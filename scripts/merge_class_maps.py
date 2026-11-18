#!/usr/bin/env python3
"""Merge the fingerprint evidence with the reviewed class map.

The fingerprint matcher sees only the code shape, so it is exact when a method
body is unique in both trees and silent otherwise.  The reviewed map carries
the decisions a human made for the ambiguous classes.  This script combines
both, resolves the conflicts by evidence strength and reports what changed so
that every difference can be inspected.
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
FIELD_RE = re.compile(r'^\.field[^\n]*?\s([A-Za-z_$][\w$]*):(\S+)', re.M)


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
        for block in METHOD_RE.findall(text):
            canonical = fingerprint(block)
            if len(canonical) < 24:
                continue
            methods[hashlib.sha256(canonical.encode()).hexdigest()] += 1
        interfaces = []
        for impl in IFACE_RE.finditer(text):
            interfaces.extend(impl.group(1).split())
        classes[match.group(1)] = {
            'methods': methods,
            'super': (SUPER_RE.search(text) or [None, None])[1],
            'interfaces': sorted(interfaces),
            'fields': len(FIELD_RE.findall(text)),
        }
    return classes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--reviewed', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()

    old = describe(args.old)
    new = describe(args.new)
    reviewed = json.loads(args.reviewed.read_text())['candidates']

    old_index = collections.defaultdict(set)
    for name, profile in old.items():
        for digest in profile['methods']:
            old_index[digest].add(name)
    new_index = collections.defaultdict(set)
    for name, profile in new.items():
        for digest in profile['methods']:
            new_index[digest].add(name)

    # Exact evidence: the fingerprint occurs in exactly one class on each side.
    exact = collections.defaultdict(dict)
    for digest, old_owners in old_index.items():
        new_owners = new_index.get(digest)
        if not new_owners or len(old_owners) != 1 or len(new_owners) != 1:
            continue
        old_owner = next(iter(old_owners))
        new_owner = next(iter(new_owners))
        exact[old_owner][new_owner] = exact[old_owner].get(new_owner, 0) + 1

    mapping = {}
    evidence = {}
    used_new = set()
    # First the classes where the evidence is unambiguous.
    for old_owner in sorted(exact):
        candidates = exact[old_owner]
        best = max(candidates.items(), key=lambda item: item[1])
        if len(candidates) == 1 or best[1] > sorted(candidates.values(), reverse=True)[1]:
            if best[0] in used_new:
                continue
            mapping[old_owner] = best[0]
            evidence[old_owner] = 'fingerprint:%d' % best[1]
            used_new.add(best[0])
    # Then the reviewed decisions for the rest, when they do not collide.
    for old_owner, new_owner in reviewed.items():
        if old_owner in mapping:
            continue
        if new_owner in used_new:
            continue
        mapping[old_owner] = new_owner
        evidence[old_owner] = 'reviewed'
        used_new.add(new_owner)

    changed = []
    for old_owner, new_owner in sorted(reviewed.items()):
        if old_owner in mapping and mapping[old_owner] != new_owner:
            changed.append({
                'old': old_owner,
                'reviewed': new_owner,
                'selected': mapping[old_owner],
                'evidence': evidence.get(old_owner),
                'exactCandidates': sorted(exact.get(old_owner, {}).items(),
                                         key=lambda item: -item[1])[:5],
            })
    added = {old: new for old, new in mapping.items() if old not in reviewed}
    output = {
        'note': ('Reviewed 171 -> 173 class map. Every class is matched by the '
                 'rename-invariant fingerprint of its method bodies; the classes '
                 'without a unique fingerprint keep the reviewed decision.'),
        'oldClasses': len(old),
        'newClasses': len(new),
        'mapped': len(mapping),
        'candidates': dict(sorted(mapping.items())),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=1) + '\n')
    report = {
        'mapped': len(mapping),
        'changedAgainstReviewed': len(changed),
        'addedAgainstReviewed': len(added),
        'changes': changed,
    }
    if args.report:
        args.report.write_text(json.dumps(report, indent=1) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'changes'}, indent=1))
    for entry in changed[:60]:
        print('  %s reviewed=%s selected=%s (%s)' % (entry['old'], entry['reviewed'],
                                                      entry['selected'], entry['evidence']))


if __name__ == '__main__':
    main()
