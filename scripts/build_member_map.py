#!/usr/bin/env python3
"""Build the reviewed 171 -> 173 member (method and field) map.

Member names are obfuscated as well, so every call site in the customized tree
has to be rewritten. This builder only proposes members of the class that the
reviewed class map assigns to the source class, which keeps the map one-to-one
and prevents cross-class mix-ups.
"""
import argparse
import collections
import difflib
import json
import re
from pathlib import Path

TYPE = re.compile(r'L[A-Za-z0-9_/$-]+;')
CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)
METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
HEADER_RE = re.compile(r'^\.method\s+.*?([^ ]+\([^\n]*)$')
FIELD_RE = re.compile(r'^\.field[^\n]*?\s([A-Za-z_$][\w$]*):(\S+)', re.M)
REF_M = re.compile(r'\b(L[A-Za-z0-9_/$-]+;)->([^\s(:]+)(\([^)]*\)\S+)')
REF_F = re.compile(r'\b(L[A-Za-z0-9_/$-]+;)->([^\s:]+):(\S+)')
ID_RE = re.compile(r'0x7f[0-9a-f]{6}')


def body_of(block):
    out = []
    for line in block.splitlines()[1:-1]:
        stripped = line.strip()
        if not stripped or stripped.startswith((
                '.line ', '.source ', '.local ', '.end local ', '.restart local ',
                '.param ', '.end param ', '.prologue', '#')):
            continue
        out.append(stripped)
    return out


def normalize(lines):
    result = []
    for line in lines:
        line = ID_RE.sub('@', line)
        line = re.sub(r'(L[A-Za-z0-9_/$-]+;)->([^\s(:]+)', r'\1->?', line)
        line = TYPE.sub('T', line)
        line = re.sub(r'\b[vp]\d+\b', 'r', line)
        line = re.sub(r':\w+', ':L', line)
        result.append(line)
    return result


def methods_of(path):
    text = path.read_text(errors='replace')
    result = {}
    for block in METHOD_RE.findall(text):
        header = HEADER_RE.match(block.splitlines()[0])
        if not header:
            continue
        result[header.group(1)] = normalize(body_of(block))
    return result


def refs_of(line):
    code = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line.split('#', 1)[0])
    result = []
    for match in REF_M.finditer(code):
        result.append(('m', match.group(1) + '->' + match.group(2) + match.group(3)))
    for match in REF_F.finditer(code):
        result.append(('f', match.group(1) + '->' + match.group(2) + ':' + match.group(3)))
    owners = {ref.split('->', 1)[0] for _, ref in result}
    for match in TYPE.finditer(code):
        if match.group(0) not in owners:
            result.append(('t', match.group(0)))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--class-map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()

    class_map = json.loads(args.class_map.read_text())['candidates']
    members = collections.defaultdict(collections.Counter)
    fields = collections.defaultdict(collections.Counter)
    method_pairs = 0
    for source, target in class_map.items():
        old_path = args.old / 'smali' / (source[1:-1] + '.smali')
        new_path = args.new / 'smali' / (target[1:-1] + '.smali')
        if not old_path.is_file() or not new_path.is_file():
            continue
        old_methods = methods_of(old_path)
        new_methods = methods_of(new_path)
        by_body = collections.defaultdict(list)
        for signature, body in new_methods.items():
            by_body['\n'.join(body)].append(signature)
        for signature, body in old_methods.items():
            candidates = by_body.get('\n'.join(body), [])
            if len(candidates) == 1:
                target_signature = candidates[0]
            else:
                scored = sorted(((difflib.SequenceMatcher(None, body, new_methods[s], autojunk=False).ratio(), s)
                                 for s in new_methods), reverse=True)
                if not scored or scored[0][0] < 0.8:
                    continue
                target_signature = scored[0][1]
            method_pairs += 1
            target_body = new_methods[target_signature]
            matcher = difflib.SequenceMatcher(None, body, target_body, autojunk=False)
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag != 'equal':
                    continue
                for offset in range(min(i2 - i1, j2 - j1)):
                    old_refs = refs_of(body[i1 + offset])
                    new_refs = refs_of(target_body[j1 + offset])
                    for kind, bucket in (('m', members), ('f', fields)):
                        old_owned = [ref for k, ref in old_refs
                                     if k == kind and ref.split('->', 1)[0] == source]
                        new_owned = [ref for k, ref in new_refs
                                     if k == kind and ref.split('->', 1)[0] == target]
                        if len(old_owned) != len(new_owned):
                            continue
                        for old_ref, new_ref in zip(old_owned, new_owned):
                            if old_ref != new_ref:
                                bucket[old_ref][new_ref] += 1
    members_out = {key: counts.most_common(1)[0][0]
                   for key, counts in members.items() if counts.most_common(1)[0][1] > 0}
    fields_out = {key: counts.most_common(1)[0][0]
                  for key, counts in fields.items() if counts.most_common(1)[0][0]}
    args.output.write_text(json.dumps({
        'warning': 'reviewed member map for the pinned 171 -> 173 migration',
        'members': {key: {'new': value} for key, value in members_out.items()},
        'fields': {key: {'new': value} for key, value in fields_out.items()},
    }, indent=1) + '\n')
    report = {'methodPairs': method_pairs, 'members': len(members_out), 'fields': len(fields_out)}
    if args.report:
        args.report.write_text(json.dumps(report, indent=1) + '\n')
    print(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
