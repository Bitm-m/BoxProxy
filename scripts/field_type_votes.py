#!/usr/bin/env python3
"""The counterpart of every type, according to the fields that hold it.

A field keeps its name when the class is renamed, and the type of the field
is written out.  When a method of the old class and a method of the new
class have the same body, the fields that the two bodies name are the same
fields, and the types of those fields are counterparts.  This is the
strongest evidence that the trees give: the name of the field and the name
of its class both have to agree.

The script prints, for every type that is asked about, the types that the
fields name as its counterpart, with the number of fields and the number of
owner classes that stand behind them.
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
    parser.add_argument('--types', default=None,
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
                        if old_category != 'fields' or new_category != 'fields':
                            continue
                        old_owner_name, _, old_rest = old_ref.partition('->')
                        new_owner_name, _, new_rest = new_ref.partition('->')
                        old_name, _, old_type = old_rest.partition(':')
                        new_name, _, new_type = new_rest.partition(':')
                        if old_name != new_name:
                            continue
                        if not old_type.startswith('L') or not new_type.startswith('L'):
                            continue
                        votes[old_type][new_type] += 1
                        backers[(old_type, new_type)].add(old_owner)

    table = {name: {target: {'votes': count,
                             'ownerClasses': len(backers[(name, target)])}
                     for target, count in counter.most_common()}
             for name, counter in votes.items()}
    if args.output:
        Path(args.output).write_text(json.dumps(
            {'methodPairs': pairs, 'fieldTypeVotes': table}, indent=1) + '\n')
        print('method pairs: %d, types with field votes: %d' % (pairs, len(table)))
    if args.types:
        for name in json.loads(args.types):
            table_for = table.get(name, {})
            print('%-10s (class map says %-9s)'
                  % (name, types.get(name)))
            for target, info in list(table_for.items())[:5]:
                print('      -> %-10s fields=%-4d ownerClasses=%d'
                      % (target, info['votes'], info['ownerClasses']))


if __name__ == '__main__':
    main()
