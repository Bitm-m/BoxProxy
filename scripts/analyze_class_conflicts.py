#!/usr/bin/env python3
"""Compare the reviewed 171 -> 173 class map with the self-reference proofs.

For every class whose proven target differs from the reviewed target the
script collects the independent evidence that can decide between the two:

* the number of self-referencing method bodies that support a target,
* how many methods of the source class have an exact body match in a target
  class, compared to the other classes of the same group,
* how well the member signatures of the two classes match,
* whether the customized methods of the migration survive the change.

The output is a report, the tool never rewrites the map.
"""
import argparse
import collections
import difflib
import hashlib
import json
import re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)
HEADER_RE = re.compile(r'^\.method\s+.*?([^ ]+\([^\n]*)$')
TYPE = re.compile(r'L[A-Za-z0-9_/$-]+;')
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


def normalize(lines):
    result = []
    for line in lines:
        line = ID_RE.sub('@', line)
        line = re.sub(r'(L[A-Za-z0-9_/$-]+;)->([^\s(:]+)', r'\1->?', line)
        line = TYPE.sub('T', line)
        line = re.sub(r'\b[vp]\d+\b', 'r', line)
        line = re.sub(r':\w+', ':L', line)
        result.append(line)
    return result


def methods_of(path):
    text = path.read_text(errors='replace')
    result = {}
    for block in METHOD_RE.findall(text):
        header = HEADER_RE.match(block.splitlines()[0])
        if not header:
            continue
        result[header.group(1)] = normalize(body_of(block))
    return result


def fingerprint(block, owner):
    text = re.sub(r'^\s*\.(?:line|source|local|end local|restart local|prologue|param)\b[^\n]*',
                  '', block, flags=re.M)
    text = text.replace(owner, 'SELF')
    text = re.sub(r'L[^/;\s\[():]+;', 'L?;', text)
    text = re.sub(r'(L\?;->)[^\s(:]+(?=[:(])', r'\1?', text)
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '"s"', text)
    text = re.sub(r'0x7f[0-9a-f]{6}', '@', text)
    text = re.sub(r'\b[vp]\d+\b', 'r', text)
    text = re.sub(r':\w+', ':L', text)
    return '\n'.join(line.strip() for line in text.splitlines()
                     if line.strip() and not line.strip().startswith('#'))


def load_digests(root):
    classes = {}
    for path in (root / 'smali').rglob('*.smali'):
        text = path.read_text(errors='replace')
        match = CLASS_RE.search(text)
        if not match:
            continue
        owner = match.group(1)
        digests = set()
        for block in METHOD_RE.findall(text):
            canonical = fingerprint(block, owner)
            if len(canonical) >= 24:
                digests.add(hashlib.sha256(canonical.encode()).hexdigest())
        classes[owner] = digests
    return classes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--class-map', type=Path, required=True)
    parser.add_argument('--coverage', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()

    old = load_digests(args.old)
    new = load_digests(args.new)
    reviewed = dict(json.loads(args.class_map.read_text())['candidates'])
    coverage = json.loads(args.coverage.read_text())
    customized = collections.defaultdict(list)
    for item in coverage['completed']:
        owner, signature = item['new'].split('->', 1)
        customized[owner].append(signature)

    old_index = collections.defaultdict(set)
    new_index = collections.defaultdict(set)
    for name, digests in old.items():
        for digest in digests:
            old_index[digest].add(name)
    for name, digests in new.items():
        for digest in digests:
            new_index[digest].add(name)
    proofs = collections.defaultdict(collections.Counter)
    for digest, old_owners in old_index.items():
        new_owners = new_index.get(digest)
        if not new_owners or len(old_owners) != 1 or len(new_owners) != 1:
            continue
        proofs[next(iter(old_owners))][next(iter(new_owners))] += 1

    method_cache = {}

    def methods_of_class(root, owner):
        key = (str(root), owner)
        if key not in method_cache:
            path = root / 'smali' / (owner[1:-1] + '.smali')
            method_cache[key] = methods_of(path) if path.is_file() else {}
        return method_cache[key]

    def exact_hits(source, target):
        source_methods = methods_of_class(args.old, source)
        target_methods = methods_of_class(args.new, target)
        if not source_methods or not target_methods:
            return 0, 0
        hits = 0
        for body in source_methods.values():
            if any(other == body for other in target_methods.values()):
                hits += 1
        return hits, len(source_methods)

    def keeps_coverage(source, target):
        if source not in customized:
            return True
        source_methods = methods_of_class(args.old, source)
        target_methods = methods_of_class(args.new, target)
        if not target_methods:
            return False
        for signature in customized[source]:
            body = source_methods.get(signature)
            if body is None:
                continue
            exact = [other for other, other_body in target_methods.items()
                     if other_body == body]
            if exact:
                continue
            scored = sorted(((difflib.SequenceMatcher(None, body, other_body,
                                                      autojunk=False).ratio(), other)
                             for other, other_body in target_methods.items()), reverse=True)
            runner_up = scored[1][0] if len(scored) > 1 else 0.0
            if not scored or scored[0][0] < 0.5 or scored[0][0] - runner_up < 0.03:
                return False
        return True

    reverse = collections.defaultdict(list)
    for source, target in reviewed.items():
        reverse[target].append(source)

    contested = []
    for source, targets in proofs.items():
        current = reviewed.get(source)
        if current is None:
            continue
        for target, count in targets.items():
            if target != current and count >= 1:
                contested.append((source, current, target, count))
                break

    entries = []
    for source, current, alternative, count in sorted(contested):
        options = sorted({current, alternative} |
                         {other for other, value in reviewed.items()
                          if value in (current, alternative) and other != source})
        evidence = []
        for target in options:
            hits, total = exact_hits(source, target)
            evidence.append({
                'target': target,
                'proofs': proofs[source].get(target, 0),
                'exactBodies': hits,
                'methods': total,
                'reviewedOwner': [other for other, value in reviewed.items()
                                  if value == target and other != source],
                'coverageKept': keeps_coverage(source, target),
            })
        entries.append({
            'old': source,
            'reviewed': current,
            'alternative': alternative,
            'proofs': count,
            'options': evidence,
        })

    report = {
        'contested': len(entries),
        'entries': entries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=1) + '\n')
    for entry in entries:
        print('%s reviewed=%s alternative=%s proofs=%d' %
              (entry['old'], entry['reviewed'], entry['alternative'], entry['proofs']))
        for option in entry['options']:
            print('    %-8s proofs=%-3d exactBodies=%d/%d coverage=%s owners=%s' %
                  (option['target'], option['proofs'], option['exactBodies'],
                   option['methods'], option['coverageKept'], option['reviewedOwner']))


if __name__ == '__main__':
    main()
