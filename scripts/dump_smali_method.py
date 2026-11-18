#!/usr/bin/env python3
"""Print a single smali method body by file and signature fragment."""
import re
import sys
from pathlib import Path


def methods(path):
    text = Path(path).read_text(errors='replace')
    out = []
    for m in re.finditer(r'^\.method.*?^\.end method', text, re.M | re.S):
        block = m.group(0)
        out.append((block.splitlines()[0].strip(), block))
    return out


def main():
    path, needle = sys.argv[1], sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10_000
    for head, block in methods(path):
        if needle in head:
            print('###', head)
            for line in block.splitlines()[:limit]:
                print(line)
            print()
            return 0
    print('not found:', needle)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
