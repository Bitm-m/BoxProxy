#!/usr/bin/env python3
"""Reject Smali methods with duplicate or dangling labels.

The dex format gives every label a unique name inside its method and every
branch has to name a label that exists.  A port that re-anchors a hunk can
copy a label into a method that already defines it, or leave a branch that
points at a label the target method never defines; both break assembly or
verification.  Apktool is lenient about the first and the second only shows
up at runtime, so the port checks them itself.
"""
import argparse
import re
from pathlib import Path

BRANCH_OPS = {'goto', 'goto/16', 'goto/32'}
DATA_BLOCKS = {'.packed-switch': '.end packed-switch',
               '.sparse-switch': '.end sparse-switch',
               '.array-data': '.end array-data'}
LABEL_RE = re.compile(r'^:(\w+)')


def check_text(text, path):
    problems = []
    in_method = False
    method = ''
    data_end = None
    labels = {}
    branches = []
    for line_no, line in enumerate(text.splitlines(), 1):
        code = line.split('#', 1)[0].strip()
        if not in_method:
            if code.startswith('.method '):
                in_method = True
                method = code
                data_end = None
                labels = {}
                branches = []
            continue
        if code == '.end method':
            for name, where in labels.items():
                if len(where) > 1:
                    problems.append('%s:%d: %s: label :%s defined %d times'
                                    % (path, where[1], method, name, len(where)))
            for target, where in branches:
                if target not in labels:
                    problems.append('%s:%d: %s: branch to undefined label :%s'
                                    % (path, where, method, target))
            in_method = False
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
        match = LABEL_RE.match(code)
        if match:
            labels.setdefault(match.group(1), []).append(line_no)
            continue
        if code.startswith('.'):
            continue
        parts = code.split()
        opcode = parts[0]
        if opcode.startswith('if-') or opcode in BRANCH_OPS:
            target = parts[-1]
            if target.startswith(':'):
                branches.append((target[1:], line_no))
    return problems


def scan_project(project):
    project = Path(project)
    problems = []
    files = sorted(project.rglob('*.smali'))
    for path in files:
        problems.extend(check_text(path.read_text(errors='replace'),
                                   path.relative_to(project).as_posix()))
    return len(files), problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', nargs='?', type=Path, default=Path('decompiled'))
    args = parser.parse_args()
    files, problems = scan_project(args.project)
    for problem in problems[:200]:
        print(problem)
    if problems:
        print('Found %d label problems in %d Smali files' % (len(problems), files))
        return 1
    print('Checked %d Smali files; no duplicate or dangling labels' % files)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
