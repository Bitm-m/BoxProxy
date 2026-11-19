#!/usr/bin/env python3
"""Check the dex rule that every move-result* follows its invoke directly.

The dex verifier rejects a method whose ``move-result``/``move-result-wide``/
``move-result-object`` is not the instruction right after the ``invoke-*``
that produced the value.  A text driven port can insert such a pair at the
wrong anchor: the instruction shapes stay identical, so a shape based hunk
verifier does not notice, but ART refuses to load the class.

The checker reports every occurrence in a Smali tree.
"""
import argparse
import re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method.*?^\.end method', re.M | re.S)
MOVE_RESULT_RE = re.compile(r'^\s*move-result(?:-wide|-object)?\b')
INVOKE_RE = re.compile(r'^\s*(invoke-|filled-new-array)')
NOISE_RE = re.compile(r'^\s*(\.line\b|\.local\b|\.end local\b|\.restart local\b|'
                       r'\.param\b|\.end param\b|\.prologue\b|\.source\b)')


def methods(text):
    for match in METHOD_RE.finditer(text):
        block = match.group(0)
        yield block.splitlines()[0].strip(), block.splitlines()


def check_file(path):
    problems = []
    text = path.read_text(errors='replace')
    for header, lines in methods(text):
        previous = None
        for number, line in enumerate(lines, 1):
            code = line.strip()
            if not code or NOISE_RE.match(code):
                continue
            if MOVE_RESULT_RE.match(code):
                if previous is None or not INVOKE_RE.match(previous):
                    problems.append((path, number, header, code, previous))
            previous = code
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path, nargs='?',
                        default=Path('.tools/migrated-176'))
    parser.add_argument('--limit', type=int, default=50)
    args = parser.parse_args()
    problems = []
    files = sorted(args.root.rglob('*.smali'))
    for path in files:
        problems.extend(check_file(path))
    for path, number, header, code, previous in problems[:args.limit]:
        print('%s:%d  %s' % (path, number, header))
        print('    %r' % code)
        print('    previous: %r' % previous)
    print('checked %d files, %d misplaced move-result instructions'
          % (len(files), len(problems)))
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
