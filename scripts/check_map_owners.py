#!/usr/bin/env python3
"""Check that a member map keeps every member inside its own class.

The member map is built from the class map: the members of a class are only
matched with the members of the class that the class map points at.  A member
that is matched with a member of another class means that the class map and
the member map disagree, and the migration would move a call to a method of
a class that does not have it.

The script also reports the classes that the map leaves without a target and
the targets that no class claims.
"""
import argparse, json, collections
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--class-map', required=True)
    parser.add_argument('--member-map', required=True)
    parser.add_argument('--changed', default=None,
                        help='JSON object of classes whose target changed')
    args = parser.parse_args()

    class_map = json.loads(Path(args.class_map).read_text())
    candidates = dict(class_map['candidates'])
    if args.changed:
        candidates.update(json.loads(Path(args.changed).read_text()))
    members = json.loads(Path(args.member_map).read_text())

    def owner_of(key):
        # a member key is "<owner>-><name>:<descriptor>" or "<owner>-><name>"
        return key.split('->', 1)[0]

    bad = []
    for kind in ('members', 'fields'):
        table = members.get(kind, {})
        for old, spec in table.items():
            new = spec['new'] if isinstance(spec, dict) else spec
            old_owner = owner_of(old)
            new_owner = owner_of(new)
            if candidates.get(old_owner) != new_owner:
                bad.append((kind, old, new, old_owner, new_owner))

    owners = collections.defaultdict(list)
    for source, target in candidates.items():
        owners[target].append(source)
    conflicts = {t: s for t, s in owners.items() if len(s) > 1}

    print('classes: %d' % len(candidates))
    print('members: %d' % len(members.get('members', {})))
    print('fields: %d' % len(members.get('fields', {})))
    print('owner mismatches: %d' % len(bad))
    for kind, old, new, oo, no in bad[:20]:
        print('  %s %s -> %s (owner %s should be %s)' % (kind, old, new, no, oo))
    print('target conflicts: %d' % len(conflicts))
    for target, sources in sorted(conflicts.items()):
        print('  %s claimed by %s' % (target, sources))
    return 1 if bad or conflicts else 0


if __name__ == '__main__':
    raise SystemExit(main())
