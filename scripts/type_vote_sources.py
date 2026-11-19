#!/usr/bin/env python3
"""Show the method pairs that give a vote for the counterpart of a type."""
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
    parser.add_argument('--type', required=True)
    parser.add_argument('--limit', type=int, default=12)
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

    shown = 0
    tally = collections.Counter()
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
                for (old_line, _), (new_line, _) in zip(old_lines, new_lines):
                    old_refs, new_refs = references(old_line), references(new_line)
                    if len(old_refs) != len(new_refs):
                        continue
                    for (old_category, old_ref), (new_category, new_ref) in zip(
                            old_refs, new_refs):
                        if old_category != new_category or old_ref != args.type:
                            continue
                        if not new_ref.startswith('L'):
                            continue
                        tally[(old_owner, new_owner, new_ref)] += 1
                        if shown < args.limit:
                            shown += 1
                            print('pair %s->%s  %s.%s  |  %s.%s'
                                  % (old_owner, new_owner, old_owner, old_signature,
                                     new_owner, new_signature))
                            print('   old: %s' % old_line.strip())
                            print('   new: %s' % new_line.strip())
    print()
    for key, count in tally.most_common(20):
        print('%4d  owner pair %s -> %s   type -> %s' % (count, key[0], key[1], key[2]))


if __name__ == '__main__':
    main()
