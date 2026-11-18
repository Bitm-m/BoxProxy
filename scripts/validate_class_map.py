#!/usr/bin/env python3
"""Validate the reviewed 171 -> 173 class map.

A fresh R8 run renames every class, so the map is a hypothesis that has to be
checked.  The strongest signal that survives the rename is the *type shape* of
a class: the multiset of method signatures (parameter and return types) and
the field types.  When the class map is correct, mapping the old types through
the map reproduces the new class almost exactly; when it is wrong, the shapes
disagree.

The script also reports the raw method/field counts, the super class and the
interface list, plus the string constants, for the entries that fail.
"""
import argparse
import collections
import json
import re
from pathlib import Path

CLASS_RE = re.compile(r'^\.class\s+(?:.*?\s)?(L[A-Za-z0-9_/$-]+;)', re.M)
SUPER_RE = re.compile(r'^\.super\s+(\S+)', re.M)
IFACE_RE = re.compile(r'^\.implements\s+(.+)$', re.M)
METHOD_RE = re.compile(r'^\.method\s+.*?([^\s(]+\([^)]*\)\S+)\s*$', re.M)
FIELD_RE = re.compile(r'^\.field\s+.*?\s([A-Za-z_$][\w$]*):(\S+)', re.M)
STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
TYPE_RE = re.compile(r'L[A-Za-z0-9_/$-]+;')
PRIMITIVES = {'I', 'J', 'Z', 'B', 'C', 'S', 'D', 'F', 'V'}


def types_of(text):
    return [t for t in TYPE_RE.findall(text) if t not in ('Ljava/lang/String;',)]


def profile(path):
    text = path.read_text(errors='replace')
    interfaces = []
    for match in IFACE_RE.finditer(text):
        interfaces.extend(match.group(1).split())
    methods = []
    for signature in METHOD_RE.findall(text):
        params, _, ret = signature.partition(')L')
        params = params.split('(', 1)[1] if '(' in params else ''
        ret = 'L' + ret if ret else 'V'
        shape = tuple(types_of(params)) + ('->',) + tuple(types_of(ret))
        methods.append(shape)
    fields = []
    for _, field_type in FIELD_RE.findall(text):
        fields.append(tuple(types_of(field_type)))
    strings = {s for s in STRING_RE.findall(text) if len(s) > 3}
    return {
        'class': CLASS_RE.search(text).group(1),
        'super': (SUPER_RE.search(text) or [None, None])[1],
        'interfaces': sorted(interfaces),
        'methodCount': len(methods),
        'fieldCount': len(fields),
        'methodShapes': collections.Counter(methods),
        'fieldShapes': collections.Counter(fields),
        'strings': strings,
    }


def normalize_shape(shape, class_map):
    remapped = [class_map.get(item, item) for item in shape]
    if '->' in remapped:
        split = remapped.index('->')
        params = tuple(sorted(remapped[:split]))
        ret = tuple(sorted(remapped[split + 1:]))
    else:
        params = tuple(sorted(remapped))
        ret = ()
    return params + ('->',) + ret


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--class-map', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--threshold', type=float, default=0.9)
    args = parser.parse_args()

    class_map = json.loads(args.class_map.read_text())['candidates']
    issues = []
    checked = 0
    for source, target in class_map.items():
        old_path = args.old / 'smali' / (source[1:-1] + '.smali')
        new_path = args.new / 'smali' / (target[1:-1] + '.smali')
        if not old_path.is_file() or not new_path.is_file():
            issues.append({'old': source, 'new': target, 'reason': 'missing file', 'score': 0.0})
            continue
        checked += 1
        old = profile(old_path)
        new = profile(new_path)
        new['methodShapes'] = collections.Counter(
            normalize_shape(shape, {}) for shape in new['methodShapes'])
        new['fieldShapes'] = collections.Counter(
            normalize_shape(shape, {}) for shape in new['fieldShapes'])
        remapped = collections.Counter(
            normalize_shape(shape, class_map) for shape in old['methodShapes'])
        total = sum(remapped.values())
        hit = sum(min(count, new['methodShapes'].get(shape, 0))
                  for shape, count in remapped.items())
        score = hit / total if total else 1.0
        reasons = []
        if score < args.threshold:
            reasons.append('method shape match %.2f' % score)
        if old['methodCount'] != new['methodCount']:
            reasons.append('method count %d != %d' % (old['methodCount'], new['methodCount']))
        if abs(old['fieldCount'] - new['fieldCount']) > 1:
            reasons.append('field count %d != %d' % (old['fieldCount'], new['fieldCount']))
        if old['super'] != new['super'] and old['super'] != 'Ljava/lang/Object;':
            if class_map.get(old['super']) != new['super']:
                reasons.append('super %s -> %s' % (old['super'], new['super']))
        old_ifaces = {class_map.get(i, i) for i in old['interfaces']}
        if not old_ifaces <= set(new['interfaces']) and len(old_ifaces ^ set(new['interfaces'])) > 1:
            reasons.append('interfaces %s vs %s' % (sorted(old_ifaces), sorted(new['interfaces'])))
        if reasons:
            issues.append({'old': source, 'new': target, 'reason': '; '.join(reasons),
                           'score': round(score, 4)})
    report = {
        'checked': checked,
        'mapped': len(class_map),
        'issues': len(issues),
        'issueList': issues,
    }
    if args.report:
        args.report.write_text(json.dumps(report, indent=1) + '\n')
    print('checked %d classes, %d issues (threshold %.2f)'
          % (checked, len(issues), args.threshold))
    kinds = collections.Counter(issue['reason'].split(' ')[0] for issue in issues)
    print(json.dumps(kinds, indent=1))


if __name__ == '__main__':
    main()
