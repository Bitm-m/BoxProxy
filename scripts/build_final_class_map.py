#!/usr/bin/env python3
"""Build the final 171 -> 173 class map from the self-referencing proofs.

A method body keeps its reference to its own class, so a body that occurs in
exactly one class of the 171 tree and in exactly one class of the 173 tree
identifies the two classes: the body was copied unchanged and the rename did
not touch it.  Those proofs are assigned globally and one-to-one; the classes
the proofs cannot decide keep the reviewed decision.
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


def load(root):
    classes = {}
    for path in (root / 'smali').rglob('*.smali'):
        text = path.read_text(errors='replace')
        match = CLASS_RE.search(text)
        if not match:
            continue
        owner = match.group(1)
        digests = set()
        signatures = collections.Counter()
        for block in METHOD_RE.findall(text):
            canonical = fingerprint(block, owner)
            if len(canonical) >= 24:
                digests.add(hashlib.sha256(canonical.encode()).hexdigest())
            signatures[block.splitlines()[0].split()[-1]] += 1
        classes[owner] = {'digests': digests, 'signatures': signatures}
    return classes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--reviewed', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()

    old = load(args.old)
    new = load(args.new)
    reviewed = json.loads(args.reviewed.read_text())['candidates']

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
            return 0.0
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

    candidates = []
    for source, targets in proofs.items():
        for target, count in targets.items():
            candidates.append((count, source, target))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))

    mapping = {}
    used = set()
    proof_count = {}
    for count, source, target in candidates:
        if source in mapping or target in used:
            continue
        mapping[source] = target
        used.add(target)
        proof_count[source] = count
    assigned_by_proof = len(mapping)

    # A target that several source classes claim is given to the class with
    # the strongest proof; the others are re-matched with the reviewed map.
    for source, target in reviewed.items():
        if source in mapping or target in used:
            continue
        mapping[source] = target
        used.add(target)
        proof_count[source] = 0

    changes = []
    for source, target in sorted(reviewed.items()):
        if source in mapping and mapping[source] != target:
            changes.append({
                'old': source,
                'reviewed': target,
                'selected': mapping[source],
                'proofs': proof_count.get(source, 0),
                'reviewedProofs': proofs[source].get(target, 0),
                'signatureScore': round(signature_score(mapping, source, mapping[source]), 4),
                'reviewedSignatureScore': round(signature_score(mapping, source, target), 4),
            })
    added = [source for source in mapping if source not in reviewed]

    output = {
        'note': ('Reviewed 171 -> 173 class map. A method body keeps the reference to '
                 'its own class, so a body that is unique in both trees proves which '
                 'two classes correspond; the reviewed decision covers the rest.'),
        'oldClasses': len(old),
        'newClasses': len(new),
        'mapped': len(mapping),
        'candidates': dict(sorted(mapping.items())),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=1) + '\n')
    report = {
        'mapped': len(mapping),
        'assignedByProof': assigned_by_proof,
        'changedAgainstReviewed': len(changes),
        'addedAgainstReviewed': len(added),
        'changes': changes,
    }
    if args.report:
        args.report.write_text(json.dumps(report, indent=1) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'changes'}, indent=1))
    for entry in changes:
        print('  %s: reviewed=%s -> %s (proofs %d vs %d, signature %.3f vs %.3f)'
              % (entry['old'], entry['reviewed'], entry['selected'], entry['proofs'],
                 entry['reviewedProofs'], entry['signatureScore'],
                 entry['reviewedSignatureScore']))


if __name__ == '__main__':
    main()
