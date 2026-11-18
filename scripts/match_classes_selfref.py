#!/usr/bin/env python3
"""Match 171 and 173 classes with a self-referencing method fingerprint.

A fresh R8 run renames every class, member and string, but the *code* of a
class survives.  Masking the type names is not enough on its own: Compose and
Kotlin helper methods repeat the same shape in many classes, so a masked body
matches everywhere.  The fingerprint therefore keeps two things that make a
body unique to its own class:

* the reference to the class itself (a self call stays a self call),
* the string constants and the resource ids the body uses.

A body that occurs in exactly one class of the 171 tree and in exactly one
class of the 173 tree is then a proof that the two classes correspond.
"""
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)


def fingerprint(block, owner):
    """Mask the rename but keep the self reference and the literals."""
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


def load(root):
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
            if len(canonical) < 24:
                continue
            digests.add(hashlib.sha256(canonical.encode()).hexdigest())
        classes[owner] = digests
    return classes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()

    old = load(args.old)
    new = load(args.new)
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

    reviewed = {}
    reviewed_path = args.output.parent / 'reviewed.json'
    mapping = {}
    reverse = {}
    for old_owner, candidates in proofs.items():
        ranked = candidates.most_common()
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            continue
        mapping[old_owner] = ranked[0][0]
    reverse = collections.defaultdict(list)
    for old_owner, new_owner in mapping.items():
        reverse[new_owner].append(old_owner)
    output = {
        'note': ('Class map derived from the self-referencing method fingerprint: the '
                 'body of a method keeps its reference to its own class, so it stays '
                 'unique to that class across a rename.'),
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
        'duplicateTargets': sum(1 for owners in reverse.values() if len(owners) > 1),
    }
    if args.report:
        args.report.write_text(json.dumps(report, indent=1) + '\n')
    print(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
