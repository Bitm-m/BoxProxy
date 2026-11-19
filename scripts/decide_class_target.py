#!/usr/bin/env python3
"""Decide the target of a class by the evidence that separates the candidates.

The body of a method is the strongest evidence, but a body that many classes
share does not tell the classes apart.  The constructor is the next best
evidence: a class that keeps its implementation keeps the signature of its
constructor, and a signature that has a rare shape is worth a lot.

The script prints, for every candidate of a class, the evidence that points
at it and the evidence that points away from it, so that the decision can be
made by reading and not by trusting a number.
"""
import argparse, json, sys, collections
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import class_shape, resolve_class_map as resolver


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--old', default='.tools/cmp/decompiled')
    parser.add_argument('--new', default='.tools/upstream-173/decompiled')
    parser.add_argument('--class-map',
                        default='upstream/26.11.17.73f2816/migration/class-map.json')
    parser.add_argument('--pairs', required=True,
                        help='JSON list of [source, [candidate, ...]]')
    args = parser.parse_args()

    old = resolver.load(Path(args.old))
    new = resolver.load(Path(args.new))
    rev = json.load(open(args.class_map))['candidates']

    newbyp = collections.defaultdict(set)
    for n, p in new.items():
        for b in p['plain']:
            newbyp[b].add(n)
    holders = collections.Counter()
    for b, names in newbyp.items():
        holders[b] = len(names)

    def shared(s, t):
        return sum(min(c, new[t]['plain'].get(b, 0)) for b, c in old[s]['plain'].items())

    def keeps(s, t):
        return sum(min(c, new[t]['self'].get(b, 0)) for b, c in old[s]['self'].items())

    def distinctive(s, t):
        total = 0.0
        for b, c in old[s]['plain'].items():
            m = min(c, new[t]['plain'].get(b, 0))
            if m:
                total += m / holders[b]
        return total

    pairs = json.loads(args.pairs)
    for source, targets in pairs:
        old_shape = class_shape.shape(old[source]['raw'], rev)
        print('=== %s  (reviewed %s) ===' % (source, rev.get(source)))
        print('  old ctors: %s' % (old_shape['constructors'],))
        print('  old fields: %s' % (old_shape['fieldTypes'],))
        print('  old methods: %d' % len(old_shape['methodNames']))
        rows = []
        for t in targets:
            if t not in new:
                print('  %-8s ABSENT from the new tree' % t)
                continue
            new_shape = class_shape.shape(new[t]['raw'])
            shape = class_shape.compare(old_shape, new_shape)
            # the exact constructor match is what tells two classes apart
            exact = [c for c in new_shape['constructors']
                     if c in old_shape['constructors']]
            rows.append((shape, t, shared(source, t), keeps(source, t),
                         distinctive(source, t), exact, new_shape))
        rows.sort(reverse=True)
        for shape, t, sh, kp, di, exact, new_shape in rows:
            print('  %-8s shape=%.3f body=%-3d self=%-3d distinct=%5.2f exactCtor=%d'
                  % (t, shape, sh, kp, di, len(exact)))
            print('        ctors: %s' % (new_shape['constructors'],))
            print('        fields: %s' % (new_shape['fieldTypes'],))
        print()


if __name__ == '__main__':
    main()
