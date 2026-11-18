#!/usr/bin/env python3
"""The methods of the customised tree that differ from the upstream tree.

The coverage list holds the methods that the migration changed.  The tree
that the migration produced holds more: the fixes that were applied after
the migration, such as the fields that were merged into a class, change
methods that the list does not name.  A port has to carry those as well, so
this script lists every method that differs.
"""
import argparse, json, re, sys, collections
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_173_maps import methods, fingerprint

CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)


def owner_of(path):
    text = path.read_text(errors='replace')
    match = CLASS_RE.search(text)
    return match.group(1) if match else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--upstream', required=True)
    parser.add_argument('--custom', required=True)
    parser.add_argument('--coverage', default=None)
    parser.add_argument('--output', default=None)
    args = parser.parse_args()

    upstream = Path(args.upstream)
    custom = Path(args.custom)
    covered = set()
    if args.coverage:
        data = json.loads(Path(args.coverage).read_text())
        for item in data.get('completed', []):
            covered.add(item['old'])

    changed = []
    for path in sorted(custom.rglob('*.smali')):
        relative = path.relative_to(custom)
        original = upstream / relative
        if not original.is_file():
            continue
        owner = owner_of(path)
        old_methods = methods(original)
        new_methods = methods(path)
        for signature, block in new_methods.items():
            other = old_methods.get(signature)
            key = (owner or '?') + '->' + signature
            if other is None:
                changed.append({'old': key, 'kind': 'added method',
                                'file': relative.as_posix(),
                                'covered': key in covered})
                continue
            if fingerprint(block) != fingerprint(other):
                changed.append({'old': key, 'kind': 'changed method',
                                'file': relative.as_posix(),
                                'covered': key in covered})
    for item in changed:
        print('%-6s %s' % ('listed' if item.get('covered') else 'EXTRA', item['old']))
    print()
    extra = [item for item in changed if not item.get('covered')]
    print('changed methods: %d, of which the coverage does not list: %d'
          % (len(changed), len(extra)))
    if args.output:
        Path(args.output).write_text(json.dumps(changed, indent=1) + '\n')


if __name__ == '__main__':
    main()
