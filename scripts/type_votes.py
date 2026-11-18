#!/usr/bin/env python3
"""The votes that the method bodies give for the counterpart of a type.

A method that is copied keeps its body, and the body names the types it
uses.  When a method of the old class and a method of the new class have the
same body, the types that the two bodies name are counterparts.  These votes
do not use the class map at all: they are the evidence that the class map is
checked against.

The script prints, for every type that is asked about, the votes that the
bodies give for it.
"""
import argparse, hashlib, json, re, sys, collections
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_173_maps import (class_index, methods, fingerprint, code_pairs,
                            references, TYPE_RE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--old', default='.tools/cmp/decompiled')
    parser.add_argument('--new', default='.tools/upstream-173/decompiled')
    parser.add_argument('--class-map',
                        default='upstream/26.11.17.73f2816/migration/class-map.json')
    parser.add_argument('--types', required=True,
                        help='JSON list of the types to report on')
    parser.add_argument('--output', default=None)
    args = parser.parse_args()

    old_root, new_root = Path(args.old), Path(args.new)
    old_classes = class_index(old_root)
    new_classes = class_index(new_root)
    types = json.loads(Path(args.class_map).read_text())['candidates']

    old_hashes = collections.defaultdict(list)
    for owner, path in old_classes.items():
        for signature, block in methods(path).items():
            canonical = fingerprint(block)
            old_hashes[hashlib.sha256(canonical.encode()).hexdigest()].append(
                (owner, signature, block))
    new_hashes = collections.defaultdict(list)
    for owner, path in new_classes.items():
        for signature, block in methods(path).items():
            canonical = fingerprint(block)
            new_hashes[hashlib.sha256(canonical.encode()).hexdigest()].append(
                (owner, signature, block))

    wanted = set(json.loads(args.types))
    votes = collections.defaultdict(collections.Counter)
    pair_count = 0
    for digest, old_matches in old_hashes.items():
        new_matches = new_hashes.get(digest)
        if not new_matches:
            continue
        for old_owner, old_signature, old_block in old_matches:
            for new_owner, new_signature, new_block in new_matches:
                if types.get(old_owner) != new_owner:
                    continue
                old_lines, new_lines = code_pairs(old_block), code_pairs(new_block)
                if [item[1] for item in old_lines] != [item[1] for item in new_lines]:
                    continue
                pair_count += 1
                for (old_line, _), (new_line, _) in zip(old_lines, new_lines):
                    old_refs, new_refs = references(old_line), references(new_line)
                    if len(old_refs) != len(new_refs):
                        continue
                    for (old_category, old_ref), (new_category, new_ref) in zip(
                            old_refs, new_refs):
                        if old_category != new_category:
                            continue
                        if old_ref == new_ref or not old_ref.startswith('L'):
                            continue
                        if old_ref in wanted:
                            votes[old_ref][new_ref] += 1
    print('method pairs used: %d' % pair_count)
    for name in sorted(wanted):
        print('%-10s (class map says %-8s) votes: %s'
              % (name, types.get(name), dict(votes[name].most_common(6))))


if __name__ == '__main__':
    main()
