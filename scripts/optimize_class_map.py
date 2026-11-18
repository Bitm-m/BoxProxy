#!/usr/bin/env python3
"""Improve the class map by the shape of the classes and by the votes.

Two kinds of evidence are used together.

The shape of a class says how well the methods of a class fit the class
that the map gives them: the parameters and the return types are translated
with the map and compared with the methods that the new class declares.
That measurement does not use the map of the class itself, so it can be used
to choose a better target.

The votes of the method bodies say which type is the counterpart of another
type: when a method of the old class and a method of the new class have the
same body, the fields that the two bodies name are the same fields, and the
types of those fields are counterparts.  Those votes do not use the class
map either.

The shape comes first: a class whose methods do not fit the class it is
given is wrong, whatever the votes say.  The votes then decide between the
targets that fit equally well, which is where two classes that look alike
are told apart.

The map has to stay one to one, so a move that takes the target of another
class takes that class along.  A group of entangled classes is resolved as
one problem, and the group is only kept when the map as a whole gets better.
"""
import argparse, collections, json, math, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_class_map import profile, normalize_shape
from assignment import best_assignment

SHIFT = 1000.0


class Universe:
    """The profiles of the two trees, and the score of the map."""

    def __init__(self, old_root, new_root):
        self.old = {}
        self.new = {}
        for path in (old_root / 'smali').rglob('*.smali'):
            owner = owner_of(path)
            if owner:
                self.old[owner] = profile(path)
        for path in (new_root / 'smali').rglob('*.smali'):
            owner = owner_of(path)
            if owner:
                self.new[owner] = profile(path)
        self.new_shapes = {}
        for owner, data in self.new.items():
            self.new_shapes[owner] = collections.Counter(
                normalize_shape(shape, {}) for shape in data['methodShapes'])

    def penalty(self, source, target, class_map):
        """The penalty of a class on a target; the smaller the better."""
        old = self.old[source]
        new = self.new.get(target)
        if new is None:
            return 10.0
        remapped = collections.Counter(
            normalize_shape(shape, class_map) for shape in old['methodShapes'])
        total = sum(remapped.values())
        if total:
            hit = sum(min(count, self.new_shapes[target].get(shape, 0))
                      for shape, count in remapped.items())
            score = hit / total
        else:
            score = 1.0
        penalty = 1.0 - score
        if old['methodCount'] != new['methodCount']:
            penalty += 0.05
        if abs(old['fieldCount'] - new['fieldCount']) > 1:
            penalty += 0.05
        if old['super'] != new['super'] and old['super'] != 'Ljava/lang/Object;':
            if class_map.get(old['super']) != new['super']:
                penalty += 0.05
        old_ifaces = {class_map.get(i, i) for i in old['interfaces']}
        if not old_ifaces <= set(new['interfaces']) and len(
                old_ifaces ^ set(new['interfaces'])) > 1:
            penalty += 0.05
        return penalty

    def total(self, class_map):
        total = 0.0
        for source, target in class_map.items():
            if source not in self.old or target not in self.new:
                total += 10.0
                continue
            total += self.penalty(source, target, class_map)
        return total


def owner_of(path):
    text = path.read_text(errors='replace')
    match = re.search(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', text, re.M)
    return match.group(1) if match else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--old', default='.tools/cmp/decompiled')
    parser.add_argument('--new', default='.tools/upstream-173/decompiled')
    parser.add_argument('--class-map', required=True)
    parser.add_argument('--votes', default='.tools/type-votes2.json')
    parser.add_argument('--min-owners', type=int, default=3)
    parser.add_argument('--max-candidates', type=int, default=10)
    parser.add_argument('--focus', type=int, default=800)
    parser.add_argument('--rounds', type=int, default=8)
    parser.add_argument('--vote-weight', type=float, default=0.0005)
    parser.add_argument('--output', default=None)
    parser.add_argument('--report', default=None)
    args = parser.parse_args()

    data = json.loads(Path(args.class_map).read_text())
    class_map = dict(data['candidates'])
    raw = json.loads(Path(args.votes).read_text())['votes']
    votes = {name: {target: info['votes'] for target, info in table.items()
                    if info['ownerClasses'] >= args.min_owners}
             for name, table in raw.items()}
    universe = Universe(Path(args.old), Path(args.new))

    import resolve_class_map as resolver
    old_tree = resolver.load(Path(args.old))
    new_tree = resolver.load(Path(args.new))
    by_body = collections.defaultdict(set)
    for name, entry in new_tree.items():
        for body in entry['plain']:
            by_body[body].add(name)

    def body_candidates(source):
        counts = collections.Counter()
        for body, amount in old_tree[source]['plain'].items():
            for name in by_body.get(body, ()):
                counts[name] += min(amount, new_tree[name]['plain'][body])
        return [name for name, _ in counts.most_common(args.max_candidates)]

    def combined(source, target, class_map):
        penalty = universe.penalty(source, target, class_map)
        count = votes.get(source, {}).get(target, 0)
        return penalty - args.vote_weight * math.log(1 + count)

    scores = {source: combined(source, target, class_map)
              for source, target in class_map.items()
              if source in universe.old and target in universe.new}
    focus = set(sorted(scores, key=lambda s: -scores[s])[:args.focus])
    for source, table in votes.items():
        if source in class_map and source in universe.old and table:
            target = max(table, key=lambda t: table[t])
            if target != class_map[source]:
                focus.add(source)

    report = []
    for round_number in range(args.rounds):
        moved = 0
        holder = {target: source for source, target in class_map.items()}
        for source in sorted(focus):
            if source not in class_map:
                continue
            current = class_map[source]
            options = set(votes.get(source, {}))
            if source in old_tree:
                options.update(body_candidates(source))
            options.add(current)
            best = None
            for target in options:
                if target == current or target not in universe.new:
                    continue
                owner = holder.get(target)
                if owner is not None and owner != source:
                    continue
                score = combined(source, target, class_map)
                if best is None or score < best[0]:
                    best = (score, target)
            if best is None:
                continue
            score, target = best
            if score >= scores.get(source, 0.0) - 1e-9:
                continue
            owner = holder.get(target)
            if owner is not None and owner != source:
                other = combined(owner, current, class_map)
                if other >= scores.get(owner, 0.0) - 1e-9:
                    continue
                report.append({'old': owner, 'from': class_map[owner], 'to': current,
                               'score': round(scores.get(owner, 0.0), 4),
                               'newScore': round(other, 4), 'round': round_number})
                class_map[owner] = current
                holder[current] = owner
                scores[owner] = other
            report.append({'old': source, 'from': current, 'to': target,
                           'score': round(scores.get(source, 0.0), 4),
                           'newScore': round(score, 4), 'round': round_number})
            class_map[source] = target
            holder[target] = source
            scores[source] = score
            moved += 1
        print('round %d: %d moves' % (round_number, moved))
        if not moved:
            break

    # the groups of entangled classes are resolved as one problem each, and
    # the group is only kept when the map as a whole gets better
    for round_number in range(args.rounds):
        moved = 0
        for members in entangled_groups(class_map, focus, votes):
            before = universe.total(class_map)
            trial = dict(class_map)
            for source, target in resolve_group(members, trial, votes, body_candidates,
                                                combined, universe):
                trial[source] = target
            after = universe.total(trial)
            if after >= before:
                continue
            for source, target in trial.items():
                if class_map.get(source) != target:
                    report.append({'old': source, 'from': class_map.get(source),
                                   'to': target, 'group': members,
                                   'round': round_number})
            class_map.clear()
            class_map.update(trial)
            moved += 1
        print('group round %d: %d groups' % (round_number, moved))
        if not moved:
            break

    before = json.loads(Path(args.class_map).read_text())['candidates']
    print('penalty before: %.3f, after: %.3f'
          % (universe.total(before), universe.total(class_map)))
    for item in report:
        print('  %-9s %-9s -> %-9s score %s -> %s'
              % (item['old'], item['from'], item['to'],
                 item.get('score'), item.get('newScore')))
    if args.output:
        data['candidates'] = class_map
        Path(args.output).write_text(json.dumps(data, indent=1) + '\n')
        print('wrote %s' % args.output)
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=1) + '\n')


def entangled_groups(class_map, focus, votes):
    """The groups of classes that have to move together."""
    holder = {target: source for source, target in class_map.items()}
    groups, seen = [], set()
    for source in sorted(focus):
        if source in seen or source not in class_map:
            continue
        group, queue = {source}, [source]
        while queue:
            current = queue.pop()
            for target in votes.get(current, {}):
                owner = holder.get(target)
                if owner is not None and owner not in group:
                    group.add(owner)
                    queue.append(owner)
        seen |= group
        groups.append(sorted(group))
    return groups


def resolve_group(members, class_map, votes, body_candidates, combined, universe):
    """The best targets for the members of a group."""
    holder = {target: source for source, target in class_map.items()}
    inside = set(members)
    columns = set(class_map[source] for source in members)
    for source in members:
        columns.update(votes.get(source, {}))
        if source in class_map:
            columns.update(body_candidates(source))
    columns = sorted(columns)
    weight = {}
    for source in members:
        for target in columns:
            if target not in universe.new:
                continue
            owner = holder.get(target)
            if owner is not None and owner not in inside:
                continue
            weight[(source, target)] = SHIFT - combined(source, target, class_map)
    assignment = best_assignment(weight, members, columns)
    return [(source, target) for source, target in assignment.items()
            if target in universe.new and target != class_map[source]]


if __name__ == '__main__':
    main()
