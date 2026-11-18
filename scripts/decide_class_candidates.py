#!/usr/bin/env python3
"""Decide between candidate targets for a 171 class with self-consistent evidence.

A candidate target has to explain the source class on its own.  The script
therefore maps the types of the source class with a mapping in which the
candidate itself is already substituted, and then measures:

* **signatures** - how many method signatures of the source class exist in
  the candidate after that mapping,
* **proofs** - how many method bodies of the source class occur in exactly one
  class of the target tree and land in the candidate,
* **references** - which share of the types the source class refers to is
  still referred to by the candidate.

The candidate that wins on all three is the right one; the report prints all
three numbers for every candidate so that a tie can be settled by hand.
"""
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method[^\n]*?([^\s(]+\([^\n]*)$', re.M)
TYPE_RE = re.compile(r'L[A-Za-z0-9_/$-]+;')
CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)


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
        refs = collections.Counter()
        for block in re.finditer(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', text, re.M | re.S):
            body = block.group(0)
            header = body.splitlines()[0]
            signature = header.split()[-1]
            signatures[signature] += 1
            canonical = fingerprint(body)
            if len(canonical) >= 24:
                digests.add(hashlib.sha256(canonical.encode()).hexdigest())
            masked = re.sub(r'"(?:[^"\\]|\\.)*"', '""', body)
            for owner in TYPE_RE.findall(masked):
                refs[owner] += 1
        classes[match.group(1)] = {
            'signatures': signatures,
            'digests': digests,
            'refs': refs,
        }
    return classes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--pairs', type=Path, required=True)
    parser.add_argument('--class-map', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()

    old = load(args.old)
    new = load(args.new)
    mapping = json.loads(args.class_map.read_text())['candidates']

    old_index = collections.defaultdict(set)
    new_index = collections.defaultdict(set)
    for name, profile in old.items():
        for digest in profile['digests']:
            old_index[digest].add(name)
    for name, profile in new.items():
        for digest in profile['digests']:
            new_index[digest].add(name)

    report = []
    for entry in json.loads(args.pairs.read_text()):
        source = entry[0]
        row = {'old': source, 'candidates': {}}
        for candidate in entry[1:]:
            local = dict(mapping)
            local[source] = candidate
            old_profile = old[source]
            new_profile = new.get(candidate)
            if new_profile is None:
                continue
            mapped = collections.Counter(
                TYPE_RE.sub(lambda match: local.get(match.group(0), match.group(0)),
                            signature)
                for signature in old_profile['signatures'])
            hit = sum(min(count, new_profile['signatures'].get(signature, 0))
                      for signature, count in mapped.items())
            unique = [digest for digest, owners in old_index.items()
                      if source in owners and len(owners) == 1]
            proofs = sum(1 for digest in unique if new_index.get(digest) == {candidate})
            total_refs = sum(old_profile['refs'].values())
            ref_hit = 0
            for owner, count in old_profile['refs'].items():
                ref_hit += min(count, new_profile['refs'].get(local.get(owner, owner), 0))
            row['candidates'][candidate] = {
                'signatures': hit,
                'oldMethods': sum(old_profile['signatures'].values()),
                'newMethods': sum(new_profile['signatures'].values()),
                'proofs': proofs,
                'uniqueBodies': len(unique),
                'references': ref_hit,
                'oldReferences': total_refs,
            }
        report.append(row)
    if args.output:
        args.output.write_text(json.dumps(report, indent=1) + '\n')
    for row in report:
        parts = []
        for candidate, score in row['candidates'].items():
            parts.append('%s sig=%d/%d proof=%d ref=%d/%d'
                         % (candidate, score['signatures'], score['oldMethods'],
                            score['proofs'], score['references'], score['oldReferences']))
        print('%-10s %s' % (row['old'], ' | '.join(parts)))


if __name__ == '__main__':
    main()
