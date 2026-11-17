#!/usr/bin/env python3
"""Reject executable Smali branches whose target has offset zero.

ART/Dalvik rejects zero-offset if/goto branches at class verification time even
though Apktool/Smali may assemble them into DEX. Labels and debug directives do
not occupy code units, so the check compares executable instruction positions.
"""
import argparse
from pathlib import Path
import re

BRANCH_OPS = {'goto', 'goto/16', 'goto/32'}
DATA_BLOCKS = {'.packed-switch': '.end packed-switch',
               '.sparse-switch': '.end sparse-switch',
               '.array-data': '.end array-data'}


def zero_offset_branches(text, path='<smali>'):
    """Return diagnostics for if/goto branches targeting their own instruction."""
    errors = []
    in_method = False
    data_end = None
    address = 0
    labels = {}
    branches = []
    method_name = ''

    def finish_method():
        for branch_address, target, line_no in branches:
            if any(label_address == branch_address
                   for label_address, _ in labels.get(target, ())):
                errors.append(
                    f'{path}:{line_no}: {method_name}: branch offset zero to :{target}')

    for line_no, line in enumerate(text.splitlines(), 1):
        code = line.split('#', 1)[0].strip()
        if not in_method:
            if code.startswith('.method '):
                in_method = True
                method_name = code
                address = 0
                labels = {}
                branches = []
            continue

        if code == '.end method':
            finish_method()
            in_method = False
            data_end = None
            continue
        if not code:
            continue

        if data_end is not None:
            if code == data_end:
                data_end = None
            continue

        directive = code.split(None, 1)[0]
        if directive in DATA_BLOCKS:
            data_end = DATA_BLOCKS[directive]
            continue
        if code.startswith(':'):
            label = code.split(None, 1)[0][1:]
            labels.setdefault(label, []).append((address, line_no))
            continue
        if code.startswith('.'):
            continue

        parts = code.split()
        opcode = parts[0]
        if opcode.startswith('if-') or opcode in BRANCH_OPS:
            target = parts[-1]
            if target.startswith(':'):
                branches.append((address, target[1:], line_no))
        address += 1

    return errors


def scan_project(project):
    project = Path(project)
    results = []
    files = sorted((project / 'smali').rglob('*.smali'))
    for path in files:
        results.extend(zero_offset_branches(
            path.read_text(errors='replace'), path.relative_to(project).as_posix()))
    return len(files), results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', nargs='?', type=Path, default=Path('decompiled'))
    args = parser.parse_args()
    classes, errors = scan_project(args.project)
    for error in errors:
        print(error)
    if errors:
        print(f'Found {len(errors)} zero-offset branches in {classes} Smali files')
        return 1
    print(f'Checked {classes} Smali files; no zero-offset if/goto branches')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
