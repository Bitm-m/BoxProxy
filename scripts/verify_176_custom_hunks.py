#!/usr/bin/env python3
"""Verify that every 171 customization hunk survived the 171 -> 176 port.

The port applies the difference between the 171 upstream tree and the 171
customized tree onto the 176 upstream tree.  A text/LCS driven patcher can
mis-anchor a hunk, split one hunk into several, or drop it entirely while
still producing a tree that assembles and passes a reference check.

This script therefore compares the *shape* of the change instead of its
position:

*   the canonical instruction sequence of the 171 upstream method,
*   the canonical instruction sequence of the 171 customized method,
*   the canonical instruction sequence of the 176 upstream method,
*   the canonical instruction sequence of the migrated 176 method.

The inserted instructions of ``171 upstream -> 171 customized`` must appear,
in the same order and with the same multiplicity, as the inserted
instructions of ``176 upstream -> migrated 176`` once every type, member and
field reference has been rewritten to the 176 name space.

Canonicalization normalizes every reference to a placeholder and every
register to ``r``, so a hunk only counts as preserved when its instruction
shapes really match.
"""
import argparse
import collections
import difflib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from port_176_candidate import (Mapper, public_map, sig_lines, find_block,
                               check_core_version_rules_whitelist)

ANDROID_TYPES = re.compile(r'^L(?:java|android|kotlin|javax|junit|org/json|org/xml)/')
METHOD_RE = re.compile(r'^\.method.*?^\.end method', re.M | re.S)

# The 176 upstream forces two of the 171 hunks to differ in shape.  Every
# entry documents why the instruction shapes cannot match and names the
# checks that replace the shape comparison for that hunk.
ALLOWED_DIFFERENCES = {
    'Lpd1;->d(Ljava/io/File;Lda1;)Ljava/lang/Object;': {
        'reason': 'the 176 upstream moved the core version probe into the Lxe1 '
                  'coroutine, so the 171 shell hunk has no counterpart to be '
                  'transplanted into; the port reimplements the 171 probe for '
                  '176 and runs it through the 176 shell executor',
        'checks': ['core_version_probe'],
    },
    'Lpd1;->g(Ljava/lang/String;Lda1;)Ljava/lang/Object;': {
        'reason': 'the 176 upstream removed the direct release URL lookup, so '
                  'the port routes the DingTalk release through the 176 '
                  'Lsb1.c(repo, tag, ctx)',
        'checks': ['dingtalk_release_lookup'],
    },
}

# The 171 core version probe script, byte for byte, as the 171 customization
# stores it in the probe string.
CORE_PROBE_MARKERS = (
    'core_path=\\"$core\\"',
    '/storage/emulated/*)',
    '_real_core=\\"/data/media/${core_path#/storage/emulated/}\\"',
    'chmod 755 \\"$_real_core\\"',
    'bpld \\"$(dirname \\"$core_path\\")\\" \\"$_bp_seed\\"',
    'LD_LIBRARY_PATH=\\"$_lp${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}\\"',
    "_version_args='version --version -v'",
    "_version_args='-version version --version -v'",
    "_version_args='--version -v version'",
)

# The 171 archive matcher accepts a "<core>-<suffix>" archive whose payload
# is at least 1 MiB.
ARCHIVE_MATCHER_MARKERS = (
    'invoke-virtual {p1, v6}, Ljava/lang/String;->concat(Ljava/lang/String;)Ljava/lang/String;',
    'invoke-virtual {v3, v6}, Ljava/lang/String;->startsWith(Ljava/lang/String;)Z',
    'const-wide/32 v6, 0x100000',
    'cmp-long v6, v4, v6',
)


def method_text(path, signature):
    block = find_block(path, signature)
    return '' if block is None else block


def require(migrated_text, needles, label, problems, name):
    for needle in needles:
        if needle not in migrated_text:
            problems.append((name, '%s: %r is missing' % (label, needle)))


def forbid(migrated_text, needles, label, problems, name):
    for needle in needles:
        if needle in migrated_text:
            problems.append((name, '%s: %r must not appear' % (label, needle)))


def check_core_version_probe(custom, migrated, problems, name):
    """The 176 core version probe keeps the whole 171 customization."""
    require(migrated, CORE_PROBE_MARKERS, 'probe script', problems, name)
    require(migrated, (
        'invoke-static {p0}, Lcom/box/app/cfg/LdFix;->wrapProbe(Ljava/lang/String;)Ljava/lang/String;',
        'invoke-static {p0}, Lzn6;->d0(Ljava/lang/String;)Ljava/lang/String;',
        'invoke-static {p1, p2, v0, p0}, Lbq5;->f(JLia1;Ljava/lang/String;)Ljava/lang/Object;',
        'check-cast p0, Lsp5;',
    ), 'probe wiring', problems, name)
    forbid(migrated, ('Lxe1;->a(',), 'superseded coroutine probe', problems, name)
    # The probe script itself has to be the one the 171 customization used.
    script = None
    for line in custom.splitlines():
        stripped = line.strip()
        if stripped.startswith('const-string p0, "') and 'core_path=' in stripped:
            script = stripped
            break
    if script is None:
        problems.append((name, 'the 171 customization no longer carries a probe script'))
    elif script not in migrated:
        problems.append((name, 'the 171 probe script was not carried over unchanged'))


def check_dingtalk_release_lookup(custom, migrated, problems, name):
    """The DingTalk release lookup uses the 176 release API."""
    require(migrated, (
        'const-string v0, "jieluojun/mihomo"',
        'const-string v1, "Prerelease-Alpha"',
        'Lsb1;->c(Ljava/lang/String;Ljava/lang/String;Lja1;)Ljava/lang/Object;',
    ), 'release lookup', problems, name)
    forbid(migrated, (
        'https://api.github.com/repos/jieluojun/mihomo/releases/tags/Prerelease-Alpha',
    ), 'removed release URL', problems, name)


ALLOWED_CHECKS = {
    'core_version_probe': check_core_version_probe,
    'dingtalk_release_lookup': check_dingtalk_release_lookup,
}


def canonical(body, resources):
    """Instruction shapes of a method body with all references normalized."""
    result = []
    for _, line, shape in sig_lines(body, resources, 'generic'):
        result.append(shape)
    return result


def inserted_shapes(before, after):
    """Instructions that the change from *before* to *after* introduced."""
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    added = []
    for tag, _, _, j1, j2 in matcher.get_opcodes():
        if tag in ('insert', 'replace'):
            added.extend(after[j1:j2])
    return added


def removed_shapes(before, after):
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    removed = []
    for tag, i1, i2, _, _ in matcher.get_opcodes():
        if tag in ('delete', 'replace'):
            removed.extend(before[i1:i2])
    return removed


def method_body(path, signature):
    block = find_block(path, signature)
    if block is None:
        return None
    return block.splitlines()[1:-1]


def significant(text):
    """Instruction lines of a method without labels and debug directives."""
    result = []
    for line in text.splitlines():
        code = line.strip()
        if not code or code.startswith('.'):
            continue
        result.append(code)
    return result


def check_176_contracts(output, problems):
    """Regression checks for the 176 contracts the port has to preserve."""

    def declared(signature):
        found = []
        for path in output.rglob('*.smali'):
            for match in METHOD_RE.finditer(path.read_text(errors='replace')):
                header = match.group(0).splitlines()[0]
                if signature in header:
                    found.append((path, match.group(0)))
        return found

    def only(signature, label):
        found = declared(signature)
        if len(found) != 1:
            problems.append((label, 'expected exactly one declaration, found %d' % len(found)))
            return None
        return found[0][1]

    def in_file(file_name, signature, label):
        path = output / 'smali' / file_name
        if not path.is_file():
            problems.append((label, 'the owning class %s is missing' % file_name))
            return None
        block = find_block(path, signature)
        if block is None:
            problems.append((label, 'the method %s is missing' % signature))
            return None
        return block

    # The core registry has to keep the nine customized cores in the reviewed
    # order.  A mis-ordered or shortened registry still assembles and still
    # passes the reference check, but it hands the wrong core id to the UI.
    registry = in_file('p77.smali', '<clinit>()V', 'Lp77;-><clinit>()V')
    if registry is not None:
        names = ['mihomo', 'mihomo_smart', 'mihomo_dingtalk', 'sing-box',
                 'sing-box_ref1nd', 'sing-box_dingtalk', 'xray', 'v2fly', 'hysteria']
        ids = ['0384', '0385', '0590', '0386', '0387', '0591', '038a', '0389', '0383']
        for index, name in enumerate(names):
            if 'const-string v%d, "%s"' % (index, name) not in registry:
                problems.append(('Lp77;-><clinit>()V',
                                 'core %s is missing or not at index %d' % (name, index)))
        for index, resource in enumerate(ids, 1):
            if 'const v0, 0x7f0f%s' % resource not in registry:
                problems.append(('Lp77;-><clinit>()V',
                                 'core id 0x7f0f%s is missing or not at index %d'
                                 % (resource, index)))
        require(registry, (
            'filled-new-array/range {v0 .. v8}, [Ljava/lang/String;',
            'filled-new-array/range {v1 .. v9}, [Ljava/lang/Integer;',
            'sput-object v0, Lp77;->a:Ljava/util/List;',
            'sput-object v0, Lp77;->b:Ljava/util/List;',
        ), 'core registry', problems, 'Lp77;-><clinit>()V')
        resources = public_map(output / 'res/values/public.xml')
        for name, resource in zip(names, ids):
            expected = 'string.proxy_core_' + name.replace('-', '_')
            if resources.get('0x7f0f' + resource) != expected:
                problems.append(('Lp77;-><clinit>()V',
                                 '0x7f0f%s does not resolve to %s' % (resource, expected)))

    # The customized VPN enum publishes the new "vpn" constant in its own
    # register and lists it in front of the six upstream constants.
    vpn = in_file('jg5.smali', '<clinit>()V', 'Ljg5;-><clinit>()V')
    if vpn is not None:
        require(vpn, (
            'const-string v9, "vpn"',
            'const-string v8, "Vpn"',
            'invoke-direct {v6, v7, v8, v9}, Ljg5;-><init>(ILjava/lang/String;Ljava/lang/String;)V',
            'sput-object v6, Ljg5;->t:Ljg5;',
            'const/4 v7, 0x7',
            'new-array v7, v7, [Ljg5;',
            'aput-object v6, v7, v8',
            'aput-object v0, v7, v8',
            'aput-object v5, v7, v8',
        ), 'vpn enum', problems, 'Ljg5;-><clinit>()V')
        forbid(vpn, ('const-string v6, "vpn"',), 'vpn enum', problems, 'Ljg5;-><clinit>()V')
        if '.locals 10' not in vpn:
            problems.append(('Ljg5;-><clinit>()V',
                             'the vpn constant needs a tenth local register'))
        field = output / 'smali' / 'jg5.smali'
        if '.field public static final enum t:Ljg5;' not in field.read_text(errors='replace'):
            problems.append(('Ljg5;->t:Ljg5;',
                             'the vpn constant is not published through the static field t'))

    # The settings list localizes the hidden-entry label before the item
    # object is created; the label lookup must not overwrite that object.
    settings = in_file('ub3.smali',
                       'U(ZZZZLla5;ZZZZLqa2;Lqa2;Lqa2;Lqa2;Lqa2;Lqa2;Lqa2;Lqa2;Lfa2;Lub2;)Ljava/util/List;',
                       'Lub3;->U(...)')
    if settings is not None:
        lines = significant(settings)
        label = [i for i, line in enumerate(lines)
                 if 'Lcom/box/app/vpn/VpnPrefs;->items(' in line]
        item = [i for i, line in enumerate(lines) if line == 'new-instance v1, Lgt1;']
        if len(label) != 1 or len(item) != 1:
            problems.append(('Lub3;->U(...)',
                             'expected exactly one VpnPrefs.items call and one item instance'))
        elif not label[0] < item[0]:
            problems.append(('Lub3;->U(...)',
                             'the localized label lookup overwrites the settings item object'))
        else:
            window = lines[max(0, label[0] - 4):item[0]]
            if not any(line.startswith('const v1, 0x7f0f') for line in window):
                problems.append(('Lub3;->U(...)',
                                 'the localized label id is not loaded before the lookup'))

    # The core path is read into v10, which is the register the 176 call
    # expects; a wider register does not assemble.
    core_path = in_file('f85.smali', 'invoke(Ljava/lang/Object;)Ljava/lang/Object;',
                        'Lf85;->invoke(...)')
    if core_path is not None:
        require(core_path, ('iget-object v10, v2, Lhc0;->h:Ljava/lang/String;',),
                'core path', problems, 'Lf85;->invoke(...)')
        forbid(core_path, ('const-string v10, ""', 'iget-object v27, v2,'),
                'core path', problems, 'Lf85;->invoke(...)')
        if '.locals 27' not in core_path:
            problems.append(('Lf85;->invoke(...)', 'the register frame changed'))

    # The core detail probe keeps its 176 signature and its 176 call sites.
    probes = declared('e(Ljava/io/File;Lja1;)Ljava/lang/Object;')
    if len(probes) != 1:
        problems.append(('Loe1;->e(Ljava/io/File;Lja1;)Ljava/lang/Object;',
                         'expected exactly one declaration, found %d' % len(probes)))
    else:
        path, block = probes[0]
        if path.name != 'oe1.smali':
            problems.append(('Loe1;->e(Ljava/io/File;Lja1;)Ljava/lang/Object;',
                             'unexpected owner file %s' % path.name))
        if 'instance-of v0, p2, Lke1;' not in block:
            problems.append(('Loe1;->e(Ljava/io/File;Lja1;)Ljava/lang/Object;',
                             'the coroutine state check is gone'))
        if 'invoke-direct {v0, p0, p2}, Lke1;-><init>(Loe1;Lja1;)V' not in block:
            problems.append(('Loe1;->e(Ljava/io/File;Lja1;)Ljava/lang/Object;',
                             'the 176 continuation contract is broken'))
        callers = []
        for other in output.rglob('*.smali'):
            text = other.read_text(errors='replace')
            if 'Loe1;->e(Ljava/io/File;Lja1;)Ljava/lang/Object;' in text:
                callers.append(other.name)
        for expected in ('ke1.smali', 'oe1.smali'):
            if expected not in callers:
                problems.append(('Loe1;->e(Ljava/io/File;Lja1;)Ljava/lang/Object;',
                                 'the 176 call site %s is gone' % expected))

    # The 176 version probe coroutine keeps its signature and its own call.
    versions = declared('a(Ljava/lang/String;Ljava/lang/String;Lio;Lja1;)Ljava/lang/Object;')
    if len(versions) != 1:
        problems.append(('Lxe1;->a(Ljava/lang/String;Ljava/lang/String;Lio;Lja1;)Ljava/lang/Object;',
                         'expected exactly one declaration, found %d' % len(versions)))
    else:
        path, _ = versions[0]
        if path.name != 'xe1.smali':
            problems.append(('Lxe1;->a(Ljava/lang/String;Ljava/lang/String;Lio;Lja1;)Ljava/lang/Object;',
                             'unexpected owner file %s' % path.name))
        called = False
        for other in output.rglob('*.smali'):
            if 'Lxe1;->a(Ljava/lang/String;Ljava/lang/String;Lio;Lja1;)Ljava/lang/Object;' \
                    in other.read_text(errors='replace'):
                called = True
        if not called:
            problems.append(('Lxe1;->a(Ljava/lang/String;Ljava/lang/String;Lio;Lja1;)Ljava/lang/Object;',
                             'the 176 coroutine is no longer called'))

    # The archive matcher keeps the 171 prefix and payload rules.
    matchers = declared('n(Ljava/io/InputStream;Ljava/lang/String;Ljava/io/File;Ljava/lang/Long;Z)V')
    if len(matchers) != 1:
        problems.append(('Lt6;->n(Ljava/io/InputStream;Ljava/lang/String;Ljava/io/File;Ljava/lang/Long;Z)V',
                         'expected exactly one declaration, found %d' % len(matchers)))
    else:
        _, block = matchers[0]
        require(block, ARCHIVE_MATCHER_MARKERS, 'archive matcher', problems,
                'Lt6;->n(Ljava/io/InputStream;Ljava/lang/String;Ljava/io/File;Ljava/lang/Long;Z)V')
        if 'if-eqz v3, :' in block:
            problems.append(('Lt6;->n(Ljava/io/InputStream;Ljava/lang/String;Ljava/io/File;Ljava/lang/Long;Z)V',
                             'the 176 exact name comparison is still in front of the matcher'))

    # The core version rule resolver has to accept the reviewed DingTalk
    # repositories: without them both DingTalk sources fall back to the
    # unsupported-source rules and lose their version number.
    try:
        check_core_version_rules_whitelist(output)
    except Exception as exc:
        problems.append(('Lt6;->k(Lpe1;)Laf1;',
                         'the core version rule resolver lost the DingTalk repositories: %r'
                         % (exc,)))

    # The root detail probe keeps the wrapped script builder.
    probes = declared('invokeSuspend(Ljava/lang/Object;)Ljava/lang/Object;')
    wrapped = 0
    for path, block in probes:
        lines = significant(block)
        for index, line in enumerate(lines):
            if line != 'invoke-static {v2}, Lzn6;->d0(Ljava/lang/String;)Ljava/lang/String;':
                continue
            following = lines[index + 1:index + 3]
            if following == ['move-result-object v2',
                             'invoke-static {v2}, Lcom/box/app/cfg/LdFix;->wrapProbe(Ljava/lang/String;)Ljava/lang/String;']:
                wrapped += 1
            else:
                problems.append((path.name,
                                 'the LdFix probe wrapper does not consume the script builder result'))
    if wrapped != 1:
        problems.append(('Lyu0;->invokeSuspend(Ljava/lang/Object;)Ljava/lang/Object;',
                         'expected exactly one wrapped probe script, found %d' % wrapped))

    # The external files fallback branch has to build the base directory on
    # both of its paths.  The 176 port once advanced the
    # :cond_external_files_ready label behind the const-string / new-instance
    # pair, so the non-null path jumped straight to File.<init> with an
    # undefined v1 and the ART verifier rejected the class with a VerifyError
    # during AppApplication.onCreate.  The label must stay in front of the
    # literal and the allocation, and the null path must keep falling through
    # the getFilesDir fallback.
    external = in_file('uc0.smali', 'k()Ljc0;', 'Luc0;->k()')
    if external is not None:
        lines = significant(external)
        anchors = {
            'branch': 'if-nez v0, :cond_external_files_ready',
            'label': ':cond_external_files_ready',
            'fallback': 'invoke-virtual {v0}, Landroid/content/Context;'
                        '->getFilesDir()Ljava/io/File;',
            'literal': 'const-string v2, "box"',
            'allocate': 'new-instance v1, Ljava/io/File;',
            'construct': 'invoke-direct {v1, v0, v2}, Ljava/io/File;'
                         '-><init>(Ljava/io/File;Ljava/lang/String;)V',
        }
        positions = {}
        for name, needle in anchors.items():
            hits = [i for i, line in enumerate(lines) if line == needle]
            if len(hits) != 1:
                problems.append(('Luc0;->k()',
                                 '%s appears %d times, expected exactly once'
                                 % (needle, len(hits))))
            else:
                positions[name] = hits[0]
        if len(positions) == len(anchors):
            # Non-null path: the branch jumps straight to the label, so the
            # label has to dominate the literal and the allocation.
            for name in ('literal', 'allocate'):
                if not positions['branch'] < positions['label'] < positions[name]:
                    problems.append(('Luc0;->k()',
                                     'the external files branch skips the %s; the '
                                     'label must precede it' % name))
            # Null path: the branch falls through the getFilesDir fallback
            # before reaching the same label.
            if not (positions['branch'] < positions['fallback']
                    < positions['label']):
                problems.append(('Luc0;->k()',
                                 'the getFilesDir fallback must sit between the '
                                 'branch and the label'))
            for name in ('literal', 'allocate'):
                if positions[name] >= positions['construct']:
                    problems.append(('Luc0;->k()',
                                     'File.<init> runs before the %s' % name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, default=Path('.tools/cmp/decompiled'))
    parser.add_argument('--new', type=Path, default=Path('.tools/upstream-173/decompiled'))
    parser.add_argument('--custom', type=Path, default=Path('.tools/customized-171/decompiled'))
    parser.add_argument('--output', type=Path, default=Path('.tools/migrated-176'))
    parser.add_argument('--coverage', type=Path,
                        default=Path('upstream/26.11.17.73f2816/migration/coverage.json'))
    parser.add_argument('--maps', type=Path, default=Path('.tools/resolved-maps-173-reviewed.json'))
    args = parser.parse_args()

    maps = json.loads(args.maps.read_text())
    coverage = json.loads(args.coverage.read_text())
    r_old = public_map(args.old / 'res/values/public.xml')
    r_custom = public_map(args.custom / 'res/values/public.xml')
    r_new = public_map(args.new / 'res/values/public.xml')
    r_migrated = public_map(args.output / 'res/values/public.xml')

    problems = []
    checked = 0
    for plan in coverage['completed']:
        old_sig = plan['old'].split('->', 1)[1]
        new_sig = plan['new'].split('->', 1)[1]
        base = method_body(args.old / plan['sourceFile'], old_sig)
        custom = method_body(args.custom / plan['sourceFile'], old_sig)
        target = method_body(args.new / plan['targetFile'], new_sig)
        migrated = method_body(args.output / plan['targetFile'], new_sig)
        if None in (base, custom, target, migrated):
            problems.append((plan['old'], 'method block missing'))
            continue
        checked += 1

        allowed = ALLOWED_DIFFERENCES.get(plan['old'])
        if allowed:
            custom_text = method_text(args.custom / plan['sourceFile'], old_sig)
            migrated_text = method_text(args.output / plan['targetFile'], new_sig)
            for check in allowed['checks']:
                ALLOWED_CHECKS[check](custom_text, migrated_text, problems, plan['old'])
            continue

        base_shapes = canonical(base, r_old)
        custom_shapes = canonical(custom, r_custom)
        target_shapes = canonical(target, r_new)
        migrated_shapes = canonical(migrated, r_migrated)

        expected_added = collections.Counter(inserted_shapes(base_shapes, custom_shapes))
        actual_added = collections.Counter(inserted_shapes(target_shapes, migrated_shapes))
        expected_removed = collections.Counter(removed_shapes(base_shapes, custom_shapes))
        actual_removed = collections.Counter(removed_shapes(target_shapes, migrated_shapes))

        missing = expected_added - actual_added
        extra = actual_added - expected_added
        lost = expected_removed - actual_removed
        spurious = actual_removed - expected_removed
        if missing or extra or lost or spurious:
            report = {
                'old': plan['old'],
                'new': plan['new'],
                'missing': dict(missing),
                'extra': dict(extra),
                'lost': dict(lost),
                'spurious': dict(spurious),
            }
            problems.append((plan['old'], report))

    print('checked %d of %d coverage entries' % (checked, len(coverage['completed'])))
    check_176_contracts(args.output, problems)
    for name, detail in problems:
        print('MISMATCH', name)
        if isinstance(detail, dict):
            for key in ('missing', 'extra', 'lost', 'spurious'):
                if detail[key]:
                    print('   %-9s %s' % (key, json.dumps(detail[key], ensure_ascii=False)))
        else:
            print('   ', detail)
    print('mismatches: %d' % len(problems))
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
