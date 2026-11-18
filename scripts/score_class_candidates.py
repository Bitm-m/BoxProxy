#!/usr/bin/env python3
"""Score candidate 171 -> 173 class pairs with graded, rename proof evidence.

The self-reference fingerprint of `match_classes_selfref.py` is only used
there when a body occurs in exactly one class of each tree.  That is the
strongest possible statement, but it is rare: most classes have no such
method.  This script computes the same fingerprint as a *graded* signal: how
many methods of the old class keep their body in the candidate class.  The
count is the number of shared method bodies, so a class that only collides
with generic Compose helpers scores low while a class that carries the real
implementation scores high.

Three signals are combined:

* `selfMatches`: methods whose body keeps the reference to their own class,
* `plainMatches`: methods whose body matches after the types are masked,
* `strings`: string constants that occur in both classes.

The script never rewrites the map, it reports the scores.
"""
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)
TYPE_RE = re.compile(r'L[A-Za-z0-9_/$-]+;')
STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


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


def masked(lines, owner=None):
    result = []
    for line in lines:
        line = re.sub(r'(L[A-Za-z0-9_/$-]+;)->([^\s(:]+)', r'\1->?', line)
        line = TYPE_RE.sub('T', line)
        line = re.sub(r'\b[vp]\d+\b', 'r', line)
        line = re.sub(r':\w+', ':L', line)
        result.append(line.strip())
    return '\n'.join(result)


def self_ref(lines, owner):
    text = '\n'.join(lines)
    text = text.replace(owner, 'SELF')
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
        strings = set()
        for block in METHOD_RE.findall(text):
            lines = bodies(block)
            plain[masked(lines)] += 1
            keeps[self_ref(lines, owner)] += 1
            strings.update(match.group(1) for match in STRING_RE.finditer(block))
        classes[owner] = {'plain': plain, 'self': keeps, 'strings': strings,
                          'methods': sum(plain.values())}
    return classes


def score(old_class, new_class, old, new):
    source, target = old[old_class], new[new_class]
    plain_hit = sum(min(count, target['plain'].get(body, 0))
                    for body, count in source['plain'].items())
    self_hit = sum(min(count, target['self'].get(body, 0))
                   for body, count in source['self'].items())
    shared_strings = len(source['strings'] & target['strings'])
    return {
        'plainMatches': plain_hit,
        'selfMatches': self_hit,
        'strings': shared_strings,
        'oldMethods': source['methods'],
        'newMethods': target['methods'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--class-map', type=Path, required=True)
    parser.add_argument('--pairs', type=Path, required=True,
                        help='json file with the contested classes and their candidates')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()

    old = load(args.old)
    new = load(args.new)
    reviewed = dict(json.loads(args.class_map.read_text())['candidates'])
    pairs = json.loads(args.pairs.read_text())

    report = []
    for source in pairs['classes']:
        options = pairs['candidates'].get(source, [])
        scored = []
        for target in options:
            if target not in new:
                continue
            entry = score(source, target, old, new)
            entry['target'] = target
            entry['reviewed'] = reviewed.get(source) == target
            scored.append(entry)
        scored.sort(key=lambda entry: (-entry['selfMatches'], -entry['plainMatches']))
        report.append({'old': source, 'reviewed': reviewed.get(source),
                       'candidates': scored})

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'classes': report}, indent=1) + '\n')
    for entry in report:
        print('%s reviewed=%s' % (entry['old'], entry['reviewed']))
        for candidate in entry['candidates']:
            print('    %-8s self=%-4d plain=%-4d strings=%-3d methods=%d/%d%s'
                  % (candidate['target'], candidate['selfMatches'],
                     candidate['plainMatches'], candidate['strings'],
                     candidate['oldMethods'], candidate['newMethods'],
                     '  <- reviewed' if candidate['reviewed'] else ''))


if __name__ == '__main__':
    main()
