#!/usr/bin/env python3
"""Repair the 171 -> 173 class map where the evidence is clearly better.

The reviewed map is the baseline.  For every class the script measures how
well the mapped target reproduces the source class once the type names are
mapped as well (the *shape* score).  A class that scores well is left alone;
a class that scores poorly is re-matched against the candidates that share a
method fingerprint with it, and the candidate with the clearly better shape
score wins.

The repair is deliberately conservative: a candidate has to beat the current
target by a margin, it may not take a target that is already used, and it
has to agree with the class hierarchy (super class and interface list) as far
as the map already knows it.
"""
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)
SUPER_RE = re.compile(r'^\.super\s+(\S+)', re.M)
IFACE_RE = re.compile(r'^\.implements\s+(.+)$', re.M)
TYPE_RE = re.compile(r'L[A-Za-z0-9_/$-]+;')


def fingerprint(block):
    text = re.sub(r'^\s*\.(?:line|source|local|end local|restart local|prologue|param)\b[^\n]*',
                  '', block, flags=re.M)
    text = re.sub(r'0x7f[0-9a-f]{6}', '@', text)
    text = re.sub(r'L[^/;\s\[():]+;', 'L?;', text)
    text = re.sub(r'(L\?;->)[^\s(:]+(?=[:(])', r'\1?', text)
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '"s"', text)
    text = re.sub(r'\b[vp]\d+\b', 'r', text)
    text = re.sub(r':\w+', ':L', text)
    return '\n'.join(line.strip() for line in text.splitlines()
                     if line.strip() and not line.strip().startswith('#'))


def describe(root):
    classes = {}
    for path in (root / 'smali').rglob('*.smali'):
        text = path.read_text(errors='replace')
        match = CLASS_RE.search(text)
        if not match:
            continue
        methods = collections.Counter()
        shapes = collections.Counter()
        for block in METHOD_RE.findall(text):
            canonical = fingerprint(block)
            if len(canonical) < 24:
                continue
            methods[hashlib.sha256(canonical.encode()).hexdigest()] += 1
            shapes[tuple(sorted(TYPE_RE.findall(block.splitlines()[0])))] += 1
        interfaces = []
        for impl in IFACE_RE.finditer(text):
            interfaces.extend(impl.group(1).split())
        classes[match.group(1)] = {
            'methods': methods,
            'shapes': shapes,
            'super': (SUPER_RE.search(text) or [None, None])[1],
            'interfaces': sorted(interfaces),
        }
    return classes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--class-map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--threshold', type=float, default=0.9)
    parser.add_argument('--margin', type=float, default=0.15)
    args = parser.parse_args()

    old = describe(args.old)
    new = describe(args.new)
    document = json.loads(args.class_map.read_text())
    mapping = dict(document['candidates'])

    old_index = collections.defaultdict(set)
    for name, profile in old.items():
        for digest in profile['methods']:
            old_index[digest].add(name)
    new_index = collections.defaultdict(set)
    for name, profile in new.items():
        for digest in profile['methods']:
            new_index[digest].add(name)

    candidates = collections.defaultdict(set)
    for digest, old_owners in old_index.items():
        new_owners = new_index.get(digest)
        if not new_owners:
            continue
        for old_owner in old_owners:
            for new_owner in new_owners:
                candidates[old_owner].add(new_owner)

    def shape_score(old_owner, new_owner):
        old_shapes = collections.Counter(
            tuple(sorted(mapping.get(item, item) for item in shape))
            for shape in old[old_owner]['shapes'])
        new_shapes = new[new_owner]['shapes']
        total = sum(old_shapes.values())
        if not total:
            return 1.0
        hit = sum(min(count, new_shapes.get(shape, 0))
                  for shape, count in old_shapes.items())
        return hit / total

    def hierarchy_ok(old_owner, new_owner):
        old_profile, new_profile = old[old_owner], new[new_owner]
        old_super = old_profile['super']
        if old_super and old_super != 'Ljava/lang/Object;':
            expected = mapping.get(old_super)
            if expected and new_profile['super'] != expected:
                return False
        for interface in old_profile['interfaces']:
            expected = mapping.get(interface)
            if expected and expected not in new_profile['interfaces']:
                return False
        return True

    changes = []
    used_new = collections.Counter(mapping.values())
    for old_owner in sorted(mapping):
        current = mapping[old_owner]
        if old_owner not in old or current not in new:
            continue
        score = shape_score(old_owner, current)
        if score >= args.threshold:
            continue
        options = []
        for candidate in candidates.get(old_owner, ()):
            if candidate == current or used_new[candidate] > 1:
                continue
            if not hierarchy_ok(old_owner, candidate):
                continue
            options.append((shape_score(old_owner, candidate), candidate))
        options.sort(reverse=True)
        if not options:
            continue
        best_score, best = options[0]
        if best_score < score + args.margin:
            continue
        changes.append({'old': old_owner, 'from': current, 'to': best,
                        'score': round(score, 4), 'best': round(best_score, 4)})
        used_new[current] -= 1
        used_new[best] += 1
        mapping[old_owner] = best

    document['candidates'] = dict(sorted(mapping.items()))
    document['mapped'] = len(mapping)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1) + '\n')
    report = {'repairs': len(changes), 'changes': changes}
    if args.report:
        args.report.write_text(json.dumps(report, indent=1) + '\n')
    print('repairs: %d' % len(changes))
    for entry in changes[:60]:
        print('  %s %s -> %s (score %.3f -> %.3f)'
              % (entry['old'], entry['from'], entry['to'], entry['score'], entry['best']))


if __name__ == '__main__':
    main()
