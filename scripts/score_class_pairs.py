#!/usr/bin/env python3
"""Score candidate 171 -> 173 class pairs with several independent signals.

A rename hides every name, but it does not hide the relationships between
classes.  For a candidate pair the script measures:

* **proof** - how many method bodies of the source class occur in exactly one
  class of the target tree and nowhere else,
* **references** - which share of the types the source class refers to are
  still referred to by the target class after the mapping is applied,
* **shape** - which share of the method signatures of the source class is
  reproduced by the target class,
* **hierarchy** - whether the super class and interface list still fit.

The signals are independent, so a pair that is ahead in all of them is the
right one.
"""
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)
SUPER_RE = re.compile(r'^\.super\s+(\S+)', re.M)
IFACE_RE = re.compile(r'^\.implements\s+(.+)$', re.M)
TYPE_RE = re.compile(r'L[A-Za-z0-9_/$-]+;')


def fingerprint(block):
    text = re.sub(r'^\s*\.(?:line|source|local|end local|restart local|prologue|param)\b[^\n]*',
                  '', block, flags=re.M)
    text = re.sub(r'0x7f[0-9a-f]{6}', '@', text)
    text = re.sub(r'L[^/;\s\[():]+;', 'L?;', text)
    text = re.sub(r'(L\?;->)[^\s(:]+(?=[:(])', r'\1?', text)
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '"s"', text)
    text = re.sub(r'\b[vp]\d+\b', 'r', text)
    text = re.sub(r':\w+', ':L', text)
    return '\n'.join(line.strip() for line in text.splitlines()
                     if line.strip() and not line.strip().startswith('#'))


def describe(root):
    classes = {}
    for path in (root / 'smali').rglob('*.smali'):
        text = path.read_text(errors='replace')
        match = CLASS_RE.search(text)
        if not match:
            continue
        methods = collections.Counter()
        shapes = collections.Counter()
        refs = collections.Counter()
        for block in METHOD_RE.findall(text):
            canonical = fingerprint(block)
            if len(canonical) < 24:
                continue
            methods[hashlib.sha256(canonical.encode()).hexdigest()] += 1
            header = block.splitlines()[0]
            shapes[tuple(sorted(TYPE_RE.findall(header)))] += 1
            body = re.sub(r'"(?:[^"\\]|\\.)*"', '""', block)
            for owner in TYPE_RE.findall(body):
                refs[owner] += 1
        interfaces = []
        for impl in IFACE_RE.finditer(text):
            interfaces.extend(impl.group(1).split())
        classes[match.group(1)] = {
            'methods': methods,
            'shapes': shapes,
            'refs': refs,
            'super': (SUPER_RE.search(text) or [None, None])[1],
            'interfaces': sorted(interfaces),
        }
    return classes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--class-map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--threshold', type=float, default=0.9)
    parser.add_argument('--margin', type=float, default=0.1)
    args = parser.parse_args()

    old = describe(args.old)
    new = describe(args.new)
    mapping = json.loads(args.class_map.read_text())['candidates']

    old_index = collections.defaultdict(set)
    for name, profile in old.items():
        for digest in profile['methods']:
            old_index[digest].add(name)
    new_index = collections.defaultdict(set)
    for name, profile in new.items():
        for digest in profile['methods']:
            new_index[digest].add(name)
    proof = collections.defaultdict(collections.Counter)
    for digest, old_owners in old_index.items():
        new_owners = new_index.get(digest)
        if not new_owners or len(old_owners) != 1 or len(new_owners) != 1:
            continue
        proof[next(iter(old_owners))][next(iter(new_owners))] += 1

    def shape_score(old_owner, new_owner):
        old_shapes = collections.Counter(
            tuple(sorted(mapping.get(item, item) for item in shape))
            for shape in old[old_owner]['shapes'])
        new_shapes = new[new_owner]['shapes']
        total = sum(old_shapes.values())
        if not total:
            return 1.0
        hit = sum(min(count, new_shapes.get(shape, 0))
                  for shape, count in old_shapes.items())
        return hit / total

    def reference_score(old_owner, new_owner):
        old_refs = old[old_owner]['refs']
        new_refs = new[new_owner]['refs']
        total = sum(old_refs.values())
        if not total:
            return 1.0
        hit = 0
        for owner, count in old_refs.items():
            mapped = mapping.get(owner, owner)
            hit += min(count, new_refs.get(mapped, 0))
        return hit / total

    def hierarchy_ok(old_owner, new_owner):
        old_profile, new_profile = old[old_owner], new[new_owner]
        old_super = old_profile['super']
        if old_super and old_super != 'Ljava/lang/Object;':
            expected = mapping.get(old_super)
            if expected and new_profile['super'] != expected:
                return False
        for interface in old_profile['interfaces']:
            expected = mapping.get(interface)
            if expected and expected not in new_profile['interfaces']:
                return False
        return True

    used = collections.Counter(mapping.values())
    changes = []
    for old_owner in sorted(mapping):
        current = mapping[old_owner]
        if old_owner not in old or current not in new:
            continue
        current_score = (proof[old_owner].get(current, 0),
                         shape_score(old_owner, current),
                         reference_score(old_owner, current))
        if current_score[0] > 0 and current_score[1] >= args.threshold:
            continue
        candidates = []
        for candidate in proof[old_owner]:
            if candidate == current or used[candidate] > 1:
                continue
            if not hierarchy_ok(old_owner, candidate):
                continue
            candidates.append((proof[old_owner][candidate],
                               shape_score(old_owner, candidate),
                               reference_score(old_owner, candidate),
                               candidate))
        candidates.sort(reverse=True)
        if not candidates:
            continue
        best = candidates[0]
        if best[0] <= current_score[0]:
            continue
        if best[1] < current_score[1] + args.margin and best[0] <= current_score[0] + 1:
            continue
        changes.append({
            'old': old_owner, 'from': current, 'to': best[3],
            'proofBefore': current_score[0], 'proofAfter': best[0],
            'shapeBefore': round(current_score[1], 4), 'shapeAfter': round(best[1], 4),
            'refsBefore': round(current_score[2], 4), 'refsAfter': round(best[2], 4),
        })
        used[current] -= 1
        used[best[3]] += 1
        mapping[old_owner] = best[3]

    output = {
        'note': ('Reviewed 171 -> 173 class map. Method-body proofs, class shape and '
                 'class references decide the pairs.'),
        'oldClasses': len(old),
        'newClasses': len(new),
        'mapped': len(mapping),
        'candidates': dict(sorted(mapping.items())),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=1) + '\n')
    report = {'changes': len(changes), 'changeList': changes}
    if args.report:
        args.report.write_text(json.dumps(report, indent=1) + '\n')
    print('changes: %d' % len(changes))
    for entry in changes:
        print('  %s %s -> %s proof %d->%d shape %.2f->%.2f refs %.2f->%.2f'
              % (entry['old'], entry['from'], entry['to'], entry['proofBefore'],
                 entry['proofAfter'], entry['shapeBefore'], entry['shapeAfter'],
                 entry['refsBefore'], entry['refsAfter']))


if __name__ == '__main__':
    main()
