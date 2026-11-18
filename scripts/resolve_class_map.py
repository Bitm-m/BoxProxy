#!/usr/bin/env python3
"""Repair the broken entries of the reviewed 171 -> 173 class map.

The reviewed map is a hypothesis about the rename of the upstream APK.  It is
correct for the large majority of the classes and this script does not touch
those.  It only repairs the entries that the evidence shows to be broken:

* a class that keeps its implementation keeps the bodies of its methods, so a
  pair that shares almost none of them does not correspond,
* a class that is much bigger than its target is broken as well: the upstream
  release merged or split the class.

A broken entry cannot be repaired on its own, because the target it wants
belongs to another class, which then has to move as well.  The script collects
the classes that are entangled with a broken entry and solves them together,
as an assignment problem: every class of the group takes a distinct target
and the assignment that keeps the most evidence wins.

A class only displaces another class when it wants the target of that class
more than the class itself does, so the groups stay small.  A group is only
accepted when no class of it ends up with less evidence than before and when
the migration coverage stays complete.  The result is written with the
decisions and the evidence that produced them.
"""
import argparse
import collections
import difflib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import class_shape

METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)
HEADER_RE = re.compile(r'^\.method\s+.*?([^ ]+\([^\n]*)$')
TYPE = re.compile(r'L[A-Za-z0-9_/$-]+;')
ID_RE = re.compile(r'0x7f[0-9a-f]{6}')
FORBIDDEN = 1e12


def bodies(block):
    out = []
    for line in block.splitlines()[1:-1]:
        stripped = line.strip()
        if not stripped or stripped.startswith((
                '.line ', '.source ', '.local ', '.end local ', '.restart local ',
                '.param ', '.end param ', '.prologue', '#')):
            continue
        out.append(stripped)
    return out


def normalize(lines):
    result = []
    for line in lines:
        line = ID_RE.sub('@', line)
        line = re.sub(r'(L[A-Za-z0-9_/$-]+;)->([^\s(:]+)', r'\1->?', line)
        line = TYPE.sub('T', line)
        line = re.sub(r'\b[vp]\d+\b', 'r', line)
        line = re.sub(r':\w+', ':L', line)
        result.append(line)
    return '\n'.join(result)


def self_ref(lines, owner):
    text = '\n'.join(lines).replace(owner, 'SELF')
    text = re.sub(r'L[^/;\s\[():]+;', 'L?;', text)
    text = re.sub(r'(L\?;->)[^\s(:]+(?=[:(])', r'\1?', text)
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '"s"', text)
    text = re.sub(r'0x7f[0-9a-f]{6}', '@', text)
    text = re.sub(r'\b[vp]\d+\b', 'r', text)
    text = re.sub(r':\w+', ':L', text)
    return '\n'.join(line.strip() for line in text.splitlines()
                     if line.strip() and not line.strip().startswith('#'))


def load(root):
    classes = {}
    for path in (root / 'smali').rglob('*.smali'):
        text = path.read_text(errors='replace')
        match = CLASS_RE.search(text)
        if not match:
            continue
        owner = match.group(1)
        plain = collections.Counter()
        keeps = collections.Counter()
        methods = 0
        for block in METHOD_RE.findall(text):
            lines = bodies(block)
            plain[normalize(lines)] += 1
            keeps[self_ref(lines, owner)] += 1
            methods += 1
        info = class_shape.parse(text)
        classes[owner] = {'plain': plain, 'self': keeps, 'methods': methods,
                          'raw': {'methods': info[1], 'fields': info[2]}}
    return classes


def hungarian(cost):
    """The Hungarian algorithm on a matrix of costs (lower is better).

    The matrix has to have at least as many columns as rows.  The assignment
    is returned as a list of column indices, one per row.
    """
    rows = len(cost)
    columns = len(cost[0])
    potentials_row = [0.0] * (rows + 1)
    potentials_column = [0.0] * (columns + 1)
    match = [0] * (columns + 1)
    way = [0] * (columns + 1)
    for row in range(1, rows + 1):
        match[0] = row
        column0 = 0
        minimum = [float('inf')] * (columns + 1)
        used = [False] * (columns + 1)
        while True:
            used[column0] = True
            row0 = match[column0]
            delta = float('inf')
            column1 = 0
            for column in range(1, columns + 1):
                if used[column]:
                    continue
                current = (cost[row0 - 1][column - 1]
                           - potentials_row[row0] - potentials_column[column])
                if current < minimum[column]:
                    minimum[column] = current
                    way[column] = column0
                if minimum[column] < delta:
                    delta = minimum[column]
                    column1 = column
            for column in range(columns + 1):
                if used[column]:
                    potentials_row[match[column]] += delta
                    potentials_column[column] -= delta
                else:
                    minimum[column] -= delta
            column0 = column1
            if match[column0] == 0:
                break
        while True:
            column1 = way[column0]
            match[column0] = match[column1]
            match[column1] = row
            column0 = column1
            if column0 == 0:
                break
    assignment = [-1] * rows
    for column in range(1, columns + 1):
        if match[column] > 0:
            assignment[match[column] - 1] = column - 1
    return assignment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--class-map', type=Path, required=True)
    parser.add_argument('--coverage', type=Path, required=True)
    parser.add_argument('--builder', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--min-methods', type=int, default=8,
                        help='a class with fewer methods is too small to judge')
    parser.add_argument('--max-ratio', type=float, default=0.1,
                        help='a pair that shares less of its bodies is broken')
    args = parser.parse_args()

    old = load(args.old)
    new = load(args.new)
    document = json.loads(args.class_map.read_text())
    reviewed = dict(document['candidates'])
    coverage = json.loads(args.coverage.read_text())
    customized = collections.defaultdict(list)
    for item in coverage['completed']:
        owner, signature = item['new'].split('->', 1)
        customized[owner].append(signature)

    new_by_plain = collections.defaultdict(set)
    for name, profile in new.items():
        for body in profile['plain']:
            new_by_plain[body].add(name)

    def shared(source, target):
        source_profile = old[source]
        target_profile = new[target]
        return sum(min(count, target_profile['plain'].get(body, 0))
                   for body, count in source_profile['plain'].items())

    # How many new classes hold a body.  A body that many classes share does
    # not tell them apart: the constructor of a small class is the same in
    # hundreds of them.  The evidence of a body is therefore the inverse of
    # the number of classes that share it.
    holders = collections.Counter()
    for body, names in new_by_plain.items():
        holders[body] = len(names)

    def distinctive(source, target):
        """The bodies that the two classes share, weighed by how rare they are.

        A body that only the target holds is worth one point.  A body that
        hundreds of classes hold is worth almost nothing, because it does not
        tell the target apart from the others.
        """
        source_profile = old[source]
        target_profile = new[target]
        total = 0.0
        for body, count in source_profile['plain'].items():
            shared_count = min(count, target_profile['plain'].get(body, 0))
            if shared_count:
                total += shared_count / holders[body]
        return total

    def keeps(source, target):
        source_profile = old[source]
        target_profile = new[target]
        return sum(min(count, target_profile['self'].get(body, 0))
                   for body, count in source_profile['self'].items())

    def structure(source, target):
        """How alike the shape of the two classes is, between 0 and 1."""
        old_shape = class_shape.shape(old[source]['raw'], reviewed)
        new_shape = class_shape.shape(new[target]['raw'])
        return class_shape.compare(old_shape, new_shape)

    def score(source, target):
        """The evidence that the old class corresponds to the new class.

        The bodies of the methods are the strongest evidence: a method that is
        copied keeps its body.  The shape of the class comes next: the types
        of the constructor and of the fields say what kind of class it is,
        and they are what tells two classes apart when their bodies are all
        generic.
        """
        return (shared(source, target) * 1000 + keeps(source, target) * 250
                + structure(source, target) * 100)

    def candidates_of(source, limit=10):
        """The new classes that share bodies with the old class."""
        counts = collections.Counter()
        for body, count in old[source]['plain'].items():
            for name in new_by_plain.get(body, ()):
                counts[name] += count
        return counts.most_common(limit)

    reverse = collections.defaultdict(list)
    for source, target in reviewed.items():
        reverse[target].append(source)
    owner_of = {target: source for source, target in reviewed.items()}

    # The targets that no class claims: a class that is displaced needs a home
    # of its own.
    claimed = set(reviewed.values())

    # The broken entries: the class shares almost nothing with its target.
    broken = set()
    for source, current in reviewed.items():
        if source not in old or current not in new:
            continue
        if old[source]['methods'] < args.min_methods:
            continue
        if shared(source, current) / old[source]['methods'] <= args.max_ratio:
            broken.add(source)

    # The groups of entangled classes.  A broken class cannot be repaired on
    # its own: the target it wants belongs to another class, which then has
    # to move as well.  The group of a broken class is therefore closed over
    # that displacement: the class that holds the wanted target joins the
    # group, and so on.
    #
    # A class only joins a group when it is the target of a class that wants
    # it more than the class itself does.  Otherwise the group would grow
    # without a reason and swallow classes that are not related.
    groups = collections.defaultdict(set)
    for source in broken:
        groups[source].add(source)
    changed = True
    while changed:
        changed = False
        for group in list(groups):
            members = groups[group]
            for member in list(members):
                for target, hits in candidates_of(member):
                    if hits < 2:
                        continue
                    for other in reverse.get(target, []):
                        if other in members:
                            continue
                        if score(member, target) <= score(other, reviewed[other]):
                            continue
                        members.add(other)
                        changed = True
            groups[group] = members

    method_cache = {}

    def methods_of_class(root, owner):
        key = (str(root), owner)
        if key not in method_cache:
            path = root / 'smali' / (owner[1:-1] + '.smali')
            if not path.is_file():
                method_cache[key] = {}
            else:
                text = path.read_text(errors='replace')
                result = {}
                for block in METHOD_RE.findall(text):
                    header = HEADER_RE.match(block.splitlines()[0])
                    if header:
                        result[header.group(1)] = normalize(bodies(block))
                method_cache[key] = result
        return method_cache[key]

    def keeps_coverage(source, target):
        """True when every customized method of the source is found again."""
        if source not in customized:
            return True
        source_methods = methods_of_class(args.old, source)
        target_methods = methods_of_class(args.new, target)
        if not target_methods:
            return False
        for signature in customized[source]:
            body = source_methods.get(signature)
            if body is None:
                continue
            if any(other == body for other in target_methods.values()):
                continue
            best = 0.0
            second = 0.0
            for other_body in target_methods.values():
                ratio = difflib.SequenceMatcher(None, body, other_body,
                                                 autojunk=False).ratio()
                if ratio > best:
                    second = best
                    best = ratio
                elif ratio > second:
                    second = ratio
            if best < 0.5 or best - second < 0.03:
                return False
        return True

    def coverage_for(mapping):
        with tempfile.TemporaryDirectory(prefix='.boxproxy-resolve-') as temp:
            map_path = Path(temp) / 'class-map.json'
            out_path = Path(temp) / 'coverage.json'
            map_path.write_text(json.dumps({'candidates': mapping}))
            result = subprocess.run(
                [sys.executable, str(args.builder),
                 '--base', str(args.old), '--new', str(args.new),
                 '--coverage', str(args.coverage),
                 '--class-map', str(map_path), '--output', str(out_path)],
                capture_output=True, text=True)
            if result.returncode != 0:
                return None
            data = json.loads(out_path.read_text())
            return len(data['completed']), data['pending']

    decisions = []
    mapping = dict(reviewed)
    # The groups that share a class are merged: a class can only be in one
    # group, because it can only move once.
    group_of = {}
    for key, members in groups.items():
        for member in members:
            group_of.setdefault(member, key)
    parent = {key: key for key in groups}

    def find(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for member, key in group_of.items():
        left, right = find(key), find(group_of[member])
        if left != right:
            parent[right] = left
    final_groups = collections.defaultdict(set)
    for key, members in groups.items():
        final_groups[find(key)].update(members)

    for group in sorted(final_groups, key=lambda key: sorted(final_groups[key])):
        members = sorted(final_groups[group])
        # The candidates of a class: the reviewed target, the classes that
        # share bodies with it, and the classes that no class claims.  The
        # last ones matter when a class is displaced: it needs a home of its
        # own.
        options = {}
        for source in members:
            current = reviewed[source]
            found = {current}
            for target, hits in candidates_of(source):
                found.add(target)
            # The targets that no class claims are always available: a class
            # that is displaced needs a home of its own.
            for target, hits in candidates_of(source, limit=64):
                if target not in claimed:
                    found.add(target)
            options[source] = sorted(found)
        columns = sorted({target for source in members for target in options[source]})
        if len(columns) < len(members):
            continue
        # A target that belongs to a class outside the group may not be taken.
        outside = {reviewed[source] for source in reviewed if source not in members}
        cost = []
        for source in members:
            row = []
            for target in columns:
                if target not in options[source] or target in outside:
                    row.append(FORBIDDEN)
                    continue
                if not keeps_coverage(source, target):
                    row.append(FORBIDDEN)
                    continue
                # a class that would end up with less evidence than before may
                # not move
                if score(source, target) < score(source, reviewed[source]):
                    row.append(FORBIDDEN)
                    continue
                # a tie is broken in favour of the reviewed target, and then
                # in favour of the candidate that has the shape of the class
                row.append(-score(source, target) * 1000
                           - (1 if target == reviewed[source] else 0))
            cost.append(row)
        assignment = hungarian(cost)
        if assignment is None:
            continue
        chosen = {}
        usable = True
        for row, source in enumerate(members):
            column = assignment[row]
            if column < 0 or cost[row][column] >= FORBIDDEN:
                usable = False
                break
            chosen[source] = columns[column]
        if not usable:
            continue
        if all(reviewed[source] == target for source, target in chosen.items()):
            continue
        for source in members:
            target = chosen[source]
            decisions.append({
                'old': source,
                'reviewed': reviewed[source],
                'selected': target,
                'sharedBodies': shared(source, target),
                'reviewedSharedBodies': shared(source, reviewed[source]),
                'selfBodies': keeps(source, target),
                'reviewedSelfBodies': keeps(source, reviewed[source]),
                'methods': old[source]['methods'],
                'newMethods': new[target]['methods'],
                'changed': reviewed[source] != target,
            })
        mapping.update(chosen)

    result = coverage_for(mapping)
    if result is None or result[1]:
        raise SystemExit('the repaired map does not keep the coverage complete: %s'
                         % (result[1][:3] if result else 'error'))

    document['candidates'] = dict(sorted(mapping.items()))
    document['mapped'] = len(mapping)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1) + '\n')
    if args.report:
        args.report.write_text(json.dumps(
            {'coverage': result[0],
             'changed': sum(1 for entry in decisions if entry['changed']),
             'decisions': decisions}, indent=1) + '\n')
    print('coverage %d completed, %d changed'
          % (result[0], sum(1 for entry in decisions if entry['changed'])))
    for entry in decisions:
        if not entry['changed']:
            continue
        print('  %-8s %-8s -> %-8s bodies %d/%d self %d/%d methods %d/%d'
              % (entry['old'], entry['reviewed'], entry['selected'],
                 entry['sharedBodies'], entry['reviewedSharedBodies'],
                 entry['selfBodies'], entry['reviewedSelfBodies'],
                 entry['methods'], entry['newMethods']))


if __name__ == '__main__':
    main()
