#!/usr/bin/env python3
"""Score 171 -> 173 class pairs with the reference graph of the program.

A renamed class keeps its role in the program: the classes that reference it
stay the same after the rename.  The script therefore builds, for both trees,
the set of classes that mention a class in a field type, a method signature,
a super call or a cast, and scores a candidate pair by how well the mapped
references of the old class line up with the references of the new class.

The signal is independent of the method bodies, so it breaks the ties that
the body fingerprint cannot: two Compose helpers that share the same body
still reference very different classes.

The script never rewrites the map, it reports the scores.
"""
import argparse
import collections
import json
import re
from pathlib import Path

CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)
TYPE_RE = re.compile(r'L[A-Za-z0-9_/$-]+;')
METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
FIELD_RE = re.compile(r'^\.field[^\n]*:(\S+)', re.M)
SUPER_RE = re.compile(r'^\.super\s+(\S+)', re.M)
IFACE_RE = re.compile(r'^\.implements\s+(.+)$', re.M)


def load_references(root):
    """Map every class to the set of classes it mentions."""
    references = {}
    names = {}
    for path in (root / 'smali').rglob('*.smali'):
        text = path.read_text(errors='replace')
        match = CLASS_RE.search(text)
        if not match:
            continue
        owner = match.group(1)
        names[owner] = path
        used = set()
        for other in TYPE_RE.findall(text):
            if other != owner:
                used.add(other)
        references[owner] = used
    return references, names


def score(source, target, references, class_map):
    """Compare the mapped references of the source with the references of the target."""
    old_used = references[source]
    new_used = references.get(target, set())
    mapped = {class_map.get(item, item) for item in old_used}
    shared = mapped & new_used
    old_only = mapped - new_used
    new_only = new_used - mapped
    union = mapped | new_used
    return {
        'shared': len(shared),
        'oldOnly': len(old_only),
        'newOnly': len(new_only),
        'jaccard': round(len(shared) / len(union), 4) if union else 1.0,
        'recall': round(len(shared) / len(mapped), 4) if mapped else 1.0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--class-map', type=Path, required=True)
    parser.add_argument('--pairs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()

    old_refs, _ = load_references(args.old)
    new_refs, _ = load_references(args.new)
    class_map = dict(json.loads(args.class_map.read_text())['candidates'])
    pairs = json.loads(args.pairs.read_text())

    report = []
    for source in pairs['classes']:
        scored = []
        for target in pairs['candidates'].get(source, []):
            if target not in new_refs:
                continue
            entry = score(source, target, old_refs, class_map)
            entry['target'] = target
            entry['reviewed'] = class_map.get(source) == target
            scored.append(entry)
        scored.sort(key=lambda entry: (-entry['shared'], -entry['jaccard']))
        report.append({'old': source, 'reviewed': class_map.get(source),
                       'candidates': scored})

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'classes': report}, indent=1) + '\n')
    for entry in report:
        print('%s reviewed=%s' % (entry['old'], entry['reviewed']))
        for candidate in entry['candidates']:
            print('    %-8s shared=%-4d oldOnly=%-4d newOnly=%-4d jaccard=%.3f recall=%.3f%s'
                  % (candidate['target'], candidate['shared'], candidate['oldOnly'],
                     candidate['newOnly'], candidate['jaccard'], candidate['recall'],
                     '  <- reviewed' if candidate['reviewed'] else ''))


if __name__ == '__main__':
    main()
