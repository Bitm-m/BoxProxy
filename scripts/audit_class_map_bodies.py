#!/usr/bin/env python3
"""Audit a 171 -> 173 class map with the shared method bodies of every pair.

The reviewed map is a hypothesis about the rename of the upstream APK.  The
strongest check that survives the rename is the method body itself: a class
that keeps its implementation keeps the bodies of its methods.  This script
computes, for every mapped pair, how many method bodies the old class shares
with the new class, and reports the pairs that share none.

A pair without a single shared body is a warning: either the class changed
completely, or the pair does not correspond at all.  The report is the input
for the manual review of the map, it never rewrites the map.
"""
import argparse
import collections
import json
import re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)


def bodies(block):
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
        line = re.sub(r'(L[A-Za-z0-9_/$-]+;)->([^\s(:]+)', r'\1->?', line)
        line = re.sub(r'L[A-Za-z0-9_/$-]+;', 'T', line)
        line = re.sub(r'\b[vp]\d+\b', 'r', line)
        line = re.sub(r':\w+', ':L', line)
        result.append(line)
    return '\n'.join(result)


def load(root):
    classes = {}
    for path in (root / 'smali').rglob('*.smali'):
        text = path.read_text(errors='replace')
        match = CLASS_RE.search(text)
        if not match:
            continue
        owner = match.group(1)
        counter = collections.Counter()
        total = 0
        for block in METHOD_RE.findall(text):
            counter[normalize(bodies(block))] += 1
            total += 1
        classes[owner] = {'bodies': counter, 'methods': total}
    return classes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--class-map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()

    old = load(args.old)
    new = load(args.new)
    class_map = dict(json.loads(args.class_map.read_text())['candidates'])

    entries = []
    buckets = collections.Counter()
    for source, target in sorted(class_map.items()):
        if source not in old or target not in new:
            entries.append({'old': source, 'new': target, 'shared': None,
                            'oldMethods': None, 'newMethods': None,
                            'missing': True})
            continue
        source_bodies = old[source]['bodies']
        target_bodies = new[target]['bodies']
        shared = sum(min(count, target_bodies.get(body, 0))
                     for body, count in source_bodies.items())
        ratio = shared / old[source]['methods'] if old[source]['methods'] else 1.0
        buckets['none' if shared == 0 else
                'low' if ratio < 0.25 else
                'mid' if ratio < 0.6 else 'high'] += 1
        entries.append({'old': source, 'new': target, 'shared': shared,
                        'oldMethods': old[source]['methods'],
                        'newMethods': new[target]['methods'],
                        'ratio': round(ratio, 4)})

    report = {
        'mapped': len(class_map),
        'buckets': dict(buckets),
        'entries': entries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=1) + '\n')
    print(json.dumps(report['buckets'], indent=1))
    if not args.quiet:
        for entry in entries:
            if entry.get('shared') == 0:
                print('  NO SHARED BODY  %s -> %s (%s/%s methods)'
                      % (entry['old'], entry['new'], entry['oldMethods'],
                         entry['newMethods']))


if __name__ == '__main__':
    main()
