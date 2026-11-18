#!/usr/bin/env python3
"""Compare two candidate targets for a 171 class with signature evidence.

For every method of the 171 class the script looks for a method in the
candidate whose *signature* matches after the type names are mapped: same
parameter types in the same order, same return type.  That is a much tighter
relation than the multiset of types, and it separates two classes that both
look plausible.

The result is reported per candidate so the decision between them can be
made on evidence instead of on the order in which the classes were matched.
"""
import argparse
import collections
import json
import re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method[^\n]*?([^\s(]+\([^\n]*)$', re.M)
TYPE_RE = re.compile(r'L[A-Za-z0-9_/$-]+;')


def methods_of(path):
    result = collections.Counter()
    if not path.is_file():
        return result
    text = path.read_text(errors='replace')
    for signature in METHOD_RE.findall(text):
        result[signature.strip()] += 1
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--pairs', type=Path, required=True)
    parser.add_argument('--class-map', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()

    mapping = json.loads(args.class_map.read_text())['candidates']

    def remap(signature):
        return TYPE_RE.sub(lambda match: mapping.get(match.group(0), match.group(0)),
                           signature)

    def class_path(root, descriptor):
        return root / 'smali' / (descriptor[1:-1] + '.smali')

    pairs = json.loads(args.pairs.read_text())
    report = []
    for entry in pairs:
        source = entry[0]
        old_methods = methods_of(class_path(args.old, source))
        row = {'old': source, 'candidates': {}}
        for candidate in entry[1:]:
            new_methods = methods_of(class_path(args.new, candidate))
            mapped = collections.Counter(remap(signature) for signature in old_methods)
            hit = 0
            for signature, count in mapped.items():
                hit += min(count, new_methods.get(signature, 0))
            row['candidates'][candidate] = {
                'matchedSignatures': hit,
                'oldMethods': sum(old_methods.values()),
                'newMethods': sum(new_methods.values()),
                'ratio': round(hit / sum(old_methods.values()), 4) if old_methods else 0.0,
            }
        report.append(row)
    if args.output:
        args.output.write_text(json.dumps(report, indent=1) + '\n')
    for row in report:
        parts = []
        for candidate, score in row['candidates'].items():
            parts.append('%s=%d/%d(%.2f)' % (candidate, score['matchedSignatures'],
                                             score['oldMethods'], score['ratio']))
        print('%-10s %s' % (row['old'], '  '.join(parts)))


if __name__ == '__main__':
    main()
