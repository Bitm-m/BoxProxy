#!/usr/bin/env python3
"""Correct the class map with the votes that the method bodies give.

The bodies of the copied methods name the types they use.  When a method of
the old class and a method of the new class have the same body, the types
that the two bodies name are counterparts.  Those votes do not use the class
map, so they can be used to check it.

A class that the votes contradict cannot simply be moved: the class that
holds the wanted target has to move as well.  The script therefore collects
the classes that are entangled with each other and solves the small problem
of giving every one of them a target that no other class claims, with the
votes as the score.  The classes that the votes do not touch keep the
target they have.
"""
import argparse, json, collections, itertools, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from assignment import best_assignment


def group_of(disputes, types, votes, threshold):
    """The classes that have to move together.

    A class that wants a target which another class holds cannot take it
    while that class stays.  The group therefore grows until every wanted
    target is either free or held inside the group.
    """
    holder = {}
    for source, target in types.items():
        holder.setdefault(target, source)

    def top(source):
        table = votes.get(source)
        if not table:
            return None
        target, count = max(table.items(), key=lambda item: item[1])
        return target if count >= threshold else None

    group = set()
    frontier = list(disputes)
    while frontier:
        source = frontier.pop()
        if source in group:
            continue
        group.add(source)
        wanted = top(source)
        if wanted is None or wanted == types.get(source):
            continue
        owner = holder.get(wanted)
        if owner is not None and owner not in group:
            frontier.append(owner)
    return sorted(group)


def options_of(source, types, votes, threshold, group):
    """The targets that the class may take."""
    found = {types[source]}
    for target, count in votes.get(source, {}).items():
        if count >= threshold:
            found.add(target)
    return sorted(found)


def solve(group, types, votes, threshold, bodies=None):
    """The assignment of the group with the highest score.

    The weight of a pair is the number of votes that the method bodies give
    for it.  When the votes do not tell two classes apart, the bodies of the
    two classes themselves do: a class that keeps its methods keeps its
    bodies.  The target that the class holds now is worth one point more, so
    that a class that the evidence does not touch keeps its place.
    """
    holder = {}
    for source, target in types.items():
        holder.setdefault(target, source)
    inside = set(group)
    columns = set()
    for source in group:
        columns.add(types[source])
        for target, count in votes.get(source, {}).items():
            if count < threshold:
                continue
            owner = holder.get(target)
            if owner is None or owner in inside:
                columns.add(target)
    columns = sorted(columns)
    weight = {}
    for source in group:
        for target in columns:
            count = votes.get(source, {}).get(target, 0)
            shape = bodies(source, target) if bodies else 0
            weight[(source, target)] = (count * 10000 + shape * 10
                                        + (1 if target == types[source] else 0))
    assignment = best_assignment(weight, group, columns)
    score = sum(weight.get((source, target), 0)
                for source, target in assignment.items())
    return score, assignment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--class-map',
                        default='upstream/26.11.17.73f2816/migration/class-map.json')
    parser.add_argument('--votes', default='.tools/type-votes.json')
    parser.add_argument('--threshold', type=int, default=3)
    parser.add_argument('--output', default=None)
    parser.add_argument('--report', default=None)
    parser.add_argument('--old', default='.tools/cmp/decompiled')
    parser.add_argument('--new', default='.tools/upstream-173/decompiled')
    parser.add_argument('--no-bodies', action='store_true',
                        help='use the votes alone, without the bodies of the classes')
    parser.add_argument('--min-owners', type=int, default=0,
                        help='the least number of owner classes that stand behind a vote')
    args = parser.parse_args()

    types = json.loads(Path(args.class_map).read_text())['candidates']
    raw = json.loads(Path(args.votes).read_text())['votes']
    owner_classes = {}
    for name, table in raw.items():
        for target, info in table.items():
            owner_classes[(name, target)] = info.get('ownerClasses', 0)
    votes = raw
    if args.min_owners:
        # a vote that only a few owner classes stand behind can be the
        # result of a pair of classes that is wrong, so it is not used
        votes = {name: {target: info['votes'] for target, info in table.items()
                        if info['ownerClasses'] >= args.min_owners}
                 for name, table in votes.items()}

    bodies = None
    if not args.no_bodies:
        import resolve_class_map as resolver
        old_tree = resolver.load(Path(args.old))
        new_tree = resolver.load(Path(args.new))

        def bodies(source, target):
            if source not in old_tree or target not in new_tree:
                return 0
            return sum(min(count, new_tree[target]['plain'].get(body, 0))
                       for body, count in old_tree[source]['plain'].items())

    disputes = []
    for source, table in votes.items():
        if source not in types or not table:
            continue
        target, count = max(table.items(), key=lambda item: item[1])
        if target != types[source] and count >= args.threshold:
            disputes.append(source)

    group = group_of(disputes, types, votes, args.threshold)
    print('disputed classes: %d, classes in the group: %d'
          % (len(disputes), len(group)))
    best = solve(group, types, votes, args.threshold, bodies)
    if best is None:
        raise SystemExit('no assignment found')
    score, assignment = best

    updated = dict(types)
    report = []
    for source, target in assignment.items():
        if target != types[source]:
            report.append({'old': source, 'from': types[source], 'to': target,
                           'votes': votes.get(source, {}).get(target, 0),
                           'ownerClasses': owner_classes.get((source, target), 0),
                           'group': [s for s in group]})
            updated[source] = target

    owners = collections.defaultdict(list)
    for source, target in updated.items():
        owners[target].append(source)
    conflicts = {t: s for t, s in owners.items() if len(s) > 1}
    print('score: %d, changes: %d, conflicts: %d'
          % (score, len(report), len(conflicts)))
    for target, sources in sorted(conflicts.items()):
        print('  CONFLICT %s claimed by %s' % (target, sources))
    for item in sorted(report, key=lambda i: i['old']):
        print('  %-9s %-9s -> %-9s votes=%-5d ownerClasses=%d'
              % (item['old'], item['from'], item['to'], item['votes'],
                 item['ownerClasses']))
    if args.output and not conflicts:
        data = json.loads(Path(args.class_map).read_text())
        data['candidates'] = updated
        Path(args.output).write_text(json.dumps(data, indent=1) + '\n')
        print('wrote %s' % args.output)
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=1) + '\n')


if __name__ == '__main__':
    main()
