#!/usr/bin/env python3
"""List the entries of a class map that the evidence shows to be broken.

An entry is broken when the old class and its target have almost nothing in
common: the bodies of the methods do not match and the shape of the classes
does not match either.  For every broken entry the script lists the classes
that could take its place, with the evidence for each.
"""
import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import class_shape
import resolve_class_map as resolver


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--class-map', type=Path, required=True)
    parser.add_argument('--min-methods', type=int, default=1)
    parser.add_argument('--max-ratio', type=float, default=0.2)
    parser.add_argument('--limit', type=int, default=8)
    args = parser.parse_args()

    old = resolver.load(args.old)
    new = resolver.load(args.new)
    reviewed = json.loads(args.class_map.read_text())['candidates']

    new_by_plain = collections.defaultdict(set)
    for name, profile in new.items():
        for body in profile['plain']:
            new_by_plain[body].add(name)

    def shared(source, target):
        return sum(min(count, new[target]['plain'].get(body, 0))
                   for body, count in old[source]['plain'].items())

    def keeps(source, target):
        return sum(min(count, new[target]['self'].get(body, 0))
                   for body, count in old[source]['self'].items())

    def structure(source, target):
        return class_shape.compare(class_shape.shape(old[source]['raw'], reviewed),
                                   class_shape.shape(new[target]['raw']))

    owner_of = {target: source for source, target in reviewed.items()}

    for source, target in sorted(reviewed.items()):
        if source not in old or target not in new:
            continue
        if old[source]['methods'] < args.min_methods:
            continue
        ratio = shared(source, target) / old[source]['methods']
        if ratio > args.max_ratio:
            continue
        counts = collections.Counter()
        for body, count in old[source]['plain'].items():
            for name in new_by_plain.get(body, ()):
                counts[name] += count
        print('%s -> %s   bodies %d/%d  methods %d/%d  shape %.2f'
              % (source, target, shared(source, target),
                 old[source]['methods'], old[source]['methods'],
                 new[target]['methods'], structure(source, target)))
        for candidate, hits in counts.most_common(args.limit):
            if candidate == target:
                continue
            print('     %-8s bodies %-3d self %-3d shape %.2f  methods %-3d'
                  '  claimed_by=%s'
                  % (candidate, shared(source, candidate),
                     keeps(source, candidate), structure(source, candidate),
                     new[candidate]['methods'],
                     owner_of.get(candidate, '-')))
        print()


if __name__ == '__main__':
    main()
