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
from port_194_candidate import (Mapper, public_map, sig_lines, find_block,
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
    'Leu0;->a(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;': {
        'reason': 'the 176 upstream dropped the171 case3 auto-start service '
                  'page from this compose factory and moved the page into its '
                  'own wq4 class, so the customized battery row cannot be '
                  'inserted into iu0.a at all; the port relocates the row '
                  'into wq4.a (checked by check_176_contracts) and this check '
                  'only proves that iu0.a carries no residue of it',
        'checks': ['battery_row_relocated_out_of_iu0'],
    },
    'Luu0;->invokeSuspend(Ljava/lang/Object;)Ljava/lang/Object;': {
        'reason': 'the 171 dynamic core install bypassed the generic updater '
                  'entry filter (the pd1 branch went straight to the '
                  'prefix-tolerant r6.l extractor), so the reviewed 171 diff '
                  'carries no counterpart for relaxing the 176 filter; the '
                  'port adds a "<core>-<suffix>" fallback to the j-blank '
                  'branch of the 176 entry filter because the jieluojun '
                  'sing-box tarballs store the binary under its full release '
                  'name',
        'checks': ['entry_filter_prefix'],
    },
    'Lqc0;->k()Lfc0;': {
        'reason': 'the reviewed 171 diff replaced the private getFilesDir '
                  'base with an unconditional Android/data external base, but '
                  'the reviewed final decision keeps the private files '
                  'directory for BOTH modes: a granted root always used it '
                  '(the stock BoxProxy layout) and the no-root mode moves '
                  'off Android/data onto the same private tree, so the port '
                  'drops the external-first transplant entirely and keeps '
                  'the stock target head; the custom and migrated shapes '
                  'cannot match because the custom carries the external arm '
                  'the migrated method must not have',
        'checks': ['private_working_directory'],
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
        'invoke-static {p0}, Lcn6;->m0(Ljava/lang/String;)Ljava/lang/String;',
        'invoke-static {p1, p2, v0, p0}, Lto5;->f(JLea1;Ljava/lang/String;)Ljava/lang/Object;',
        'check-cast p0, Lko5;',
    ), 'probe wiring', problems, name)
    # In 194 the stock ke1.d legitimately calls the te1 version coroutine,
    # so there is no superseded host reference to forbid here.
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
        'Lrb1;->c(Ljava/lang/String;Ljava/lang/String;Lfa1;)Ljava/lang/Object;',
    ), 'release lookup', problems, name)
    forbid(migrated, (
        'https://api.github.com/repos/jieluojun/mihomo/releases/tags/Prerelease-Alpha',
    ), 'removed release URL', problems, name)


def check_entry_filter_prefix(custom, migrated, problems, name):
    """The j-blank entry filter falls back to "<core>-<suffix>" prefixes.

    The jieluojun sing-box tarballs store the binary under its full release
    name ("sing-box-<version>-android-arm64-v8a-ebpf"), so an exact basename
    comparison never matches; the filter must keep the exact check first and
    then accept a "<core>-" prefixed basename, mirroring the 171 archive
    matcher.  The probe wrapper in the same method is asserted by
    check_176_contracts.
    """
    require(migrated, (
        'invoke-virtual {v14, v9}, Ljava/lang/Object;->equals(Ljava/lang/Object;)Z',
        'move-result v10',
        'if-nez v10, :boxproxy_entry_match',
        'const-string v10, "-"',
        'invoke-virtual {v9, v10}, Ljava/lang/String;->concat(Ljava/lang/String;)Ljava/lang/String;',
        'move-result-object v10',
        'invoke-virtual {v14, v10}, Ljava/lang/String;->startsWith(Ljava/lang/String;)Z',
        'if-eqz v10, :cond_47',
        ':boxproxy_entry_match',
    ), 'entry filter prefix fallback', problems, name)
    # The exact comparison has to stay the first guard: the prefix path may
    # only run when the basename is not already equal to the core name.
    exact = migrated.find(
        'invoke-virtual {v14, v9}, Ljava/lang/Object;->equals(Ljava/lang/Object;)Z')
    fallback = migrated.find('if-nez v10, :boxproxy_entry_match')
    if not (0 <= exact < fallback):
        problems.append((name,
                         'entry filter prefix fallback: the exact basename '
                         'comparison no longer guards the prefix path'))


def check_private_working_directory(custom, migrated, problems, name):
    """uc0.k builds the box/ tree from the private files dir in both modes.

    The reviewed decision keeps the stock BoxProxy base: root and no-root
    alike run from getFilesDir() (box.db via jb0.a, bin/run/state,
    boxctl/boxbpf all derive from this one builder), and nothing in the
    method may reach for the Android/data external directory or for the
    discarded sticky decision (uc0.g/uc0.h, the box_dir preferences, the
    PATH su scan) again.
    """
    for forbidden in ('getExternalFilesDir', 'box_dir', '"PATH"',
                      'Lvc0;->g:Z', 'Lvc0;->h:Z', ':box_dir_'):
        if forbidden in migrated:
            problems.append((name,
                             'private working directory: %r must not appear '
                             'in vc0.k' % forbidden))
    match = re.search(r'\.method public static k\(\)Llc0;\n(.*?)\.end method',
                      migrated, re.S)
    if not match:
        problems.append((name, 'private working directory: vc0.k() is missing'))
        return
    block = match.group(1)
    required = (
        'invoke-virtual {v0}, Landroid/content/Context;->getFilesDir()Ljava/io/File;',
        'const-string v2, "box"',
        'new-instance v1, Ljava/io/File;',
        'invoke-direct {v1, v0, v2}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V',
    )
    for needle in required:
        if needle not in block:
            problems.append((name,
                             'private working directory: %r is missing from '
                             'vc0.k' % needle))
    # The historic VerifyError guard still applies to the straight-line
    # stock head: v1 is allocated first, the base is resolved before the
    # literal, and File.<init> runs last with registers both already held.
    body_lines = [line.strip() for line in block.splitlines()]
    order = [
        'new-instance v1, Ljava/io/File;',
        'invoke-virtual {v0}, Landroid/content/Context;->getFilesDir()Ljava/io/File;',
        'const-string v2, "box"',
        'invoke-direct {v1, v0, v2}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V',
    ]
    positions = []
    for needle in order:
        hits = [i for i, line in enumerate(body_lines) if line == needle]
        if not hits:
            return  # already reported as missing above
        positions.append(hits[0])
    if positions != sorted(positions):
        problems.append((name,
                         'private working directory: the allocation, the '
                         'stock base, the literal and File.<init> are out '
                         'of order: %r' % positions))
    if body_lines.count(order[1]) != 1:
        problems.append((name,
                         'private working directory: expected exactly one '
                         'getFilesDir base in vc0.k'))


def check_battery_row_relocated_out_of_iu0(custom, migrated, problems, name):
    """The171 battery row belongs to the page iu0.a no longer hosts.

    ``custom`` is the customized 171 eu0.a, ``migrated`` the migrated iu0.a.
    The row itself is asserted inside wq4.a by ``check_176_contracts``; here
    only the absence from iu0.a is proven, so a future regression that
    re-runs the generic delta against iu0.a fails even if the wq4 row is
    still present.
    """
    require(custom, ('BattToggle', 'VpnPrefs;->battOn()Z'),
            '171 battery row', problems, name)
    forbid(migrated, ('BattToggle', '0x13f2fb70', 'VpnPrefs;->battOn()Z'),
           'relocated battery row residue', problems, name)


ALLOWED_CHECKS = {
    'core_version_probe': check_core_version_probe,
    'dingtalk_release_lookup': check_dingtalk_release_lookup,
    'battery_row_relocated_out_of_iu0': check_battery_row_relocated_out_of_iu0,
    'entry_filter_prefix': check_entry_filter_prefix,
    'private_working_directory': check_private_working_directory,
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
    registry = in_file('c67.smali', '<clinit>()V', 'Lc67;-><clinit>()V')
    if registry is not None:
        names = ['mihomo', 'mihomo_smart', 'mihomo_dingtalk', 'sing-box',
                 'sing-box_ref1nd', 'sing-box_dingtalk', 'xray', 'v2fly', 'hysteria']
        ids = ['0384', '0385', '0590', '0386', '0387', '0591', '038a', '0389', '0383']
        for index, name in enumerate(names):
            if 'const-string v%d, "%s"' % (index, name) not in registry:
                problems.append(('Lc67;-><clinit>()V',
                                 'core %s is missing or not at index %d' % (name, index)))
        require(registry, (
            'filled-new-array/range {v0 .. v8}, [Ljava/lang/String;',
            'filled-new-array/range {v1 .. v9}, [Ljava/lang/Integer;',
            'sput-object v0, Lc67;->a:Ljava/util/List;',
            'sput-object v0, Lc67;->b:Ljava/util/List;',
        ), 'core registry', problems, 'Lc67;-><clinit>()V')
        resources = public_map(output / 'res/values/public.xml')
        id_by_name = {value: key for key, value in resources.items()}
        for name in names:
            expected = 'string.proxy_core_' + name.replace('-', '_')
            resource = id_by_name.get(expected)
            if resource is None:
                problems.append(('Lc67;-><clinit>()V',
                                 '%s does not resolve in public.xml' % expected))
            elif 'const v0, %s' % resource not in registry:
                problems.append(('Lc67;-><clinit>()V',
                                 'core id %s for %s is missing from the registry'
                                 % (resource, name)))

    # The customized VPN enum publishes the new "vpn" constant in its own
    # register and lists it in front of the six upstream constants.
    vpn = in_file('ef5.smali', '<clinit>()V', 'Lef5;-><clinit>()V')
    if vpn is not None:
        require(vpn, (
            'const-string v9, "vpn"',
            'const-string v8, "Vpn"',
            'invoke-direct {v6, v7, v8, v9}, Lef5;-><init>(ILjava/lang/String;Ljava/lang/String;)V',
            'sput-object v6, Lef5;->t:Lef5;',
            'const/4 v7, 0x7',
            'new-array v7, v7, [Lef5;',
            'aput-object v6, v7, v8',
            'aput-object v0, v7, v8',
            'aput-object v5, v7, v8',
        ), 'vpn enum', problems, 'Lef5;-><clinit>()V')
        forbid(vpn, ('const-string v6, "vpn"',), 'vpn enum', problems, 'Lef5;-><clinit>()V')
        if '.locals 10' not in vpn:
            problems.append(('Lef5;-><clinit>()V',
                             'the vpn constant needs a tenth local register'))
        field = output / 'smali' / 'ef5.smali'
        if '.field public static final enum t:Lef5;' not in field.read_text(errors='replace'):
            problems.append(('Lef5;->t:Lef5;',
                             'the vpn constant is not published through the static field t'))

    # The settings list localizes the hidden-entry label before the item
    # object is created; the label lookup must not overwrite that object.
    settings = in_file('cc3.smali',
                       'R(ZZZZLg95;ZZZZLfa2;Lfa2;Lfa2;Lfa2;Lfa2;Lfa2;Lfa2;Lfa2;Lu92;Lib2;)Ljava/util/List;',
                       'Lcc3;->R(...)')
    if settings is not None:
        lines = significant(settings)
        label = [i for i, line in enumerate(lines)
                 if 'Lcom/box/app/vpn/VpnPrefs;->items(' in line]
        item = [i for i, line in enumerate(lines) if line == 'new-instance v1, Lvs1;']
        if len(label) != 1 or len(item) != 1:
            problems.append(('Lcc3;->R(...)',
                             'expected exactly one VpnPrefs.items call and one item instance'))
        elif not label[0] < item[0]:
            problems.append(('Lcc3;->R(...)',
                             'the localized label lookup overwrites the settings item object'))
        else:
            window = lines[max(0, label[0] - 4):item[0]]
            if not any(line.startswith('const v1, 0x7f0f') for line in window):
                problems.append(('Lcc3;->R(...)',
                                 'the localized label id is not loaded before the lookup'))

    # The core path is read into v10, which is the register the 176 call
    # expects; a wider register does not assemble.
    core_path = in_file('a75.smali', 'invoke(Ljava/lang/Object;)Ljava/lang/Object;',
                        'La75;->invoke(...)')
    if core_path is not None:
        require(core_path, ('iget-object v10, v2, Ljc0;->h:Ljava/lang/String;',),
                'core path', problems, 'La75;->invoke(...)')
        forbid(core_path, ('const-string v10, ""', 'iget-object v27, v2,'),
                'core path', problems, 'La75;->invoke(...)')
        if '.locals 27' not in core_path:
            problems.append(('La75;->invoke(...)', 'the register frame changed'))

    # The core detail probe keeps its 176 signature and its 176 call sites.
    probes = declared('d(Ljava/io/File;Lfa1;)Ljava/lang/Object;')
    if len(probes) != 1:
        problems.append(('Lke1;->d(Ljava/io/File;Lfa1;)Ljava/lang/Object;',
                         'expected exactly one declaration, found %d' % len(probes)))
    else:
        path, block = probes[0]
        if path.name != 'ke1.smali':
            problems.append(('Lke1;->d(Ljava/io/File;Lfa1;)Ljava/lang/Object;',
                             'unexpected owner file %s' % path.name))
        if 'instance-of v0, p2, Lge1;' not in block:
            problems.append(('Lke1;->d(Ljava/io/File;Lfa1;)Ljava/lang/Object;',
                             'the coroutine state check is gone'))
        if 'invoke-direct {v0, p0, p2}, Lge1;-><init>(Lke1;Lfa1;)V' not in block:
            problems.append(('Lke1;->d(Ljava/io/File;Lfa1;)Ljava/lang/Object;',
                             'the 194 continuation contract is broken'))
        callers = []
        for other in output.rglob('*.smali'):
            text = other.read_text(errors='replace')
            if 'Lke1;->d(Ljava/io/File;Lfa1;)Ljava/lang/Object;' in text:
                callers.append(other.name)
        for expected in ('ge1.smali', 'ke1.smali'):
            if expected not in callers:
                problems.append(('Lke1;->d(Ljava/io/File;Lfa1;)Ljava/lang/Object;',
                                 'the 194 call site %s is gone' % expected))

    # The 176 version probe coroutine keeps its signature and its own call.
    versions = declared('a(Ljava/lang/String;Ljava/lang/String;Lgo;Lfa1;)Ljava/lang/Object;')
    if len(versions) != 1:
        problems.append(('Lte1;->a(Ljava/lang/String;Ljava/lang/String;Lgo;Lfa1;)Ljava/lang/Object;',
                         'expected exactly one declaration, found %d' % len(versions)))
    else:
        path, _ = versions[0]
        if path.name != 'te1.smali':
            problems.append(('Lte1;->a(Ljava/lang/String;Ljava/lang/String;Lgo;Lfa1;)Ljava/lang/Object;',
                             'unexpected owner file %s' % path.name))
        called = False
        for other in output.rglob('*.smali'):
            if 'Lte1;->a(Ljava/lang/String;Ljava/lang/String;Lgo;Lfa1;)Ljava/lang/Object;' \
                    in other.read_text(errors='replace'):
                called = True
        if not called:
            problems.append(('Lte1;->a(Ljava/lang/String;Ljava/lang/String;Lgo;Lfa1;)Ljava/lang/Object;',
                             'the 194 coroutine is no longer called'))

    # The archive matcher keeps the 171 prefix and payload rules.
    matchers = declared('p(Ljava/io/InputStream;Ljava/lang/String;Ljava/io/File;Ljava/lang/Long;Z)V')
    if len(matchers) != 1:
        problems.append(('Lu6;->p(Ljava/io/InputStream;Ljava/lang/String;Ljava/io/File;Ljava/lang/Long;Z)V',
                         'expected exactly one declaration, found %d' % len(matchers)))
    else:
        _, block = matchers[0]
        require(block, ARCHIVE_MATCHER_MARKERS, 'archive matcher', problems,
                'Lu6;->p(Ljava/io/InputStream;Ljava/lang/String;Ljava/io/File;Ljava/lang/Long;Z)V')
        if 'if-eqz v3, :' in block:
            problems.append(('Lu6;->p(Ljava/io/InputStream;Ljava/lang/String;Ljava/io/File;Ljava/lang/Long;Z)V',
                             'the exact name comparison is still in front of the matcher'))

    # The core version rule resolver has to accept the reviewed DingTalk
    # repositories: without them both DingTalk sources fall back to the
    # unsupported-source rules and lose their version number.
    try:
        check_core_version_rules_whitelist(output)
    except Exception as exc:
        problems.append(('Lmm0;->H(Lle1;)Lwe1;',
                         'the core version rule resolver lost the DingTalk repositories: %r'
                         % (exc,)))

    # The root detail probe keeps the wrapped script builder.
    probes = declared('invokeSuspend(Ljava/lang/Object;)Ljava/lang/Object;')
    wrapped = 0
    for path, block in probes:
        lines = significant(block)
        for index, line in enumerate(lines):
            if line != 'invoke-static {v2}, Lcn6;->m0(Ljava/lang/String;)Ljava/lang/String;':
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

    # The working directory stays the private files dir in both modes, and
    # the straight-line stock head has to keep the historic VerifyError
    # guard: the base is resolved before the const-string / new-instance
    # pair, so no path reaches File.<init> with an undefined v1.  Nothing
    # may reintroduce the Android/data arm or the discarded sticky
    # decision (uc0.g/uc0.h, the box_dir preferences, the PATH su scan).
    external = in_file('vc0.smali', 'k()Llc0;', 'Lvc0;->k()')
    if external is not None:
        uc0_text = (output / 'smali/vc0.smali').read_text(errors='replace')
        for residue in ('.field public static volatile g:Z',
                        '.field public static volatile h:Z'):
            if residue in uc0_text:
                problems.append(('Lvc0;->k()',
                                 'the discarded sticky decision field %r is '
                                 'still declared on vc0' % residue))
        for residue in ('getExternalFilesDir', 'box_dir', '"PATH"',
                        'Lvc0;->g:Z', 'Lvc0;->h:Z', ':box_dir_'):
            if residue in external:
                problems.append(('Lvc0;->k()',
                                 'the working directory head still carries %r'
                                 % residue))
        lines = significant(external)
        anchors = {
            'base': 'invoke-virtual {v0}, Landroid/content/Context;'
                    '->getFilesDir()Ljava/io/File;',
            'literal': 'const-string v2, "box"',
            'allocate': 'new-instance v1, Ljava/io/File;',
            'construct': 'invoke-direct {v1, v0, v2}, Ljava/io/File;'
                         '-><init>(Ljava/io/File;Ljava/lang/String;)V',
        }
        positions = {}
        for anchor_name, needle in anchors.items():
            hits = [i for i, line in enumerate(lines) if line == needle]
            if len(hits) != 1:
                problems.append(('Lvc0;->k()',
                                 '%s appears %d times, expected exactly once'
                                 % (needle, len(hits))))
            else:
                positions[anchor_name] = hits[0]
        wanted = ['allocate', 'base', 'literal', 'construct']
        if all(anchor_name in positions for anchor_name in wanted):
            sequence = [positions[anchor_name] for anchor_name in wanted]
            if sequence != sorted(sequence):
                problems.append(('Lvc0;->k()',
                                 'the allocation, the private base, the '
                                 'literal and File.<init> are out of '
                                 'order: %r' % list(zip(wanted, sequence))))

    # The customized "unrestricted battery" row moved with its host page: the
    # 176 upstream dropped the171 case3 auto-start service page from the iu0
    # factory and rebuilt that page as wq4.a, so the row has to live in wq4.a
    # between the auto-start row and the accelerated download row, spelled in
    # wq4's own register allocation (state v4, flag v3, row object v15, dead
    # temporaries v9 and v16..v25).  A generic re-run of the delta would put
    # the row back into iu0.a where v7 holds a boolean, which the verifier
    # rejects as a non-reference register.
    iu0_row = in_file('ut0.smali',
                      'a(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;',
                      'Lut0;->a(...)')
    if iu0_row is not None:
        for residue in ('BattToggle', '0x13f2fb70', 'VpnPrefs;->battOn'):
            if residue in iu0_row:
                problems.append(('Lut0;->a(...)',
                                 'the relocated battery row left %r in ut0.a'
                                 % residue))
    wq4_row = in_file('bq4.smali',
                      'a(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;',
                      'Lbq4;->a(...)')
    if wq4_row is not None:
        lines = significant(wq4_row)
        resources = public_map(output / 'res/values/public.xml')
        title_id = {value: key for key, value in resources.items()}.get(
            'string.service_battery_unrestricted_title')
        if title_id is None:
            problems.append(('Lbq4;->a(...)',
                             'the battery title resource is missing from public.xml'))
            title_id = '0x7f0f055b'
        row = [
            'const v9, 0x13f2fb70',
            'invoke-virtual {v4, v9}, Lib2;->g0(I)V',
            'const v9, ' + title_id,
            'invoke-static {v9, v4}, Lya3;->c0(ILib2;)Ljava/lang/String;',
            'move-result-object v35',
            'move-object/from16 v36, v14',
            'invoke-static {}, Lcom/box/app/vpn/BattToggle;->create()'
            'Lcom/box/app/vpn/BattToggle;',
            'move-result-object v34',
            'invoke-static {}, Lcom/box/app/vpn/VpnPrefs;->battOn()Z',
            'move-result v33',
            'const/16 v37, 0x0',
            'const/high16 v39, 0xc00000',
            'move-object/from16 v38, v4',
            'const/16 v40, 0x0',
            'const/16 v41, 0x3f78',
            'invoke-static/range {v33 .. v41}, Lms6;->a(ZLfa2;'
            'Ljava/lang/String;Lyz0;ZLib2;III)V',
            'invoke-virtual {v4, v3}, Lib2;->r(Z)V',
            'const/16 v9, 0xe',
        ]
        anchor = 'const v9, -0x533ee63'
        hits = [i for i, line in enumerate(lines) if line == anchor]
        if len(hits) != 1:
            problems.append(('Lbq4;->a(...)',
                             'battery row anchor %r appears %d times, expected '
                             'exactly once' % (anchor, len(hits))))
        else:
            start = hits[0] - len(row)
            if start < 0 or lines[start:hits[0]] != row:
                problems.append(('Lbq4;->a(...)',
                                 'the battery unrestricted row is not the '
                                 'block directly in front of %r' % anchor))
        if sum(1 for line in lines if 'BattToggle' in line) != 1:
            problems.append(('Lbq4;->a(...)',
                             'BattToggle must appear exactly once in bq4.a'))

    # The VPN modeRes shortcut has to keep the mode result in the register
    # the shared row lookup reads as its third argument (v15), not in the
    # enum register v13: the jump path into :goto_6 must arrive with v13 as
    # the row id, v14 as the flag and v15 as the string resource, and the
    # fall through path has to keep the enum in v13 for the dispatch.
    ra1_mode = in_file('pa1.smali',
                       'a(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;',
                       'Lpa1;->a(...)')
    if ra1_mode is not None:
        lines = significant(ra1_mode)
        shortcut = [
            'check-cast v13, Lef5;',
            'invoke-static {v13}, Lcom/box/app/vpn/VpnBridge;->modeRes(Lef5;)I',
            'move-result v14',
            'if-eqz v14, :cond_pv_novpn',
            'const v13, -0x1c301169',
            'const/4 v15, 0x0',
            'goto :goto_6',
            ':cond_pv_novpn',
        ]
        found = None
        for index in range(len(lines) - len(shortcut) + 1):
            if lines[index:index + len(shortcut)] == shortcut:
                found = index
                break
        if found is None:
            problems.append(('Lpa1;->a(...)',
                             'the modeRes shortcut block is missing or has '
                             'the wrong register layout'))
        for index, line in enumerate(lines):
            if 'VpnBridge;->modeRes' in line and index + 1 < len(lines) \
                    and lines[index + 1] != 'move-result v14':
                problems.append(('Lpa1;->a(...)',
                                 'the modeRes result must land in v14, found '
                                 '%r' % lines[index + 1]))


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
