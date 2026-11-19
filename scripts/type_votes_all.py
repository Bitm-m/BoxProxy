#!/usr/bin/env python3
"""The votes that the method bodies give for the counterpart of every type.

The script writes the whole table, so that the class map can be checked
against it in one pass: for every old class, the new classes that the bodies
name as its counterpart, with the number of votes and the number of owner
classes that stand behind them.

The owner classes matter: the bodies of a method are compared only inside a
pair of classes that the class map already ties together.  A vote that many
owner classes agree on is worth more than a vote that comes from a single
pair, because a single pair can be wrong.
"""
import argparse, hashlib, json, sys, collections
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_173_maps import class_index, methods, fingerprint, code_pairs, references


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--old', default='.tools/cmp/decompiled')
    parser.add_argument('--new', default='.tools/upstream-173/decompiled')
    parser.add_argument('--class-map',
                        default='upstream/26.11.17.73f2816/migration/class-map.json')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()

    old_root, new_root = Path(args.old), Path(args.new)
    old_classes = class_index(old_root)
    new_classes = class_index(new_root)
    types = json.loads(Path(args.class_map).read_text())['candidates']

    old_hashes = collections.defaultdict(list)
    for owner, path in old_classes.items():
        for signature, block in methods(path).items():
            digest = hashlib.sha256(fingerprint(block).encode()).hexdigest()
            old_hashes[digest].append((owner, signature, block))
    new_hashes = collections.defaultdict(list)
    for owner, path in new_classes.items():
        for signature, block in methods(path).items():
            digest = hashlib.sha256(fingerprint(block).encode()).hexdigest()
            new_hashes[digest].append((owner, signature, block))

    votes = collections.defaultdict(collections.Counter)
    backers = collections.defaultdict(set)
    pairs = 0
    for digest, old_matches in old_hashes.items():
        new_matches = new_hashes.get(digest)
        if not new_matches:
            continue
        for old_owner, _, old_block in old_matches:
            for new_owner, _, new_block in new_matches:
                if types.get(old_owner) != new_owner:
                    continue
                old_lines, new_lines = code_pairs(old_block), code_pairs(new_block)
                if [item[1] for item in old_lines] != [item[1] for item in new_lines]:
                    continue
                pairs += 1
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
                        votes[old_ref][new_ref] += 1
                        backers[(old_ref, new_ref)].add(old_owner)

    table = {name: {target: {'votes': count,
                             'ownerClasses': len(backers[(name, target)])}
                     for target, count in counter.most_common()}
             for name, counter in votes.items()}
    Path(args.output).write_text(json.dumps(
        {'methodPairs': pairs, 'votes': table}, indent=1) + '\n')
    print('method pairs: %d, types with votes: %d' % (pairs, len(table)))


if __name__ == '__main__':
    main()
