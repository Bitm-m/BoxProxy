#!/usr/bin/env python3
"""Decide a disputed class by the classes that use it.

A class with no methods of its own cannot be told apart from another class
with no methods of its own.  The classes that use it can: the subclasses,
the classes that call its methods, and the classes that hold it in a field.
The counterpart of a class is the class that is used by the same classes.

The script prints, for every candidate, the classes that use it and how many
of them are the mapped image of the classes that use the old class.
"""
import argparse, json, re, collections
from pathlib import Path

CLASS_RE = re.compile(r'^\.class\s+(.*)$', re.M)
SUPER_RE = re.compile(r'^\.super\s+(\S+)', re.M)
IFACE_RE = re.compile(r'^\.implements\s+(.*)$', re.M)
TYPE_RE = re.compile(r'L[A-Za-z0-9_/$-]+;')
MEMBER_RE = re.compile(r'L[A-Za-z0-9_/$-]+;->')


def load(root):
    data = {}
    for path in (root / 'smali').rglob('*.smali'):
        text = path.read_text(errors='replace')
        match = CLASS_RE.search(text)
        if not match:
            continue
        owner = TYPE_RE.search(match.group(1))
        if not owner:
            continue
        data[owner.group(0)] = text
    return data


def users_of(trees, target):
    """The classes that name the target.

    A class is named by a class that holds it in a field, that inherits from
    it, that implements it, or that calls one of its members.  The last one
    counts as well: a class that is only used as the owner of a static call
    is still used by that class.
    """
    result = collections.defaultdict(set)
    for owner, text in trees.items():
        if owner == target:
            continue
        super_match = SUPER_RE.search(text)
        if super_match and super_match.group(1) == target:
            result[owner].add('super')
        impl = IFACE_RE.search(text)
        if impl:
            for item in TYPE_RE.findall(impl.group(1)):
                if item == target:
                    result[owner].add('interface')
        stripped = MEMBER_RE.sub('', text)
        if target in TYPE_RE.findall(stripped):
            result[owner].add('type')
        if (target + '->') in text:
            result[owner].add('member')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--old', default='.tools/cmp/decompiled')
    parser.add_argument('--new', default='.tools/upstream-173/decompiled')
    parser.add_argument('--class-map',
                        default='upstream/26.11.17.73f2816/migration/class-map.json')
    parser.add_argument('--changes', default=None)
    parser.add_argument('--pairs', required=True,
                        help='JSON list of [old, [candidate, ...]]')
    args = parser.parse_args()

    old = load(Path(args.old))
    new = load(Path(args.new))
    candidates = json.loads(Path(args.class_map).read_text())['candidates']
    if args.changes:
        candidates.update(json.loads(Path(args.changes).read_text()))

    for source, targets in json.loads(args.pairs):
        old_users = users_of(old, source)
        expected = {candidates[u] for u in old_users if u in candidates}
        print('=== %s  (class map says %s) ===' % (source, candidates.get(source)))
        print('  used by %d classes' % len(old_users))
        for target in targets:
            new_users = users_of(new, target)
            hit = len(expected & set(new_users))
            print('  %-8s used by %-4d classes, %d of them are the image of the old users'
                  % (target, len(new_users), hit))
            for owner in sorted(new_users)[:6]:
                print('        %s (%s)' % (owner, ','.join(sorted(new_users[owner]))))
        print()


if __name__ == '__main__':
    main()
