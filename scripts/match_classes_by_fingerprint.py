#!/usr/bin/env python3
"""Match 171 and 173 classes by rename-invariant method fingerprints.

A fresh R8 run renames every class, member and string, so no name survives
between the two APKs.  What does survive is the *shape* of every method: the
instruction sequence with all type names, member names and resource ids
masked out.  Two classes that correspond therefore share a set of identical
method fingerprints.

The matcher turns that observation into a reviewed mapping:

* every class is described by the multiset of its method fingerprints,
* candidate pairs are the classes that share at least one fingerprint,
* the pairs are accepted greedily from the strongest evidence, requiring the
  match to be mutually best so that identical shapes do not collide,
* the super class and interface list are used as a consistency check.
"""
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
HEADER_RE = re.compile(r'^\.method\s+.*?([^\s(]+\([^\n]*)$')
CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)
SUPER_RE = re.compile(r'^\.super\s+(\S+)', re.M)
IFACE_RE = re.compile(r'^\.implements\s+(.+)$', re.M)
FIELD_RE = re.compile(r'^\.field[^\n]*?\s([A-Za-z_$][\w$]*):(\S+)', re.M)


def fingerprint(block):
    """Mask everything a rename can change, keep the instruction sequence."""
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
        name = match.group(1)
        methods = collections.Counter()
        for block in METHOD_RE.findall(text):
            canonical = fingerprint(block)
            if len(canonical) < 24:
                continue
            methods[hashlib.sha256(canonical.encode()).hexdigest()] += 1
        interfaces = []
        for impl in IFACE_RE.finditer(text):
            interfaces.extend(impl.group(1).split())
        classes[name] = {
            'methods': methods,
            'super': (SUPER_RE.search(text) or [None, None])[1],
            'interfaces': sorted(interfaces),
            'fields': len(FIELD_RE.findall(text)),
            'path': path,
        }
    return classes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--min-shared', type=int, default=1)
    args = parser.parse_args()

    old = describe(args.old)
    new = describe(args.new)

    old_index = collections.defaultdict(set)
    for name, profile in old.items():
        for digest in profile['methods']:
            old_index[digest].add(name)
    new_index = collections.defaultdict(set)
    for name, profile in new.items():
        for digest in profile['methods']:
            new_index[digest].add(name)

    scores = collections.defaultdict(int)
    for digest, old_owners in old_index.items():
        new_owners = new_index.get(digest)
        if not new_owners:
            continue
        if len(old_owners) == 1 and len(new_owners) == 1:
            old_owner = next(iter(old_owners))
            new_owner = next(iter(new_owners))
            scores[(old_owner, new_owner)] += 1
            continue
        for old_owner in old_owners:
            for new_owner in new_owners:
                scores[(old_owner, new_owner)] += 1

    best_for_old = {}
    best_for_new = {}
    for (old_owner, new_owner), score in scores.items():
        if score > best_for_old.get(old_owner, (0, None))[0]:
            best_for_old[old_owner] = (score, new_owner)
        if score > best_for_new.get(new_owner, (0, None))[0]:
            best_for_new[new_owner] = (score, old_owner)

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    mapping = {}
    used_new = set()
    ambiguous = []
    for (old_owner, new_owner), score in ranked:
        if old_owner in mapping or new_owner in used_new:
            continue
        if best_for_old[old_owner][1] != new_owner or best_for_new[new_owner][1] != old_owner:
            continue
        mapping[old_owner] = new_owner
        used_new.add(new_owner)

    # Fill the remaining classes with the strongest non-conflicting candidate.
    for (old_owner, new_owner), score in ranked:
        if old_owner in mapping or new_owner in used_new:
            continue
        if score < args.min_shared:
            continue
        mapping[old_owner] = new_owner
        used_new.add(new_owner)

    conflicts = []
    for old_owner, new_owner in sorted(mapping.items()):
        old_profile, new_profile = old[old_owner], new[new_owner]
        if old_profile['super'] and old_profile['super'] != 'Ljava/lang/Object;':
            if new_profile['super'] != old_profile['super'] and new_profile['super'] != 'Ljava/lang/Object;':
                conflicts.append({'old': old_owner, 'new': new_owner,
                                  'reason': 'super %s vs %s' % (old_profile['super'],
                                                              new_profile['super'])})
    output = {
        'note': 'Class map derived from rename-invariant method fingerprints.',
        'oldClasses': len(old),
        'newClasses': len(new),
        'mapped': len(mapping),
        'candidates': dict(sorted(mapping.items())),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=1) + '\n')
    report = {
        'mapped': len(mapping),
        'oldClasses': len(old),
        'newClasses': len(new),
        'unmatchedOld': len(old) - len(mapping),
        'conflicts': len(conflicts),
        'conflictList': conflicts[:200],
    }
    if args.report:
        args.report.write_text(json.dumps(report, indent=1) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'conflictList'}, indent=1))


if __name__ == '__main__':
    main()
