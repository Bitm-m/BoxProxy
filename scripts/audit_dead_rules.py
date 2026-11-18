#!/usr/bin/env python3
"""Audit the seven manual rules that the 176 coverage never reaches.

The manual rules in scripts/port_176_candidate.py were copied from
scripts/port_171_stage6_candidate.py, where the coverage keyed the old
reference on the 171 upstream class names (Lqw6, Lbf0, Lhl, Lrx4, Llb1,
Lf55, Liw4).  The 176 coverage keys the old reference on the 171
customized class names instead (Lr57, Lt36, Lk, Lq75, Lpd1, Lne5, Lg65),
so every one of those rules is dead: the prefix never matches and the
generic LCS patcher silently takes over.

This script prints, for each of the seven methods, the customized-171
body, the 176 upstream body and the migrated-176 body so the difference
the dead rule was supposed to introduce can be reviewed by hand.
"""
import json
import re
import sys
from pathlib import Path

CUSTOM = Path('.tools/customized-171/decompiled')
UPSTREAM = Path('.tools/upstream-173/decompiled')
MIGRATED = Path('.tools/migrated-176')
COVERAGE = Path('upstream/26.11.17.73f2816/migration/coverage.json')

# 171 upstream rule key -> (176 coverage old prefix, label)
RULES = [
    ('Lqw6;-><clinit>()V', 'Lr57;-><clinit>()V', 'core registry'),
    ('Lbf0;->m(', 'Lt36;->O(', 'settings list'),
    ('Lhl;->b(', 'Lk;->u(', 'restore menu in k'),
    ('Lrx4;->invoke(', 'Lq75;->invoke(', 'restore menu in q75'),
    ('Llb1;->g(', 'Lpd1;->g(', 'coroutine states'),
    ('Lf55;-><clinit>()V', 'Lne5;-><clinit>()V', 'VPN enum v9'),
    ('Liw4;->invoke(', 'Lg65;->invoke(', 'field h in v10'),
]


def method_blocks(text):
    result = {}
    for match in re.finditer(r'^\.method.*?^\.end method', text, re.M | re.S):
        block = match.group(0)
        result[block.splitlines()[0].strip()] = block
    return result


MODIFIERS = ('public', 'private', 'protected', 'static', 'final', 'synchronized',
             'bridge', 'varargs', 'native', 'abstract', 'strictfp', 'synthetic',
             'constructor')


def load(path):
    """Map signature -> block for every method in the file.

    The signature is the part after '->' in the coverage reference, so the
    access modifiers and the static/synthetic flags have to be stripped
    from the smali method header first.
    """
    result = {}
    for block in method_blocks(Path(path).read_text(errors='replace')).values():
        head = block.splitlines()[0]
        words = head.split()
        while len(words) > 2 and words[1] in MODIFIERS:
            words.pop(1)
        result[' '.join(words[1:])] = block
    return result


def body_of(block):
    lines = block.splitlines()
    return lines[1:-1]


def main():
    coverage = json.loads(COVERAGE.read_text())
    plans = {p['old']: p for p in coverage['completed']}
    custom = {}
    upstream = {}
    migrated = {}
    for old_key, new_prefix, label in RULES:
        plan = next((p for p in coverage['completed'] if p['old'].startswith(new_prefix)), None)
        if plan is None:
            print('### %s: NO COVERAGE ENTRY for %s' % (old_key, new_prefix))
            continue
        new_sig = plan['new'].split('->', 1)[1]
        custom_sig = plan['old'].split('->', 1)[1]
        cb = load(CUSTOM / plan['sourceFile']).get(custom_sig)
        ub = load(UPSTREAM / plan['targetFile']).get(new_sig)
        mb = load(MIGRATED / plan['targetFile']).get(new_sig)
        custom[label] = cb
        upstream[label] = ub
        migrated[label] = mb
        print('=' * 78)
        print('### %-28s dead key %s' % (label, old_key))
        print('### coverage old=%s' % plan['old'])
        print('### coverage new=%s  (%s -> %s)' % (plan['new'], plan['sourceFile'],
                                                    plan['targetFile']))
        for name, block in (('customized-171', cb), ('176 upstream', ub),
                            ('migrated-176', mb)):
            if block is None:
                print('--- %s: MISSING' % name)
                continue
            body = body_of(block)
            print('--- %s (%d lines)' % (name, len(body)))
            if name == 'migrated-176':
                for line in body:
                    print('    ' + line)
            else:
                for line in body:
                    print('    ' + line)
            print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
