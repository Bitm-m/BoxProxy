#!/usr/bin/env python3
"""Assign every 171 class to a 173 class with a global one-to-one assignment.

The proof is a method body that occurs in exactly one class of the 171 tree
and in exactly one class of the 173 tree: that body was copied unchanged, so
the two classes correspond.  Proofs are counted for every candidate pair, and
the assignment that follows is global and one-to-one: when two source classes
want the same target, the class with more proofs wins and the other one is
re-matched with the remaining evidence.

The reviewed map is the baseline for everything the proofs do not decide, so
the result only moves a class when the evidence is clearly better.
"""
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)
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


def load(root):
    classes = {}
    for path in (root / 'smali').rglob('*.smali'):
        text = path.read_text(errors='replace')
        match = CLASS_RE.search(text)
        if not match:
            continue
        signatures = collections.Counter()
        digests = set()
        for block in METHOD_RE.findall(text):
            header = block.splitlines()[0]
            signatures[header.split()[-1]] += 1
            canonical = fingerprint(block)
            if len(canonical) >= 24:
                digests.add(hashlib.sha256(canonical.encode()).hexdigest())
        classes[match.group(1)] = {'signatures': signatures, 'digests': digests}
    return classes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--class-map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()

    old = load(args.old)
    new = load(args.new)
    document = json.loads(args.class_map.read_text())
    reviewed = dict(document['candidates'])

    old_index = collections.defaultdict(set)
    new_index = collections.defaultdict(set)
    for name, profile in old.items():
        for digest in profile['digests']:
            old_index[digest].add(name)
    for name, profile in new.items():
        for digest in profile['digests']:
            new_index[digest].add(name)

    proofs = collections.defaultdict(collections.Counter)
    for digest, old_owners in old_index.items():
        new_owners = new_index.get(digest)
        if not new_owners or len(old_owners) != 1 or len(new_owners) != 1:
            continue
        proofs[next(iter(old_owners))][next(iter(new_owners))] += 1

    def signature_score(mapping, source, target):
        if target not in new:
            return 0
        local = dict(mapping)
        local[source] = target
        old_profile, new_profile = old[source], new[target]
        mapped = collections.Counter(
            TYPE_RE.sub(lambda match: local.get(match.group(0), match.group(0)),
                        signature)
            for signature in old_profile['signatures'])
        hit = sum(min(count, new_profile['signatures'].get(signature, 0))
                  for signature, count in mapped.items())
        total = sum(old_profile['signatures'].values())
        return hit / total if total else 0.0

    # Global assignment: the pairs with the most proofs come first.
    pairs = []
    for source, candidates in proofs.items():
        for target, count in candidates.items():
            pairs.append((count, source, target))
    pairs.sort(key=lambda item: (-item[0], item[1], item[2]))

    mapping = {}
    used_new = set()
    assigned_by_proof = 0
    for count, source, target in pairs:
        if source in mapping or target in used_new:
            continue
        mapping[source] = target
        used_new.add(target)
        assigned_by_proof += 1

    # The reviewed decisions fill the classes the proofs cannot decide.
    for source, target in reviewed.items():
        if source in mapping or target in used_new:
            continue
        mapping[source] = target
        used_new.add(target)

    changes = []
    for source, target in sorted(reviewed.items()):
        if source in mapping and mapping[source] != target:
            changes.append({
                'old': source,
                'reviewed': target,
                'selected': mapping[source],
                'proofs': proofs[source].get(mapping[source], 0),
                'reviewedProofs': proofs[source].get(target, 0),
                'signatureScore': round(signature_score(mapping, source, mapping[source]), 4),
                'reviewedSignatureScore': round(signature_score(mapping, source, target), 4),
            })

    document['candidates'] = dict(sorted(mapping.items()))
    document['mapped'] = len(mapping)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1) + '\n')
    report = {
        'mapped': len(mapping),
        'assignedByProof': assigned_by_proof,
        'changedAgainstReviewed': len(changes),
        'changes': changes,
    }
    if args.report:
        args.report.write_text(json.dumps(report, indent=1) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'changes'}, indent=1))
    for entry in changes:
        print('  %s: reviewed=%s -> %s (proof %d vs %d, sig %.2f vs %.2f)'
              % (entry['old'], entry['reviewed'], entry['selected'], entry['proofs'],
                 entry['reviewedProofs'], entry['signatureScore'],
                 entry['reviewedSignatureScore']))


if __name__ == '__main__':
    main()
