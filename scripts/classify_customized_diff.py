#!/usr/bin/env python3
"""Classify the methods of the customised 171 tree that differ from upstream.

The migration coverage names the methods that the 139 -> 171 migration
changed. The customised tree holds more: the Toast rewrite and the Update
Core source-list fix are applied by the port script after the migration, so
they change methods that the coverage does not name. This script groups the
difference by the kind of change so that the port can account for each of
them.
"""
import argparse, collections, difflib, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_173_maps import methods

TOAST_OLD = 'Landroid/widget/Toast;->makeText'
TOAST_NEW = 'Lcom/box/app/vpn/FToast;->makeText'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', type=Path, required=True)
    parser.add_argument('--custom', type=Path, required=True)
    parser.add_argument('--coverage', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=None)
    args = parser.parse_args()

    coverage = json.loads(args.coverage.read_text())
    listed = {item['new'] for item in coverage['completed']}

    groups = collections.defaultdict(list)
    for path in sorted(args.custom.rglob('*.smali')):
        relative = path.relative_to(args.custom)
        original = args.upstream / relative
        if not original.is_file():
            continue
        owner = re.search(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)',
                          path.read_text(errors='replace'), re.M).group(1)
        old_methods = methods(original)
        new_methods = methods(path)
        for signature, block in new_methods.items():
            key = owner + '->' + signature
            other = old_methods.get(signature)
            if other is None:
                groups['added method'].append({'old': key, 'file': relative.as_posix(),
                                              'listed': key in listed})
                continue
            if other == block:
                continue
            diff = [line for line in difflib.unified_diff(
                        other.splitlines(), block.splitlines(), lineterm='', n=0)
                    if line.startswith(('+', '-')) and not line.startswith(('+++', '---'))]
            text = '\n'.join(diff)
            if TOAST_NEW in text and TOAST_OLD in text:
                kind = 'toast rewrite'
            elif 'Lcom/box/app/vpn/VpnPrefs;->items' in text:
                kind = 'settings list'
            elif 'mihomo_dingtalk' in text or 'sing-box_dingtalk' in text:
                kind = 'dingtalk source list'
            elif 'dingtalk_sources_migrated_v1' in text:
                kind = 'dingtalk source migration'
            elif 'sources_v1' in text:
                kind = 'sources preference'
            else:
                kind = 'other'
            groups[kind].append({'old': key, 'file': relative.as_posix(),
                                 'listed': key in listed, 'diff': diff})
    for kind in sorted(groups):
        items = groups[kind]
        extra = [item for item in items if not item['listed']]
        print('%-26s %3d changed (%d not in the coverage)' % (kind, len(items), len(extra)))
        for item in extra:
            print('    ', item['old'])
            for line in item.get('diff', [])[:12]:
                print('        ', line)
    if args.output:
        Path(args.output).write_text(json.dumps(
            {kind: items for kind, items in groups.items()}, indent=1) + '\n')


if __name__ == '__main__':
    main()
