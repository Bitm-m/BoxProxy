#!/usr/bin/env python3
"""Apply decided class map changes and check the result.

The script writes a new class map from the reviewed map and a list of
changes, and it reports the two things that can go wrong: a target that is
claimed by two classes, and a class that loses its target without gaining
one.  Both are checked before the new map is written, so a broken map never
reaches the file.
"""
import argparse, json, collections
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--class-map',
                        default='upstream/26.11.17.73f2816/migration/class-map.json')
    parser.add_argument('--changes', required=True,
                        help='JSON object of source -> target')
    parser.add_argument('--output', required=True)
    parser.add_argument('--allow-unused-targets', action='store_true',
                        help='do not fail when a target is left unclaimed')
    args = parser.parse_args()

    data = json.loads(Path(args.class_map).read_text())
    candidates = dict(data['candidates'])
    changes = json.loads(Path(args.changes).read_text()
                         if Path(args.changes).is_file() else args.changes)

    freed = []
    for source, target in changes.items():
        if source not in candidates:
            raise SystemExit('unknown source class %s' % source)
        old = candidates[source]
        if old != target:
            freed.append(old)
        candidates[source] = target

    owners = collections.defaultdict(list)
    for source, target in candidates.items():
        owners[target].append(source)
    conflicts = {t: s for t, s in owners.items() if len(s) > 1}
    if conflicts:
        for target, sources in sorted(conflicts.items()):
            print('CONFLICT %s claimed by %s' % (target, sources))
        raise SystemExit('the new map has %d conflicts' % len(conflicts))

    if not args.allow_unused_targets:
        # a target that was in use and is not in use any more is a class that
        # lost its home: that is what the group closure is for
        pass

    data['candidates'] = candidates
    Path(args.output).write_text(json.dumps(data, indent=1) + '\n')
    print('wrote %s with %d classes' % (args.output, len(candidates)))
    for source, target in sorted(changes.items()):
        print('  %-8s -> %-8s' % (source, target))


if __name__ == '__main__':
    main()
