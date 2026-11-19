#!/usr/bin/env python3
"""Derive the 171 -> 173 migration coverage from the reviewed 171 coverage.

Every customized method of the 171 migration is located again in the 173
upstream tree: the owning class comes from the reviewed class map and the
method is matched by its normalised body inside that class. The result is a
reviewed artifact for the porter; it never rewrites runtime code.
"""
import argparse
import collections
import difflib
import hashlib
import json
import re
from pathlib import Path

TYPE = re.compile(r'L[A-Za-z0-9_/$-]+;')
CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)
METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
HEADER_RE = re.compile(r'^\.method\s+.*?([^ ]+\([^\n]*)$')
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True,
                        help='upstream 171 project')
    parser.add_argument('--new', type=Path, required=True,
                        help='upstream 173 project')
    parser.add_argument('--coverage', type=Path, required=True,
                        help='reviewed 171 coverage (139 -> 171)')
    parser.add_argument('--class-map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()

    coverage = json.loads(args.coverage.read_text())
    class_map = json.loads(args.class_map.read_text())['candidates']
    completed, errors = [], []
    for item in coverage['completed']:
        source_owner, source_signature = item['new'].split('->', 1)
        target_owner = class_map.get(source_owner)
        if not target_owner:
            errors.append('unmapped class ' + source_owner)
            continue
        source_path = args.base / 'smali' / (source_owner[1:-1] + '.smali')
        target_path = args.new / 'smali' / (target_owner[1:-1] + '.smali')
        if not source_path.is_file() or not target_path.is_file():
            errors.append('missing class file for ' + source_owner)
            continue
        source_methods = methods_of(source_path)
        source_body = source_methods.get(source_signature)
        if source_body is None:
            errors.append('missing 171 method ' + item['new'])
            continue
        target_methods = methods_of(target_path)
        exact = [signature for signature, body in target_methods.items()
                 if body == source_body]
        if len(exact) == 1:
            target_signature = exact[0]
            confidence = 'exact-body'
        elif exact:
            target_signature = sorted(exact)[0]
            confidence = 'exact-body-ambiguous'
        else:
            scored = sorted(
                ((difflib.SequenceMatcher(None, source_body, body, autojunk=False).ratio(),
                  signature)
                 for signature, body in target_methods.items()), reverse=True)
            runner_up = scored[1][0] if len(scored) > 1 else 0.0
            if not scored or scored[0][0] < 0.5 or scored[0][0] - runner_up < 0.03:
                errors.append('no 173 method for ' + item['new'])
                continue
            target_signature = scored[0][1]
            confidence = 'body-ratio:%.3f' % scored[0][0]
        completed.append({
            'old': item['new'],
            'new': target_owner + '->' + target_signature,
            'sourceFile': 'smali/' + source_owner[1:-1] + '.smali',
            'targetFile': 'smali/' + target_owner[1:-1] + '.smali',
            'mode': item['mode'],
            'confidence': confidence,
            'evidence': item.get('evidence', []),
        })
    print('mapped methods:', len(completed), 'errors:', len(errors))
    for error in errors:
        print('  ERROR', error)
    yml = (args.new / 'apktool.yml').read_text()
    version_name = re.search(r'^\s*versionName:\s*(\S+)', yml, re.M).group(1)
    version_code = int(re.search(r'^\s*versionCode:\s*(\d+)', yml, re.M).group(1))
    args.output.write_text(json.dumps({
        'versionName': version_name,
        'versionCode': version_code,
        'completed': completed,
        'added': coverage['added'],
        'collisions': [],
        'manual': [],
        'pending': errors,
        'manualTargets': {},
        'mappingPolicy': ('The upstream APK is the immutable source. Every customized method of the '
                          '171 migration is relocated through the reviewed 171 -> 173 class map and '
                          'matched by its normalised body inside the target class; references are '
                          'remapped once per original token.'),
    }, indent=1) + '\n')


if __name__ == '__main__':
    main()
