#!/usr/bin/env python3
"""Gate every class-map correction by the migration coverage.

A class-map correction is only accepted when the customized methods of the
migration are still all located in the 173 tree afterwards.  That makes the
coverage report the judge of the map: a correction that moves a class away
from the class that holds one of the customized methods is rejected, because
the migration would lose that method.

The candidates come from the method-body proofs; the script applies them one
at a time and keeps only the ones that leave the coverage complete.
"""
import argparse
import collections
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)
TYPE_RE = re.compile(r'L[A-Za-z0-9_/$-]+;')


def fingerprint(block, owner):
    text = re.sub(r'^\s*\.(?:line|source|local|end local|restart local|prologue|param)\b[^\n]*',
                  '', block, flags=re.M)
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
        digests = set()
        signatures = collections.Counter()
        for block in METHOD_RE.findall(text):
            canonical = fingerprint(block, owner)
            if len(canonical) >= 24:
                digests.add(hashlib.sha256(canonical.encode()).hexdigest())
            signatures[block.splitlines()[0].split()[-1]] += 1
        classes[owner] = {'digests': digests, 'signatures': signatures}
    return classes


def proofs_between(old, new, source, target):
    """Count the method bodies of source that occur in exactly one class of
    each tree and land in target."""
    old_index = collections.defaultdict(set)
    new_index = collections.defaultdict(set)
    for name, profile in old.items():
        for digest in profile['digests']:
            old_index[digest].add(name)
    for name, profile in new.items():
        for digest in profile['digests']:
            new_index[digest].add(name)
    hit = 0
    for digest in old[source]['digests']:
        if old_index[digest] != {source}:
            continue
        if new_index.get(digest) == {target}:
            hit += 1
    return hit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--class-map', type=Path, required=True)
    parser.add_argument('--coverage', type=Path, required=True)
    parser.add_argument('--builder', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--min-proofs', type=int, default=1)
    args = parser.parse_args()

    old = load(args.old)
    new = load(args.new)
    document = json.loads(args.class_map.read_text())
    mapping = dict(document['candidates'])

    def signature_score(source, target):
        if target not in new:
            return 0.0
        old_profile, new_profile = old[source], new[target]
        mapped = collections.Counter(
            TYPE_RE.sub(lambda match: mapping.get(match.group(0), match.group(0)),
                        signature)
            for signature in old_profile['signatures'])
        hit = sum(min(count, new_profile['signatures'].get(signature, 0))
                  for signature, count in mapped.items())
        total = sum(old_profile['signatures'].values())
        return hit / total if total else 0.0

    def coverage_for(candidate_mapping):
        with tempfile.TemporaryDirectory(prefix='.boxproxy-gate-') as temp:
            map_path = Path(temp) / 'class-map.json'
            out_path = Path(temp) / 'coverage.json'
            map_path.write_text(json.dumps({'candidates': candidate_mapping}))
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

    baseline = coverage_for(mapping)
    if baseline is None:
        raise SystemExit('the coverage builder failed on the baseline map')
    print('baseline coverage: %d completed, %d pending' % (baseline[0], len(baseline[1])))
    if baseline[1]:
        print('  pending:', baseline[1][:5])

    candidates = []
    for source, profile in old.items():
        for digest in profile['digests']:
            pass
    # The candidates are the classes whose proofs contradict the baseline.
    old_index = collections.defaultdict(set)
    new_index = collections.defaultdict(set)
    for name, profile in old.items():
        for digest in profile['digests']:
            old_index[digest].add(name)
    for name, profile in new.items():
        for digest in profile['digests']:
            new_index[digest].add(name)
    proof_table = collections.defaultdict(collections.Counter)
    for digest, old_owners in old_index.items():
        new_owners = new_index.get(digest)
        if not new_owners or len(old_owners) != 1 or len(new_owners) != 1:
            continue
        proof_table[next(iter(old_owners))][next(iter(new_owners))] += 1

    used = collections.Counter(mapping.values())
    used_sources = {target: source for source, target in mapping.items()}
    for source, targets in proof_table.items():
        current = mapping.get(source)
        if current is None:
            continue
        for target, count in targets.items():
            if target == current or count < args.min_proofs:
                continue
            if proof_table[source].get(current, 0) >= count:
                continue
            owner = used_sources.get(target)
            if owner is not None and owner != source:
                continue
            if signature_score(source, target) <= signature_score(source, current):
                continue
            candidates.append((count, source, current, target))
    candidates.sort(key=lambda item: (-item[0], item[1]))

    accepted = []
    rejected = []
    for count, source, current, target in candidates:
        trial = dict(mapping)
        trial[source] = target
        result = coverage_for(trial)
        if result is None or result[1]:
            rejected.append({'old': source, 'from': current, 'to': target,
                             'proofs': count,
                             'reason': 'coverage incomplete: %s' % (result[1][:2] if result else 'error')})
            continue
        owners = [other for other, value in trial.items()
                  if value == target and other != source]
        if owners:
            rejected.append({'old': source, 'from': current, 'to': target,
                             'proofs': count,
                             'reason': 'target already used by ' + ','.join(sorted(owners))})
            continue
        mapping = trial
        used_sources.pop(current, None)
        used_sources[target] = source
        accepted.append({'old': source, 'from': current, 'to': target, 'proofs': count})

    document['candidates'] = dict(sorted(mapping.items()))
    document['mapped'] = len(mapping)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1) + '\n')
    report = {'accepted': accepted, 'rejected': rejected}
    if args.report:
        args.report.write_text(json.dumps(report, indent=1) + '\n')
    print('accepted %d, rejected %d' % (len(accepted), len(rejected)))
    for entry in accepted:
        print('  ACCEPT %s: %s -> %s (proofs %d)'
              % (entry['old'], entry['from'], entry['to'], entry['proofs']))
    for entry in rejected:
        print('  REJECT %s: %s -> %s (%s)'
              % (entry['old'], entry['from'], entry['to'], entry['reason']))


if __name__ == '__main__':
    main()
