#!/usr/bin/env python3
"""Build reviewed candidate 139->171 type/member maps from pinned Smali trees.

First generate class candidates (heuristic suggestions only):
  python3 scripts/suggest_upstream_classes.py \
    .tools/upstream-old/decompiled .tools/upstream-new/decompiled \
    --baseline HEAD --customized HEAD --output .tools/class-candidates.json
Then run this script. It validates one-to-one class targets, gives explicit
coverage pairs precedence, and emits detailed maps for the porter. It never
rewrites the runtime tree by itself.
"""
import argparse
import collections
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

# Keep descriptor scanning strict enough that names beginning with L (for
# example LongClickListener) are not mistaken for class descriptors.
TYPE_RE = re.compile(r'L[A-Za-z0-9_/$-]+;')
REF_M = re.compile(r'\b(L[A-Za-z0-9_/$-]+;)->([^\s(:]+)(\([^)]*\)\S+)')
REF_F = re.compile(r'\b(L[A-Za-z0-9_/$-]+;)->([^\s:]+):(\S+)')
METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
HEADER_RE = re.compile(r'^\.method\s+.*?([^ ]+\([^\n]*)$')


def resource_map(root):
    public_xml = root / 'res/values/public.xml'
    return {
        entry.attrib['id']: entry.attrib['type'] + '.' + entry.attrib['name']
        for entry in ET.parse(public_xml).getroot()
        if entry.tag == 'public'
    }


def normalize_method(text, resources):
    text = re.sub(
        r'^\s*\.(?:line|source|local|end local|restart local|prologue|param)\b[^\n]*',
        '', text, flags=re.M)
    text = re.sub(r'0x7f[0-9a-f]{6}', lambda m: resources.get(m[0], m[0]), text)
    text = re.sub(r'L[^/;\s\[():]+;', 'L?;', text)
    text = re.sub(r'(L\?;->)[^\s(:]+(?=[:(])', r'\1?', text)
    text = re.sub(r'(?m)(^\s*\.method[^\n]*? )[^ (]+(?=\()', r'\1?', text)
    text = re.sub(r'(?m)(^\s*\.field[^\n]*? )[^ :]+(?=:)', r'\1?', text)
    return '\n'.join(
        line.strip() for line in text.splitlines()
        if line.strip() and not line.strip().startswith('#')
    )


def method_signature(block):
    match = HEADER_RE.match(block.splitlines()[0])
    return match.group(1) if match else None


def methods(path):
    text = path.read_text(errors='replace')
    result = {}
    for match in METHOD_RE.finditer(text):
        block = match.group(0).rstrip()
        signature = method_signature(block)
        if signature:
            result[signature] = block
    return result


def class_path(root, descriptor):
    return root / 'smali' / (descriptor[1:-1] + '.smali')


def line_references(line):
    cleaned = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line.split('#', 1)[0])
    result = []
    for match in REF_M.finditer(cleaned):
        result.append(('members', match.group(1) + '->' + match.group(2) + match.group(3)))
    for match in REF_F.finditer(cleaned):
        result.append(('fields', match.group(1) + '->' + match.group(2) + ':' + match.group(3)))
    owners = {reference[1].split('->', 1)[0] for reference in result}
    for match in TYPE_RE.finditer(cleaned):
        if match.group(0) not in owners:
            result.append(('types', match.group(0)))
    return result


def normalized_code_pairs(block, resources):
    result = []
    for line in block.splitlines()[1:-1]:
        raw = line.strip()
        if (not raw or raw.startswith((
                '.line ', '.source ', '.local ', '.end local ', '.restart local ',
                '.param ', '.end param ', '.prologue', '#'))):
            continue
        normalized = re.sub(r'0x7f[0-9a-f]{6}', lambda m: resources.get(m[0], m[0]), raw)
        normalized = re.sub(r'L[^/;\s\[():]+;', 'L?;', normalized)
        normalized = re.sub(r'(L\?;->)[^\s(:]+(?=[:(])', r'\1?', normalized)
        result.append((raw, normalized))
    return result


def class_index(root):
    result = {}
    for path in (root / 'smali').rglob('*.smali'):
        text = path.read_text(errors='replace')
        match = re.search(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', text, re.M)
        if match:
            result[match.group(1)] = path
    return result


def resolve_votes(votes):
    result = {}
    for old, counts in votes.items():
        ordered = counts.most_common()
        if ordered and (len(ordered) == 1 or ordered[0][1] > ordered[1][1]):
            result[old] = ordered[0][0]
    return result


def generate(old_root, new_root, coverage_path, candidates_path):
    old_root, new_root = Path(old_root), Path(new_root)
    coverage = json.loads(Path(coverage_path).read_text())
    candidates = json.loads(Path(candidates_path).read_text())['candidates']
    old_classes, new_classes = class_index(old_root), class_index(new_root)

    # Heuristic candidates are accepted only if both endpoints exist and the
    # destination is unique. Reviewed coverage owners are added next.
    types = dict(candidates)
    invalid = [(old, new) for old, new in types.items()
               if old not in old_classes or new not in new_classes]
    reverse = collections.defaultdict(list)
    for old, new in types.items():
        reverse[new].append(old)
    duplicates = {new: owners for new, owners in reverse.items() if len(owners) > 1}
    if invalid or duplicates:
        raise ValueError(f'class candidates failed validation: invalid={len(invalid)} '
                         f'duplicateTargets={len(duplicates)}')

    explicit_methods = {}
    reviewed_types = dict(types)
    for item in coverage['completed']:
        old, new = item['old'], item['new']
        old_owner, old_signature = old.split('->', 1)
        new_owner, new_signature = new.split('->', 1)
        reviewed_types[old_owner] = new_owner
        explicit_methods[old] = new
    reverse = collections.defaultdict(list)
    for old, new in reviewed_types.items():
        reverse[new].append(old)
    duplicates = {new: owners for new, owners in reverse.items() if len(owners) > 1}
    invalid = [(old, new) for old, new in reviewed_types.items()
               if old not in old_classes or new not in new_classes]
    if invalid or duplicates:
        raise ValueError(f'explicit class pairs failed validation: invalid={len(invalid)} '
                         f'duplicateTargets={len(duplicates)}')

    old_resources = resource_map(old_root)
    new_resources = resource_map(new_root)
    type_votes = collections.defaultdict(collections.Counter)
    member_votes = collections.defaultdict(collections.Counter)
    field_votes = collections.defaultdict(collections.Counter)
    matched_pairs = 0
    for old_owner, new_owner in reviewed_types.items():
        old_path = class_path(old_root, old_owner)
        new_path = class_path(new_root, new_owner)
        if not old_path.is_file() or not new_path.is_file():
            continue
        old_methods, new_methods = methods(old_path), methods(new_path)
        old_hashes = collections.defaultdict(list)
        new_hashes = collections.defaultdict(list)
        for signature, block in old_methods.items():
            canonical = normalize_method(block, old_resources)
            if len(canonical) > 100:
                old_hashes[hashlib.sha256(canonical.encode()).hexdigest()].append((signature, block))
        for signature, block in new_methods.items():
            canonical = normalize_method(block, new_resources)
            if len(canonical) > 100:
                new_hashes[hashlib.sha256(canonical.encode()).hexdigest()].append((signature, block))
        for fingerprint, old_matches in old_hashes.items():
            new_matches = new_hashes.get(fingerprint, ())
            if len(old_matches) != 1 or len(new_matches) != 1:
                continue
            old_signature, old_block = old_matches[0]
            new_signature, new_block = new_matches[0]
            matched_pairs += 1
            old_lines = normalized_code_pairs(old_block, old_resources)
            new_lines = normalized_code_pairs(new_block, new_resources)
            if (len(old_lines) != len(new_lines)
                    or [line[1] for line in old_lines] != [line[1] for line in new_lines]):
                continue
            for (old_line, _), (new_line, _) in zip(old_lines, new_lines):
                old_refs, new_refs = line_references(old_line), line_references(new_line)
                for (old_category, old_ref), (new_category, new_ref) in zip(old_refs, new_refs):
                    if old_category != new_category or old_ref == new_ref:
                        continue
                    votes = {
                        'members': member_votes,
                        'fields': field_votes,
                        'types': type_votes,
                    }[old_category]
                    if old_ref.startswith('L') and new_ref.startswith('L'):
                        votes[old_ref][new_ref] += 1

    def descriptor_types(signature):
        return TYPE_RE.findall(signature)

    for old, new in explicit_methods.items():
        _, old_signature = old.split('->', 1)
        _, new_signature = new.split('->', 1)
        old_types, new_types = descriptor_types(old_signature), descriptor_types(new_signature)
        if len(old_types) == len(new_types):
            for old_type, new_type in zip(old_types, new_types):
                if old_type != new_type and old_type.startswith('L') and new_type.startswith('L'):
                    type_votes[old_type][new_type] += 20

    # Explicit coverage owner pairs outrank incidental call-site votes.
    types_out = dict(reviewed_types)
    reverse = collections.defaultdict(list)
    for old, new in types_out.items():
        reverse[new].append(old)
    accepted_type_votes = {}
    rejected_type_votes = []
    for old, new in resolve_votes(type_votes).items():
        if old in types_out:
            if types_out[old] != new:
                rejected_type_votes.append((old, new, 'candidate mapping takes precedence'))
            continue
        if old not in old_classes:
            rejected_type_votes.append((old, new, 'source class absent from 139'))
            continue
        if new not in new_classes:
            rejected_type_votes.append((old, new, 'target class absent from 171'))
            continue
        if new in reverse and old not in reverse[new]:
            rejected_type_votes.append((old, new, 'target already assigned to another source class'))
            continue
        types_out[old] = new
        accepted_type_votes[old] = new
        reverse[new].append(old)

    members_out = resolve_votes(member_votes)
    members_out.update(explicit_methods)
    fields_out = resolve_votes(field_votes)

    # Preserve same-name declarations only after class ownership is known.
    for old_owner, new_owner in reviewed_types.items():
        old_path, new_path = class_path(old_root, old_owner), class_path(new_root, new_owner)
        if not old_path.is_file() or not new_path.is_file():
            continue
        old_text, new_text = old_path.read_text(errors='replace'), new_path.read_text(errors='replace')
        old_fields = {
            match.group(1): match.group(2)
            for match in re.finditer(r'^\.field[^\n]*?\s([A-Za-z_$][\w$]*):(\S+)', old_text, re.M)
        }
        new_fields = {
            match.group(1): match.group(2)
            for match in re.finditer(r'^\.field[^\n]*?\s([A-Za-z_$][\w$]*):(\S+)', new_text, re.M)
        }
        for name, old_type in old_fields.items():
            if name in new_fields:
                fields_out.setdefault(
                    old_owner + '->' + name + ':' + old_type,
                    new_owner + '->' + name + ':' + new_fields[name])
        new_signatures = set(methods(new_path))
        for signature in methods(old_path):
            mapped_signature = TYPE_RE.sub(
                lambda match: types_out.get(match.group(0), match.group(0)), signature)
            if mapped_signature in new_signatures:
                members_out.setdefault(old_owner + '->' + signature,
                                       new_owner + '->' + mapped_signature)

    maps = {
        'types': {key: {'new': value} for key, value in types_out.items()},
        'members': {key: {'new': value} for key, value in members_out.items()},
        'fields': {key: {'new': value} for key, value in fields_out.items()},
        '_stats': {
            'candidateTypes': len(candidates),
            'reviewedOwnerTypes': len(reviewed_types),
            'acceptedTypeVotes': len(accepted_type_votes),
            'rejectedTypeVotes': len(rejected_type_votes),
            'types': len(types_out),
            'methodPairs': matched_pairs,
            'members': len(members_out),
            'fields': len(fields_out),
            'typeVotes': len(type_votes),
            'memberVotes': len(member_votes),
        },
    }
    review = {
        'warning': 'Heuristic mappings remain review candidates; use the detailed endpoint audit before migration.',
        'rejectedTypeVotes': [
            {'old': old, 'new': new, 'reason': reason}
            for old, new, reason in rejected_type_votes
        ],
    }
    return maps, review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, default=Path('.tools/upstream-old/decompiled'))
    parser.add_argument('--new', type=Path, default=Path('.tools/upstream-new/decompiled'))
    parser.add_argument('--coverage', type=Path,
                        default=Path('upstream/26.11.16.25abc84/migration/coverage.json'))
    parser.add_argument('--candidates', type=Path, default=Path('.tools/class-candidates.json'))
    parser.add_argument('--output', type=Path, default=Path('.tools/resolved-maps.json'))
    parser.add_argument('--review', type=Path, default=Path('.tools/map-review.json'))
    args = parser.parse_args()
    maps, review = generate(args.old, args.new, args.coverage, args.candidates)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.review.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(maps, indent=2) + '\n')
    args.review.write_text(json.dumps(review, indent=2) + '\n')
    print(json.dumps(maps['_stats'], indent=2))


if __name__ == '__main__':
    main()
