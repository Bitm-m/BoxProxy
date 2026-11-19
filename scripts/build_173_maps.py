#!/usr/bin/env python3
"""Build the reviewed 171 -> 173 type/member/field maps.

The class map is the input: every class is matched by hand-reviewed evidence,
and this script derives the member level from it.  Two classes that are
matched to each other contribute member and field votes only from call sites
that occur inside a method pair that the class map already ties together, so
a member never leaves its owner class.

Method pairs are established with the normalized-body fingerprint that
survives an R8 rename: the body with all type names, member names, resource
ids and line numbers masked out.
"""
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

TYPE_RE = re.compile(r'L[A-Za-z0-9_/$-]+;')
REF_M = re.compile(r'\b(L[A-Za-z0-9_/$-]+;)->([^\s(:]+)(\([^)]*\)\S+)')
REF_F = re.compile(r'\b(L[A-Za-z0-9_/$-]+;)->([^\s:]+):(\S+)')
METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
HEADER_RE = re.compile(r'^\.method\s+.*?([^\s(]+\([^\n]*)$')
FIELD_RE = re.compile(r'^\.field[^\n]*?\s([A-Za-z_$][\w$]*):(\S+)')


def class_index(root):
    result = {}
    for path in (root / 'smali').rglob('*.smali'):
        match = re.search(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)',
                          path.read_text(errors='replace'), re.M)
        if match:
            result[match.group(1)] = path
    return result


def methods(path):
    text = path.read_text(errors='replace')
    result = {}
    for match in METHOD_RE.finditer(text):
        block = match.group(0).rstrip()
        header = HEADER_RE.match(block.splitlines()[0])
        if header:
            result[header.group(1)] = block
    return result


def fingerprint(block):
    """Mask everything a rename can change: types, member names, ids, lines."""
    text = re.sub(r'^\s*\.(?:line|source|local|end local|restart local|prologue|param)\b[^\n]*',
                  '', block, flags=re.M)
    text = re.sub(r'0x7f[0-9a-f]{6}', '@', text)
    text = re.sub(r'L[^/;\s\[():]+;', 'L?;', text)
    text = re.sub(r'(L\?;->)[^\s(:]+(?=[:(])', r'\1?', text)
    text = re.sub(r'(?m)(^s*\.(?:method|field)[^\n]*? )[^ :]+(?=[:(])', r'\1?', text)
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '"s"', text)
    return '\n'.join(line.strip() for line in text.splitlines()
                     if line.strip() and not line.strip().startswith('#'))


def code_pairs(block):
    """Return the (raw, normalized) instruction pairs of a method body."""
    result = []
    for line in block.splitlines()[1:-1]:
        raw = line.strip()
        if (not raw or raw.startswith((
                '.line ', '.source ', '.local ', '.end local ', '.restart local ',
                '.param ', '.end param ', '.prologue', '#'))):
            continue
        normalized = re.sub(r'0x7f[0-9a-f]{6}', '@', raw)
        normalized = re.sub(r'L[^/;\s\[():]+;', 'L?;', normalized)
        normalized = re.sub(r'(L\?;->)[^\s(:]+(?=[:(])', r'\1?', normalized)
        result.append((raw, normalized))
    return result


def references(line):
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


def resolve(votes):
    result = {}
    for old, counts in votes.items():
        ranked = counts.most_common()
        if ranked and (len(ranked) == 1 or ranked[0][1] > ranked[1][1]):
            result[old] = ranked[0][0]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--class-map', type=Path, required=True)
    parser.add_argument('--coverage', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    args = parser.parse_args()

    class_map = json.loads(args.class_map.read_text())['candidates']
    old_classes, new_classes = class_index(args.old), class_index(args.new)
    invalid = [(old, new) for old, new in class_map.items()
               if old not in old_classes or new not in new_classes]
    reverse = collections.defaultdict(list)
    for old, new in class_map.items():
        reverse[new].append(old)
    duplicates = {new: owners for new, owners in reverse.items() if len(owners) > 1}
    if invalid or duplicates:
        raise SystemExit('class map failed validation: invalid=%d duplicates=%d'
                         % (len(invalid), len(duplicates)))

    types = dict(class_map)
    if args.coverage:
        coverage = json.loads(args.coverage.read_text())
        for item in coverage['completed']:
            old_owner, old_signature = item['old'].split('->', 1)
            new_owner, new_signature = item['new'].split('->', 1)
            if types.get(old_owner) not in (None, new_owner):
                raise SystemExit('coverage contradicts the class map: ' + item['old'])
            types[old_owner] = new_owner

    member_votes = collections.defaultdict(collections.Counter)
    field_votes = collections.defaultdict(collections.Counter)
    type_votes = collections.defaultdict(collections.Counter)
    matched_pairs = 0
    identical_pairs = 0
    for old_owner, new_owner in sorted(types.items()):
        old_path, new_path = old_classes.get(old_owner), new_classes.get(new_owner)
        if old_path is None or new_path is None:
            continue
        old_methods, new_methods = methods(old_path), methods(new_path)
        old_hashes = collections.defaultdict(list)
        new_hashes = collections.defaultdict(list)
        for signature, block in old_methods.items():
            canonical = fingerprint(block)
            if len(canonical) > 80:
                old_hashes[hashlib.sha256(canonical.encode()).hexdigest()].append((signature, block))
        for signature, block in new_methods.items():
            canonical = fingerprint(block)
            if len(canonical) > 80:
                new_hashes[hashlib.sha256(canonical.encode()).hexdigest()].append((signature, block))
        for digest, old_matches in old_hashes.items():
            new_matches = new_hashes.get(digest, ())
            if len(old_matches) != 1 or len(new_matches) != 1:
                continue
            old_signature, old_block = old_matches[0]
            new_signature, new_block = new_matches[0]
            matched_pairs += 1
            old_lines, new_lines = code_pairs(old_block), code_pairs(new_block)
            if [item[1] for item in old_lines] != [item[1] for item in new_lines]:
                continue
            identical_pairs += 1
            for (old_line, _), (new_line, _) in zip(old_lines, new_lines):
                old_refs, new_refs = references(old_line), references(new_line)
                if len(old_refs) != len(new_refs):
                    continue
                for (old_category, old_ref), (new_category, new_ref) in zip(old_refs, new_refs):
                    if old_category != new_category or old_ref == new_ref:
                        continue
                    if not (old_ref.startswith('L') and new_ref.startswith('L')):
                        continue
                    if old_category == 'members':
                        member_votes[old_ref][new_ref] += 1
                    elif old_category == 'fields':
                        field_votes[old_ref][new_ref] += 1
                    else:
                        type_votes[old_ref][new_ref] += 1

    members = resolve(member_votes)
    fields = resolve(field_votes)
    # A member may only be renamed inside the class the class map assigns to
    # its owner; a vote that crosses that boundary is not trustworthy.
    members = {old: new for old, new in members.items()
               if old.split('->', 1)[0] in types
               and new.split('->', 1)[0] == types[old.split('->', 1)[0]]}
    fields = {old: new for old, new in fields.items()
              if old.split('->', 1)[0] in types
              and new.split('->', 1)[0] == types[old.split('->', 1)[0]]}

    # Declarations that survived the rename keep their name; that is the
    # strongest signal available and it fills the gaps of the vote based map.
    for old_owner, new_owner in types.items():
        old_path, new_path = old_classes.get(old_owner), new_classes.get(new_owner)
        if old_path is None or new_path is None:
            continue
        old_text = old_path.read_text(errors='replace')
        new_text = new_path.read_text(errors='replace')
        old_fields = {match.group(1): match.group(2)
                      for match in FIELD_RE.finditer(old_text)}
        new_fields = {match.group(1): match.group(2)
                      for match in FIELD_RE.finditer(new_text)}
        for name, old_type in old_fields.items():
            if name in new_fields:
                fields.setdefault(old_owner + '->' + name + ':' + old_type,
                                  new_owner + '->' + name + ':' + new_fields[name])
        new_signatures = set(methods(new_path))
        for signature in methods(old_path):
            mapped = TYPE_RE.sub(lambda match: types.get(match.group(0), match.group(0)),
                                 signature)
            if mapped in new_signatures:
                members.setdefault(old_owner + '->' + signature,
                                   new_owner + '->' + mapped)

    maps = {
        'types': {key: {'new': value} for key, value in sorted(types.items())},
        'members': {key: {'new': value} for key, value in sorted(members.items())},
        'fields': {key: {'new': value} for key, value in sorted(fields.items())},
        '_stats': {
            'types': len(types),
            'members': len(members),
            'fields': len(fields),
            'methodPairs': matched_pairs,
            'identicalBodyPairs': identical_pairs,
            'memberVotes': len(member_votes),
            'fieldVotes': len(field_votes),
            'typeVotes': len(type_votes),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(maps, indent=1) + '\n')
    if args.review:
        rejected = [
            {'old': old, 'new': new, 'reason': 'owner class mismatch'}
            for old, new in resolve(member_votes).items()
            if old.split('->', 1)[0] in types
            and new.split('->', 1)[0] != types[old.split('->', 1)[0]]]
        args.review.write_text(json.dumps({
            'warning': 'Reviewed 171 -> 173 member map; owner-crossing votes are rejected.',
            'rejectedMemberVotes': rejected,
        }, indent=1) + '\n')
    print(json.dumps(maps['_stats'], indent=1))


if __name__ == '__main__':
    main()
