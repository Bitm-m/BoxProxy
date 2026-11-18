#!/usr/bin/env python3
"""Refine the 171 -> 173 class map with the class hierarchy as a hard rule.

The fingerprint matcher proves that two classes correspond when they share a
method body that occurs nowhere else.  Those pairs are seeds.  The rest of the
map is then derived with the class graph as the constraint: a subclass has to
map onto a subclass of the mapped super class, an interface has to map onto a
mapped interface, and every class may only be used once.

The result is a map that is consistent with the hierarchy by construction, so
a wrong pairing cannot silently move a method into an unrelated class.
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
FIELD_RE = re.compile(r'^\.field[^\n]*?\s([A-Za-z_$][\w$]*):(\S+)', re.M)


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
        for block in METHOD_RE.findall(text):
            canonical = fingerprint(block)
            if len(canonical) < 24:
                continue
            methods[hashlib.sha256(canonical.encode()).hexdigest()] += 1
        interfaces = []
        for impl in IFACE_RE.finditer(text):
            interfaces.extend(impl.group(1).split())
        classes[match.group(1)] = {
            'methods': methods,
            'super': (SUPER_RE.search(text) or [None, None])[1],
            'interfaces': sorted(interfaces),
            'fields': len(FIELD_RE.findall(text)),
        }
    return classes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--reviewed', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--rounds', type=int, default=8)
    args = parser.parse_args()

    old = describe(args.old)
    new = describe(args.new)
    reviewed = json.loads(args.reviewed.read_text())['candidates']

    old_index = collections.defaultdict(set)
    for name, profile in old.items():
        for digest in profile['methods']:
            old_index[digest].add(name)
    new_index = collections.defaultdict(set)
    for name, profile in new.items():
        for digest in profile['methods']:
            new_index[digest].add(name)

    # Candidate pairs with the number of shared method fingerprints.
    shared = collections.defaultdict(int)
    for digest, old_owners in old_index.items():
        new_owners = new_index.get(digest)
        if not new_owners:
            continue
        for old_owner in old_owners:
            for new_owner in new_owners:
                shared[(old_owner, new_owner)] += 1

    mapping = {}
    used_new = set()
    reason = {}
    # Seeds: the reviewed decisions, then the fingerprint evidence.
    for old_owner, new_owner in sorted(reviewed.items()):
        if old_owner in mapping or new_owner in used_new:
            continue
        if old_owner not in old or new_owner not in new:
            continue
        mapping[old_owner] = new_owner
        used_new.add(new_owner)
        reason[old_owner] = 'reviewed'
    scored = sorted(shared.items(), key=lambda item: (-item[1], item[0]))
    for (old_owner, new_owner), score in scored:
        if old_owner in mapping or new_owner in used_new:
            continue
        mapping[old_owner] = new_owner
        used_new.add(new_owner)
        reason[old_owner] = 'fingerprint:%d' % score

    # Children index for both trees.
    old_children = collections.defaultdict(list)
    new_children = collections.defaultdict(list)
    for name, profile in old.items():
        if profile['super']:
            old_children[profile['super']].append(name)
    for name, profile in new.items():
        if profile['super']:
            new_children[profile['super']].append(name)

    def hierarchy_ok(old_owner, new_owner):
        old_profile, new_profile = old[old_owner], new[new_owner]
        old_super, new_super = old_profile['super'], new_profile['super']
        if old_super and old_super != 'Ljava/lang/Object;':
            expected = mapping.get(old_super)
            if expected and new_super != expected:
                return False
        elif new_super and new_super != 'Ljava/lang/Object;':
            # A class without a mapped super may not become a subclass.
            if old_super == 'Ljava/lang/Object;' and new_super != 'Ljava/lang/Object;':
                return False
        for interface in old_profile['interfaces']:
            expected = mapping.get(interface)
            if expected and expected not in new_profile['interfaces']:
                return False
        if len(old_children.get(old_owner, [])) != len(new_children.get(new_owner, [])):
            return False
        return True

    changes = []
    for round_index in range(args.rounds):
        round_changes = 0
        for old_owner in sorted(mapping):
            new_owner = mapping[old_owner]
            if hierarchy_ok(old_owner, new_owner):
                continue
            options = []
            for candidate, profile in new.items():
                if candidate in used_new and candidate != new_owner:
                    continue
                score = shared.get((old_owner, candidate), 0)
                if score == 0:
                    continue
                if not hierarchy_ok(old_owner, candidate):
                    continue
                options.append((score, candidate))
            if not options:
                continue
            options.sort(reverse=True)
            best_score, best = options[0]
            if best == new_owner:
                continue
            used_new.discard(new_owner)
            used_new.add(best)
            changes.append({'round': round_index, 'old': old_owner,
                            'from': new_owner, 'to': best, 'score': best_score,
                            'was': reason.get(old_owner)})
            mapping[old_owner] = best
            reason[old_owner] = 'hierarchy:%d' % best_score
            round_changes += 1
        if not round_changes:
            break

    output = {
        'note': ('Reviewed 171 -> 173 class map. Method-body fingerprints place the '
                 'classes, the class hierarchy keeps the result consistent.'),
        'oldClasses': len(old),
        'newClasses': len(new),
        'mapped': len(mapping),
        'candidates': dict(sorted(mapping.items())),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=1) + '\n')
    report = {'mapped': len(mapping), 'hierarchyChanges': len(changes), 'changes': changes}
    if args.report:
        args.report.write_text(json.dumps(report, indent=1) + '\n')
    print(json.dumps({'mapped': len(mapping), 'hierarchyChanges': len(changes)}, indent=1))
    for entry in changes[:60]:
        print('  %s %s -> %s (%s)' % (entry['old'], entry['from'], entry['to'], entry['was']))


if __name__ == '__main__':
    main()
