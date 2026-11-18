#!/usr/bin/env python3
"""Check how many unique method bodies of a 171 class land in a 173 class.

A method body that occurs in exactly one class of the 171 tree and in exactly
one class of the 173 tree is a *proof* that the two classes correspond: the
body was copied unchanged and the rename did not touch it.  Counting how many
such proofs a candidate pair collects shows which of two candidate targets is
the real one.
"""
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)


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
    result = {}
    for path in (root / 'smali').rglob('*.smali'):
        text = path.read_text(errors='replace')
        match = re.search(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', text, re.M)
        if not match:
            continue
        digests = set()
        for block in METHOD_RE.findall(text):
            canonical = fingerprint(block)
            if len(canonical) < 24:
                continue
            digests.add(hashlib.sha256(canonical.encode()).hexdigest())
        result[match.group(1)] = digests
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--pairs', type=Path, required=True,
                        help='JSON list of [old, candidateA, candidateB] triples')
    parser.add_argument('--output', type=Path)
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

    def transfer(source, target):
        unique = [digest for digest, owners in old_index.items()
                  if source in owners and len(owners) == 1]
        if not unique:
            return {'uniqueBodies': 0, 'transferred': 0, 'ratio': 0.0}
        hit = 0
        for digest in unique:
            owners = new_index.get(digest)
            if owners == {target}:
                hit += 1
        return {'uniqueBodies': len(unique), 'transferred': hit,
                'ratio': round(hit / len(unique), 4)}

    pairs = json.loads(args.pairs.read_text())
    report = []
    for entry in pairs:
        source = entry[0]
        row = {'old': source, 'candidates': {}}
        for candidate in entry[1:]:
            row['candidates'][candidate] = transfer(source, candidate)
        report.append(row)
    if args.output:
        args.output.write_text(json.dumps(report, indent=1) + '\n')
    for row in report:
        parts = []
        for candidate, score in row['candidates'].items():
            parts.append('%s=%d/%d' % (candidate, score['transferred'], score['uniqueBodies']))
        print('%-10s %s' % (row['old'], '  '.join(parts)))


if __name__ == '__main__':
    main()
