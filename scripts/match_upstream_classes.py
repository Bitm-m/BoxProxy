#!/usr/bin/env python3
"""Match upstream Smali classes between two pinned Apktool trees.

A fresh R8 run reassigns every obfuscated name, so class identity cannot be
recovered from names. This matcher recovers it from content and structure:

  1. method-body fingerprints (types masked) seed the mapping,
  2. the seed map is used to re-normalise bodies with *mapped* types, which
     separates classes that only differ in the types they touch,
  3. classes that remain ambiguous are resolved by the order in which a
     referring class mentions them (anchored positional alignment),
  4. one-to-one violations are repaired by dropping the weaker candidate,
  5. reviewed exceptions are applied from an override table.

The output is a review artifact: it never rewrites runtime code.
"""
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

TYPE = re.compile(r'L[A-Za-z0-9_/$-]+;')
CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)
METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
HEADER_RE = re.compile(r'^\.method\s+.*?([^ ]+\([^\n]*)$')
FIELD_RE = re.compile(r'^\.field[^\n]*?\s([A-Za-z_$][\w$]*):(\S+)', re.M)
STRING_RE = re.compile(r'const-string(?:/jumbo)?\s+[vp]\d+,\s+(".*?")')
ID_RE = re.compile(r'0x7f[0-9a-f]{6}')


def body_of(block):
    out = []
    for line in block.splitlines()[1:-1]:
        stripped = line.strip()
        if not stripped or stripped.startswith((
                '.line ', '.source ', '.local ', '.end local ', '.restart local ',
                '.param ', '.end param ', '.prologue', '#')):
            continue
        out.append(stripped)
    return out


def normalize(lines, mapping=None):
    result = []
    for line in lines:
        line = ID_RE.sub('@', line)
        if mapping is None:
            line = TYPE.sub(lambda m: m.group(0), line)
        else:
            line = TYPE.sub(lambda m: mapping.get(m.group(0), m.group(0)), line)
        line = re.sub(r'(L[A-Za-z0-9_/$-]+;)->([^\s(:]+)', r'\1->?', line)
        line = re.sub(r'\b[vp]\d+\b', 'r', line)
        line = re.sub(r':\w+', ':L', line)
        result.append(line)
    return result


def load(root, mapping=None):
    result = {}
    for path in (root / 'smali').rglob('*.smali'):
        text = path.read_text(errors='replace')
        match = CLASS_RE.search(text)
        if not match:
            continue
        descriptor = match.group(1)
        methods, seen, ordered, signatures = [], set(), [], set()
        for block in METHOD_RE.findall(text):
            header = HEADER_RE.match(block.splitlines()[0])
            if not header:
                continue
            methods.append(normalize(body_of(block), mapping))
            params, _, ret = header.group(1).partition(')')
            signatures.add('(' + ','.join(sorted(TYPE.findall(params))) + ')'
                            + ','.join(sorted(TYPE.findall(ret))))
        for item in TYPE.findall(text):
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        result[descriptor] = dict(methods=methods, ordered=ordered,
                                  signatures=signatures,
                                  strings=set(STRING_RE.findall(text)))
    return result


def seed_by_content(old, new):
    """Score candidate pairs from method bodies, signatures and strings."""
    body_index = collections.defaultdict(set)
    signature_index = collections.defaultdict(set)
    string_index = collections.defaultdict(set)
    for descriptor, info in new.items():
        for lines in info['methods']:
            if len(lines) > 2:
                body_index['\n'.join(lines)].add(descriptor)
        for signature in info['signatures']:
            signature_index[signature].add(descriptor)
        for value in info['strings']:
            string_index[value].add(descriptor)
    scores = {}
    for descriptor, info in old.items():
        counter = collections.Counter()
        for lines in info['methods']:
            if len(lines) > 2:
                for target in body_index.get('\n'.join(lines), ()):
                    counter[target] += 3
        for signature in info['signatures']:
            for target in signature_index.get(signature, ()):
                counter[target] += 1
        for value in info['strings']:
            for target in string_index.get(value, ()):
                counter[target] += 1
        if counter:
            scores[descriptor] = counter
    mapping, used = {}, set()
    for descriptor, counter in sorted(scores.items(),
                                     key=lambda item: (-max(item[1].values()), item[0])):
        ranked = counter.most_common()
        if not ranked or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]):
            continue
        target = ranked[0][0]
        if target in used:
            continue
        mapping[descriptor] = target
        used.add(target)
    return mapping


def refine(old, new, mapping):
    """Re-match with mapped types; this separates structurally identical twins."""
    index = collections.defaultdict(set)
    for descriptor, info in new.items():
        for lines in info['methods']:
            if len(lines) > 2:
                index['\n'.join(lines)].add(descriptor)
    for _ in range(8):
        mapped_old = load(old['root'], mapping)
        votes = collections.defaultdict(collections.Counter)
        for descriptor, info in mapped_old.items():
            for lines in info['methods']:
                if len(lines) <= 2:
                    continue
                for target in index.get('\n'.join(lines), ()):
                    votes[descriptor][target] += 1
        changed = 0
        for descriptor, counts in votes.items():
            ranked = counts.most_common()
            if not ranked or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]):
                continue
            if mapping.get(descriptor) != ranked[0][0]:
                changed += 1
            mapping[descriptor] = ranked[0][0]
        if not changed:
            break
    return mapping


def align(old_seq, new_seq, mapping):
    """Pair unmentioned references by anchoring on already mapped ones."""
    new_index = {}
    for index, item in enumerate(new_seq):
        new_index.setdefault(item, index)
    anchors = []
    for index, item in enumerate(old_seq):
        if item in mapping and mapping[item] in new_index:
            anchors.append((index, new_index[mapping[item]]))
    if not anchors:
        return []
    anchors.sort()
    pairs = []
    for (old_at, new_at), (next_old, next_new) in zip(
            anchors, anchors[1:] + [(len(old_seq), len(new_seq))]):
        unknown_old = [i for i in range(old_at + 1, next_old) if old_seq[i] not in mapping]
        used_new = {j for _, j in anchors if new_at < j < next_new}
        free_new = [j for j in range(new_at + 1, next_new) if j not in used_new]
        if unknown_old and len(unknown_old) == len(free_new):
            for i, j in zip(unknown_old, free_new):
                pairs.append((old_seq[i], new_seq[j]))
    return pairs


def resolve_positional(old, new, mapping):
    for _ in range(4):
        votes = collections.defaultdict(collections.Counter)
        for descriptor, info in old.items():
            target = mapping.get(descriptor)
            if not target:
                continue
            new_seq = new[target]['ordered']
            for source, destination in align(info['ordered'], new_seq, mapping):
                if source not in old or destination not in new:
                    continue
                if source in mapping or destination in mapping.values():
                    continue
                votes[source][destination] += 1
        added = 0
        for source, counts in votes.items():
            ranked = counts.most_common()
            if not ranked or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]):
                continue
            mapping[source] = ranked[0][0]
            added += 1
        if not added:
            break
    return mapping


def repair_conflicts(old, new, mapping, seed):
    """Keep the stronger candidate when two sources claim the same target."""
    reverse = collections.defaultdict(list)
    for source, target in mapping.items():
        reverse[target].append(source)
    for target, sources in reverse.items():
        if len(sources) < 2:
            continue
        keeper = seed.get(target)
        if keeper is None or keeper not in sources:
            keeper = max(sources, key=lambda s: (
                len(old[s]['strings'] & new[target]['strings']),
                len(old[s]['methods']), -len(s)))
        for source in sources:
            if source == keeper:
                continue
            best = None
            for candidate, info in new.items():
                if candidate in mapping.values() and candidate != target:
                    continue
                if candidate == target:
                    continue
                score = (len(old[source]['strings'] & info['strings']),
                         len(old[source]['methods']) - abs(len(info['methods']) - len(old[source]['methods'])))
                if best is None or score > best[0]:
                    best = (score, candidate)
            if best:
                mapping[source] = best[1]
    return mapping


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--overrides', type=Path)
    args = parser.parse_args()

    old = load(args.old)
    new = load(args.new)
    mapping = seed_by_content(old, new)
    print('fingerprint seed:', len(mapping))
    mapping = refine({'root': args.old}, new, mapping)
    print('after refinement:', len(mapping))
    seed = dict(mapping)
    mapping = resolve_positional(old, new, mapping)
    print('after positional resolution:', len(mapping))
    mapping = repair_conflicts(old, new, mapping, seed)
    print('after conflict repair:', len(mapping))
    if args.overrides:
        overrides = json.loads(args.overrides.read_text())
        for source, target in overrides['classes'].items():
            mapping[source] = target
        print('applied reviewed overrides:', len(overrides['classes']))

    reverse = collections.defaultdict(list)
    for source, target in mapping.items():
        reverse[target].append(source)
    conflicts = {target: sources for target, sources in reverse.items() if len(sources) > 1}
    unmapped = sorted(set(old) - set(mapping))
    report = {
        'oldClasses': len(old),
        'newClasses': len(new),
        'mapped': len(mapping),
        'conflicts': {k: v for k, v in conflicts.items()},
        'unmapped': unmapped,
    }
    args.output.write_text(json.dumps({
        'warning': 'review artifact; the porter validates every reference again',
        'candidates': mapping,
    }, indent=1) + '\n')
    if args.report:
        args.report.write_text(json.dumps(report, indent=1) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'unmapped'}, indent=1)[:400])
    print('unmapped:', len(unmapped))


if __name__ == '__main__':
    main()
