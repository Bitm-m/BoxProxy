#!/usr/bin/env python3
"""Recreate the reviewed 139 -> 171 customization in a disposable Apktool tree.

The source project (decompiled/) and pinned upstream trees are never modified.
The mapper input is a separately generated candidate map; output remains a
review artifact until reference, semantic, build, and device checks pass.
"""
import argparse
import collections
import difflib
import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

ANDROID = '{http://schemas.android.com/apk/res/android}'
TYPE_RE = re.compile(r'L[A-Za-z0-9_/$-]+;')
REF_M = re.compile(r'\b(L[A-Za-z0-9_/$-]+;)->([^\s(:]+)(\([^)]*\)\S+)')
REF_F = re.compile(r'\b(L[A-Za-z0-9_/$-]+;)->([^\s:]+):(\S+)')
REF_TOKEN_RE = re.compile(
    r'(?P<method>\bL[A-Za-z0-9_/$-]+;->[^\s(:]+\([^)]*\)\S+)|'
    r'(?P<field>\bL[A-Za-z0-9_/$-]+;->[^\s:]+:\S+)|'
    r'(?P<type>L[A-Za-z0-9_/$-]+;)')
ID_RE = re.compile(r'0x7f[0-9a-f]{6}')
REG_RE = re.compile(r'\b[vp]\d+\b')
LABEL_RE = re.compile(r':\w+')
METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
HEADER_RE = re.compile(r'^\.method\s+.*?([^ ]+\([^\n]*)$')
DEBUG_PREFIXES = ('.line ', '.local ', '.end local ', '.restart local ',
                  '.param ', '.end param ', '.source ', '.prologue')

# Reviewed 139 -> 171 API moves that cannot be inferred safely from obfuscated
# names alone. Lmw is intentionally NOT a global type override: its collection
# adapter remains Lhw, while the path-builder API used by CfgIcon was split into
# Lbx4 in 171 and is corrected only in that custom addition.
MANUAL_TYPE_OVERRIDES = {
    'Lun2;': 'Lcv2;',       # image-vector path model (same constructor and API)
    'Lxm2;': 'Lju2;',       # image-vector composables a/b
    'Lza0;': 'Lfb0;',       # VPN settings singleton became a synthetic lambda name
    'Ljh2;': 'Lvo2;',       # 139 control result; 171 Ljh2 is now an enum
}
MANUAL_FIELD_OVERRIDES = {
    'Lnv;->f:Lv8;': 'Liv;->g:Lq9;',
    'Lza0;->a:Lza0;': 'Lfb0;->a:Lfb0;',
}
MANUAL_MEMBER_OVERRIDES = {
    # 171 changed the URL-download overload from c(url, continuation) to d.
    # The custom 139 caller owns the API as Lca1; its owner maps to 171 Lbb1.
    'Lca1;->c(Ljava/lang/String;Lz81;)Ljava/lang/Object;':
        'Lbb1;->d(Ljava/lang/String;Lda1;)Ljava/lang/Object;',
    'Lbb1;->c(Ljava/lang/String;Lda1;)Ljava/lang/Object;':
        'Lbb1;->d(Ljava/lang/String;Lda1;)Ljava/lang/Object;',
    # The app context moved from dn.K/AppApplication.j to ln.w/AppApplication.i.
    'Ldn;->K()Landroid/content/Context;': 'Lln;->w()Landroid/content/Context;',
    # Settings singleton API changes.
    'Lv8;->u(Landroid/content/Context;)Lnv;': 'Lq9;->o(Landroid/content/Context;)Liv;',
    'Lza0;->o(Lp62;)Ljava/lang/Object;': 'Lfb0;->p(Lh92;)Ljava/lang/Object;',
    # File helper moved its cache-directory getter from l46.c to od6.b.
    'Ll46;->c()Ljava/io/File;': 'Lod6;->b()Ljava/io/File;',
    # 139's Kotlin stream-copy helper Lcs.u collides with unrelated 171 class Lcs;
    # 171 provides the same InputStream.copyTo implementation as Loq.D.
    'Lcs;->u(Ljava/io/InputStream;Ljava/io/OutputStream;)J':
        'Loq;->D(Ljava/io/InputStream;Ljava/io/OutputStream;)J',
    # The Compose function moved and now requires a 171 ComposableLambda wrapper.
    'Lpr;->h(Le62;Lwp3;ZZJFFFLt62;Lz11;II)V':
        'Lhq;->h(Lw82;Lmz3;ZZJFFFLyz0;Lla2;II)V',
}
CFG_ICON_BUILDER_FROM = 'Lhw;'
CFG_ICON_BUILDER_TO = 'Lbx4;'
# CfgNav is custom-only. Use an unused, stable 32-bit Compose group key for its
# icon lambda; validate the pinned 171 factory contract and key uniqueness.
CFG_ICON_LAMBDA_KEY = '0x43464749'  # ASCII "CFGI"


def public_map(path):
    result = {}
    for entry in ET.parse(path).getroot():
        if entry.tag == 'public':
            result[entry.attrib['id']] = entry.attrib['type'] + '.' + entry.attrib['name']
    return result


def class_descriptors(root):
    result = set()
    for path in (root / 'smali').rglob('*.smali'):
        match = re.search(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)',
                          path.read_text(errors='replace'), re.M)
        if match:
            result.add(match.group(1))
    return result


def strip_comment(line):
    quoted = escaped = False
    for i, ch in enumerate(line):
        if ch == '#' and not quoted:
            return line[:i]
        if ch == '"' and not escaped:
            quoted = not quoted
        if ch == '\\' and not escaped:
            escaped = True
        else:
            escaped = False
    return line


def rewrite_unquoted(line, transform):
    out, segment = [], []
    quoted = escaped = False
    for index, ch in enumerate(line):
        if not quoted and ch == '#':
            if segment:
                out.append(transform(''.join(segment)))
                segment = []
            out.append(line[index:])
            return ''.join(out)
        if ch == '"' and not escaped:
            if segment:
                out.append(transform(''.join(segment)))
                segment = []
            out.append(ch)
            quoted = not quoted
        elif quoted:
            out.append(ch)
        else:
            segment.append(ch)
        if ch == '\\' and not escaped:
            escaped = True
        else:
            escaped = False
    if segment:
        out.append(transform(''.join(segment)))
    return ''.join(out)


class Mapper:
    def __init__(self, id_map, maps, old_classes=None, new_classes=None):
        self.id_map = id_map
        self.old_classes = old_classes or set()
        self.new_classes = new_classes or set()
        self.maps = {
            category: {old: item['new'] for old, item in maps.get(category, {}).items()}
            for category in ('types', 'fields', 'members')
        }

    def filter_local(self, local):
        if not local:
            return
        if not self.old_classes or not self.new_classes:
            return
        local['types'] = {old: new for old, new in local.get('types', {}).items()
                          if old in self.old_classes and new in self.new_classes}
        for category in ('members', 'fields'):
            local[category] = {
                old: new for old, new in local.get(category, {}).items()
                if old.split('->', 1)[0] in self.old_classes
                and new.split('->', 1)[0] in self.new_classes
            }

    def line(self, line, local=None):
        local_maps = {category: {} for category in ('types', 'fields', 'members')}
        if local:
            if any(key in local for key in local_maps):
                for category in local_maps:
                    local_maps[category] = local.get(category, {})
            else:
                for old, new in local.items():
                    category = ('types' if '->' not in old else
                                'members' if '(' in old else 'fields')
                    local_maps[category][old] = new

        def mapped_type(match):
            old = match.group(0)
            return self.maps['types'].get(old, local_maps['types'].get(old, old))

        def mapped_member(match, category):
            old = match.group(0)
            replacement = self.maps[category].get(old, local_maps[category].get(old))
            if replacement is not None:
                return replacement
            return TYPE_RE.sub(mapped_type, old)

        def transform(code):
            def replace(match):
                if match.lastgroup == 'method':
                    return mapped_member(match, 'members')
                if match.lastgroup == 'field':
                    return mapped_member(match, 'fields')
                return mapped_type(match)

            if 'L' in code:
                code = REF_TOKEN_RE.sub(replace, code)
            if '0x7f' in code:
                code = ID_RE.sub(lambda match: self.id_map.get(match.group(0), match.group(0)), code)
            return code
        return rewrite_unquoted(line, transform)


def method_blocks(text):
    result = {}
    for match in METHOD_RE.finditer(text):
        block = match.group(0).rstrip()
        header = block.splitlines()[0]
        parsed = HEADER_RE.match(header)
        if parsed:
            result[parsed.group(1)] = block
    return result


def body_of(block):
    return block.splitlines()[1:-1]


def find_block(path, signature):
    return method_blocks(path.read_text(errors='replace')).get(signature)


def nline(line, resources, mode='generic'):
    code = strip_comment(line).strip()
    if (not code or code.startswith(DEBUG_PREFIXES)
            or code.startswith(('.locals ', '.registers ', '.end method'))):
        return ''

    def normalize(segment):
        segment = ID_RE.sub(lambda match: '@' + resources[match.group(0)]
                            if match.group(0) in resources else match.group(0), segment)
        if mode == 'generic':
            segment = REF_M.sub(
                lambda match: 'T;-><init>(ARGS)T' if match.group(2) == '<init>'
                else 'T;->M(ARGS)T', segment)
            segment = REF_F.sub('T;->F:T', segment)
            segment = TYPE_RE.sub('T;', segment)
        segment = REG_RE.sub('r', segment)
        return LABEL_RE.sub(':L', segment)
    return rewrite_unquoted(code, normalize).strip()


def sig_lines(body, resources, mode='generic'):
    result = []
    for index, line in enumerate(body):
        canonical = nline(line, resources, mode)
        if canonical:
            result.append((index, line, canonical))
    return result


def refs(line):
    code = re.sub(r'"(?:[^"\\]|\\.)*"', '""', strip_comment(line))
    result = []
    for match in REF_M.finditer(code):
        result.append(('m', match.group(1) + '->' + match.group(2) + match.group(3)))
    for match in REF_F.finditer(code):
        result.append(('f', match.group(1) + '->' + match.group(2) + ':' + match.group(3)))
    owners = {ref.split('->', 1)[0] for _, ref in result}
    for match in TYPE_RE.finditer(code):
        if match.group(0) not in owners:
            result.append(('t', match.group(0)))
    return result


def build_local(base_body, target_body, r_old, r_new):
    base = sig_lines(base_body, r_old, 'generic')
    target = sig_lines(target_body, r_new, 'generic')
    matcher = difflib.SequenceMatcher(None, [x[2] for x in base],
                                       [x[2] for x in target], autojunk=False)
    index_map, labels = {}, {}
    ref_votes = {name: collections.defaultdict(collections.Counter)
                 for name in ('members', 'fields', 'types')}
    reg_votes = collections.defaultdict(collections.Counter)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            continue
        for offset in range(i2 - i1):
            old_item, new_item = base[i1 + offset], target[j1 + offset]
            index_map[old_item[0]] = new_item[0]
            for (old_kind, old_ref), (new_kind, new_ref) in zip(refs(old_item[1]), refs(new_item[1])):
                if old_kind != new_kind or old_ref == new_ref:
                    continue
                category = {'m': 'members', 'f': 'fields', 't': 'types'}[old_kind]
                if category != 'types' or (old_ref.startswith('L') and new_ref.startswith('L')):
                    ref_votes[category][old_ref][new_ref] += 1
            for old_reg, new_reg in zip(REG_RE.findall(old_item[1]), REG_RE.findall(new_item[1])):
                reg_votes[old_reg][new_reg] += 1
            old_line, new_line = old_item[1].strip(), new_item[1].strip()
            if old_line.startswith(':') and new_line.startswith(':'):
                labels[old_line[1:]] = new_line[1:]
    local = {category: {} for category in ref_votes}
    for category, owners in ref_votes.items():
        for old_ref, counts in owners.items():
            ranked = counts.most_common()
            if ranked and (len(ranked) == 1 or ranked[0][1] > ranked[1][1]):
                local[category][old_ref] = ranked[0][0]
    reg_map = {}
    for old_reg, counts in reg_votes.items():
        ranked = counts.most_common()
        if ranked and (len(ranked) == 1 or ranked[0][1] > ranked[1][1]):
            reg_map[old_reg] = ranked[0][0]
    return local, index_map, labels, base, target, reg_map, matcher.ratio()


def label_maps(base_body, target_body, custom_body, target_labels, old_to_new_labels, resources_old):
    target_names = {line.strip()[1:] for line in target_body if line.strip().startswith(':')}
    custom_names = {line.strip()[1:] for line in custom_body if line.strip().startswith(':')}
    base_lines = sig_lines(base_body, resources_old, 'exact')
    custom_lines = sig_lines(custom_body, resources_old, 'exact')
    matcher = difflib.SequenceMatcher(None, [x[2] for x in base_lines],
                                       [x[2] for x in custom_lines], autojunk=False)
    custom_to_base = {}
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            continue
        for offset in range(min(i2 - i1, j2 - j1)):
            old_line = base_lines[i1 + offset][1].strip()
            custom_line = custom_lines[j1 + offset][1].strip()
            if old_line.startswith(':') and custom_line.startswith(':'):
                custom_to_base[custom_line[1:]] = old_line[1:]
    output, taken = {}, set(target_names)
    for name in custom_names:
        base_name = custom_to_base.get(name, name)
        target = old_to_new_labels.get(base_name, base_name)
        if name in custom_to_base:
            output[name] = target
        elif name in target_names:
            fresh = name + '_custom'
            suffix = 1
            while fresh in taken:
                suffix += 1
                fresh = name + '_custom' + str(suffix)
            taken.add(fresh)
            output[name] = fresh
        else:
            taken.add(name)
            output[name] = name
    return output, custom_to_base


def get_locals(lines):
    for i, line in enumerate(lines):
        match = re.match(r'^\s*\.locals\s+(\d+)', line)
        if match:
            return i, int(match.group(1))
    return None, 0


def parameter_words(header):
    match = re.search(r'\(([^)]*)\)', header)
    if not match:
        return 0
    args = match.group(1)
    words = index = 0
    while index < len(args):
        char = args[index]
        while char == '[':
            index += 1
            char = args[index]
        if char == 'L':
            end = args.find(';', index)
            if end < 0:
                return 0
            index = end + 1
            words += 1
        elif char in 'JD':
            index += 1
            words += 2
        else:
            index += 1
            words += 1
    return words + (0 if ' static ' in header + ' ' else 1)


def dest_reg(line):
    code = line.strip()
    if not code or code.startswith(('#', '.')):
        return None
    op = code.split(None, 1)[0]
    if op.startswith(('move-result', 'move-exception', 'const', 'new-instance', 'new-array',
                       'sget', 'iget', 'aget', 'array-length', 'instance-of', 'cmp', 'add-',
                       'sub-', 'mul-', 'div-', 'rem-', 'and-', 'or-', 'xor-', 'shl-',
                       'shr-', 'ushr-', 'neg-', 'not-', 'rsub-')):
        match = REG_RE.search(code)
        return match.group(0) if match else None
    if op == 'check-cast':
        match = REG_RE.search(code)
        return match.group(0) if match else None
    return None


def advance_chain(lines, position):
    position = max(0, min(position, len(lines)))
    significant = [i for i, line in enumerate(lines)
                   if line.strip() and not line.strip().startswith(DEBUG_PREFIXES)]
    before = [i for i in significant if i < position]
    after = [i for i in significant if i >= position]
    if not before or not after:
        return position
    bi, ai = before[-1], after[0]
    if lines[ai].strip().startswith('move-result') and lines[bi].strip().startswith('invoke-'):
        return (after[1] + 1) if len(after) > 1 else ai + 1
    if (lines[bi].strip().startswith('move-result') and len(before) > 1
            and lines[before[-2]].strip().startswith('invoke-')):
        return after[0] + 1 if after else ai + 1
    return position


def all_range_regs(line):
    code = strip_comment(line)
    if '/range' in code:
        match = re.search(r'\{\s*([vp])(\d+)\s*\.\.\s*([vp])(\d+)\s*\}', code)
        if match and match.group(1) == match.group(3):
            return {match.group(1) + str(i) for i in range(int(match.group(2)), int(match.group(4)) + 1)}
    return set(REG_RE.findall(code))


def replace_block(path, target_sig, new_block):
    text = path.read_text(errors='replace')
    old = method_blocks(text).get(target_sig)
    if not old:
        return False
    if text.count(old) != 1:
        raise ValueError('ambiguous method block ' + target_sig)
    path.write_text(text.replace(old, new_block, 1))
    return True


def patch_method(plan, mapper, old_root, custom_root, out_root, r_old, r_new, audit):
    rel = plan['sourceFile']
    old_sig = plan['old'].split('->', 1)[1]
    target_sig = plan['new'].split('->', 1)[1]
    custom = find_block(custom_root / rel, old_sig)
    base = find_block(old_root / rel, old_sig)
    target = find_block(out_root / plan['targetFile'], target_sig)
    if not (custom and base and target):
        return False, 'method block missing'
    custom_body, base_body, target_body = body_of(custom), body_of(base), body_of(target)

    # Explicit whole initializer for the enlarged core registry: LCS register
    # alignment otherwise drops the extra entries from both range arrays.
    if plan['old'].startswith('Lqw6;-><clinit>()V'):
        entries = [
            ('mihomo', '0x7f0f0306'), ('mihomo_smart', '0x7f0f0307'),
            ('mihomo_dingtalk', '0x7f0f050a'), ('sing-box', '0x7f0f0308'),
            ('sing-box_ref1nd', '0x7f0f0309'), ('sing-box_dingtalk', '0x7f0f050b'),
            ('xray', '0x7f0f030c'), ('v2fly', '0x7f0f030b'), ('hysteria', '0x7f0f0305'),
        ]
        out_ids = public_map(out_root / 'res/values/public.xml')
        ids = []
        for name, old_id in entries:
            new_id = mapper.id_map.get(old_id)
            if ('"' + name + '"') not in custom or new_id is None:
                return False, 'manual core registry source/resource not found: ' + name
            if out_ids.get(new_id) != 'string.proxy_core_' + name.replace('-', '_'):
                return False, 'manual core registry resource mapping mismatch: ' + name
            ids.append(new_id)
        target_class = plan['new'].split('->', 1)[0]
        body = ['    .locals 10', '']
        for reg, (name, _) in enumerate(entries):
            body.append(f'    const-string v{reg}, "{name}"')
        body += [
            '    filled-new-array/range {v0 .. v8}, [Ljava/lang/String;',
            '    move-result-object v0',
            '    invoke-static {v0}, Lkm;->e0([Ljava/lang/Object;)Ljava/util/List;',
            '    move-result-object v0',
            f'    sput-object v0, {target_class}->a:Ljava/util/List;',
        ]
        for reg, resource_id in enumerate(ids, 1):
            body += [
                f'    const v0, {resource_id}',
                '    invoke-static {v0}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;',
                f'    move-result-object v{reg}',
            ]
        body += [
            '    filled-new-array/range {v1 .. v9}, [Ljava/lang/Integer;',
            '    move-result-object v0',
            '    invoke-static {v0}, Lkm;->e0([Ljava/lang/Object;)Ljava/util/List;',
            '    move-result-object v0',
            f'    sput-object v0, {target_class}->b:Ljava/util/List;',
            '    return-void',
        ]
        new_block = target.splitlines()[0] + '\n' + '\n'.join(body) + '\n.end method'
        path = out_root / plan['targetFile']
        if path.read_text(errors='replace').count(target) != 1:
            return False, 'manual core registry target missing or ambiguous'
        path.write_text(path.read_text(errors='replace').replace(target, new_block, 1))
        audit.append({'old': plan['old'], 'new': plan['new'], 'manual': 'nine-entry core registry'})
        return True, {'inserts': len(body), 'deletes': 0, 'unmappedRegisters': [], 'alignment': 1.0}

    local, base_to_target, labelmap, _, _, base_reg_map, alignment = build_local(
        base_body, target_body, r_old, r_new)
    mapper.filter_local(local)
    base_seq = sig_lines(base_body, r_old, 'exact')
    custom_seq = sig_lines(custom_body, r_old, 'exact')
    delta = difflib.SequenceMatcher(None, [x[2] for x in base_seq],
                                    [x[2] for x in custom_seq], autojunk=False)
    custom_votes = collections.defaultdict(collections.Counter)
    for tag, i1, i2, j1, j2 in delta.get_opcodes():
        if tag != 'equal':
            continue
        for offset in range(i2 - i1):
            custom_line, base_line = custom_seq[j1 + offset][1], base_seq[i1 + offset][1]
            for custom_reg, base_reg in zip(REG_RE.findall(custom_line), REG_RE.findall(base_line)):
                custom_votes[custom_reg][base_reg] += 2
    base_generic = sig_lines(base_body, r_old, 'generic')
    custom_generic = sig_lines(custom_body, r_old, 'generic')
    generic_delta = difflib.SequenceMatcher(None, [x[2] for x in base_generic],
                                             [x[2] for x in custom_generic], autojunk=False)
    for tag, i1, i2, j1, j2 in generic_delta.get_opcodes():
        if tag != 'equal':
            continue
        for offset in range(i2 - i1):
            custom_line, base_line = custom_generic[j1 + offset][1], base_generic[i1 + offset][1]
            for custom_reg, base_reg in zip(REG_RE.findall(custom_line), REG_RE.findall(base_line)):
                custom_votes[custom_reg][base_reg] += 1
    reg_map = {}
    for custom_reg, counts in custom_votes.items():
        ranked = counts.most_common()
        if ranked and (len(ranked) == 1 or ranked[0][1] > ranked[1][1]):
            reg_map[custom_reg] = base_reg_map.get(ranked[0][0], ranked[0][0])
    for reg in REG_RE.findall('\n'.join(custom_body)):
        if reg.startswith('p'):
            reg_map.setdefault(reg, reg)

    label_out, _ = label_maps(base_body, target_body, custom_body, base_to_target, labelmap, r_old)
    deletes, inserts = set(), []
    for tag, i1, i2, j1, j2 in delta.get_opcodes():
        if tag == 'equal':
            continue
        if tag in ('delete', 'replace'):
            for seq_i in range(i1, i2):
                old_index = base_seq[seq_i][0]
                if old_index in base_to_target:
                    deletes.add(base_to_target[old_index])
        if tag in ('insert', 'replace'):
            raw = [custom_seq[i][1] for i in range(j1, j2)]
            raw = [line for line in raw if line.strip()
                   and not line.strip().startswith(DEBUG_PREFIXES)
                   and not line.strip().startswith(('.locals ', '.registers '))]
            position = None
            for before_i in range(i1 - 1, -1, -1):
                base_index = base_seq[before_i][0]
                if base_index in base_to_target:
                    position = base_to_target[base_index] + 1
                    break
            if position is None:
                for after_i in range(i1, len(base_seq)):
                    base_index = base_seq[after_i][0]
                    if base_index in base_to_target:
                        position = base_to_target[base_index]
                        break
            if position is None:
                position = next((i for i, line in enumerate(target_body)
                                 if line.strip().startswith('return')), len(target_body))
            position = advance_chain(target_body, position)
            if raw:
                inserts.append((position, raw))

    old_ref = plan['old']
    manual = None
    if old_ref.startswith('Lbf0;->m('):
        if 'VpnPrefs;->items' not in custom:
            return False, 'settings-list delta no longer matches source'
        significant = [i for i, line in enumerate(target_body)
                       if line.strip() and not line.strip().startswith(DEBUG_PREFIXES)
                       and not line.strip().startswith(('.locals ', '.registers '))]
        sequence = [target_body[i].strip() for i in significant]
        anchor = ('invoke-static {v0}, Lkm;->e0([Ljava/lang/Object;)Ljava/util/List;',
                  'move-result-object v0', 'new-instance v1, Lxr1;')
        hits = [k for k in range(len(sequence) - 2) if tuple(sequence[k:k + 3]) == anchor]
        if len(hits) != 1:
            return False, 'settings-list anchor missing or ambiguous'
        pos = significant[hits[0] + 2]
        raw = [
            '    const v1, 0x7f0f0509',
            '    invoke-static {v1, v10}, Lru5;->e0(ILz11;)Ljava/lang/String;',
            '    move-result-object v1',
            '    invoke-static {v0, v1}, Lcom/box/app/vpn/VpnPrefs;->items(Ljava/util/List;Ljava/lang/String;)Ljava/util/List;',
            '    move-result-object v0',
        ]
        inserts, deletes = [(pos, raw)], set()
        reg_map.update({'v0': 'v0', 'v1': 'v1', 'v10': 'v10'})
        manual = 'settings list -> localized label -> VpnPrefs.items -> xr1'
    elif old_ref.startswith('Lhl;->b('):
        anchor = 'filled-new-array {p2, p3, v0}, [Lpv4;'
        hits = [i for i, line in enumerate(target_body) if line.strip() == anchor]
        if len(hits) != 1:
            return False, 'restore-menu anchor missing or ambiguous in k'
        pos = hits[0]
        raw = [
            '    const p1, 0x7f0f050c',
            '    invoke-static {p1, v9}, Lru5;->e0(ILz11;)Ljava/lang/String;',
            '    move-result-object p1',
            '    new-instance v4, Lbm4;',
            '    sget-object v10, Lcom/box/app/vpn/RestoreCfg;->MENU:Lcom/box/app/vpn/RestoreCfg;',
            '    invoke-direct {v4, p1, v10}, Lbm4;-><init>(Ljava/lang/Object;Ljava/lang/Object;)V',
            '    filled-new-array {p2, p3, v0, v4}, [Lbm4;',
        ]
        inserts, deletes = [(pos, raw)], {pos}
        reg_map.update({'p1': 'p1', 'p2': 'p2', 'p3': 'p3', 'v0': 'v0', 'v4': 'v4', 'v9': 'v9', 'v10': 'v10'})
        manual = 'add restore item to k proxy menu'
    elif old_ref.startswith('Lrx4;->invoke('):
        anchor = 'filled-new-array {p2, p1, v0}, [Lpv4;'
        hits = [i for i, line in enumerate(target_body) if line.strip() == anchor]
        if len(hits) != 1:
            return False, 'restore-menu anchor missing or ambiguous in q75'
        pos = hits[0]
        raw = [
            '    const p0, 0x7f0f050c',
            '    invoke-static {p0, v9}, Lru5;->e0(ILz11;)Ljava/lang/String;',
            '    move-result-object p0',
            '    new-instance v4, Lbm4;',
            '    sget-object v5, Lcom/box/app/vpn/RestoreCfg;->MENU:Lcom/box/app/vpn/RestoreCfg;',
            '    invoke-direct {v4, p0, v5}, Lbm4;-><init>(Ljava/lang/Object;Ljava/lang/Object;)V',
            '    filled-new-array {p2, p1, v0, v4}, [Lbm4;',
        ]
        inserts, deletes = [(pos, raw)], {pos}
        reg_map.update({'p0': 'p0', 'p1': 'p1', 'p2': 'p2', 'v0': 'v0', 'v4': 'v4', 'v5': 'v5', 'v9': 'v9'})
        manual = 'add restore item to q75 proxy menu'
    elif old_ref.startswith('Llb1;->g('):
        if not inserts or len(inserts[0][1]) < 6:
            return False, 'fork coroutine state hunk changed'
        pos, _ = inserts[0]
        states = [
            '    :pswitch_9', '    invoke-static {v1}, Lsi3;->l0(Ljava/lang/Object;)V',
            '    goto/16 :goto_dd', '    :pswitch_10',
            '    invoke-static {v1}, Lsi3;->l0(Ljava/lang/Object;)V',
            '    goto/16 :goto_sd',
        ]
        inserts[0] = (pos, states)
        label_out.update({'pswitch_9': 'pswitch_9', 'pswitch_10': 'pswitch_10',
                          'goto_dd': 'goto_dd', 'goto_sd': 'goto_sd'})
        reg_map.update({'v1': 'v1'})
        manual = 'preserve target pswitch_0 and add custom coroutine states 9/10'
    elif old_ref.startswith('Lf55;-><clinit>()V'):
        reg_map['v9'] = 'v9'
        manual = 'allocate a dedicated v9 for the custom VPN enum name'
    elif old_ref.startswith('Liw4;->invoke('):
        reg_map['v10'] = 'v10'
        manual = 'keep field h in range-call argument register v10'

    audit_entry = {'old': old_ref, 'new': plan['new'], 'alignment': round(alignment, 4)}
    if manual:
        audit_entry['manualAnchor'] = manual

    target_loc_index, target_locals = get_locals(target_body)
    fresh, next_local = {}, target_locals
    if old_ref.startswith('Lf55;-><clinit>()V'):
        next_local = max(next_local, 10)
    translated, unmapped = [], []
    for position, raw_lines in inserts:
        group = []
        future_regs = set()
        for line in target_body[position:]:
            future_regs.update(reg for reg in all_range_regs(line) if reg.startswith('v'))
        safe = ['v' + str(i) for i in range(target_locals) if 'v' + str(i) not in future_regs]
        for line in raw_lines:
            for reg in REG_RE.findall(strip_comment(line)):
                if reg.startswith('p') or reg in reg_map or reg in fresh:
                    continue
                if reg not in unmapped:
                    unmapped.append(reg)
                if safe:
                    fresh[reg] = safe.pop(0)
                else:
                    fresh[reg] = 'v' + str(next_local)
                    next_local += 1
            def subreg(match):
                reg = match.group(0)
                return reg_map.get(reg, fresh.get(reg, reg))
            mapped = rewrite_unquoted(line, lambda code: REG_RE.sub(subreg, code))
            mapped = rewrite_unquoted(
                mapped, lambda code: LABEL_RE.sub(
                    lambda match: ':' + label_out.get(match.group(0)[1:], match.group(0)[1:]), code))
            mapped = mapper.line(mapped, local)
            if mapped.strip():
                group.append(mapped)
        if group:
            translated.append((position, group))
    if next_local > target_locals:
        param_count = parameter_words(target.splitlines()[0])
        def param_alias(match):
            value = int(match.group(1))
            if target_locals <= value < target_locals + param_count:
                return 'p' + str(value - target_locals)
            return match.group(0)
        for i, line in enumerate(target_body):
            target_body[i] = rewrite_unquoted(line, lambda code: re.sub(r'\bv(\d+)\b', param_alias, code))
    for index in sorted(deletes, reverse=True):
        if 0 <= index < len(target_body):
            target_body.pop(index)
    for position, group in sorted(translated, key=lambda item: item[0], reverse=True):
        adjusted = position - sum(1 for deletion in deletes if deletion < position)
        target_body[max(0, min(adjusted, len(target_body))):max(0, min(adjusted, len(target_body)))] = group
    locals_index, locals_count = get_locals(target_body)
    need = max(target_locals, next_local)
    if need > locals_count:
        if locals_index is None:
            return False, 'cannot safely expand target register frame'
        target_body[locals_index] = re.sub(r'(\.locals\s+)\d+', r'\g<1>' + str(need), target_body[locals_index])
    new_block = target.splitlines()[0] + '\n' + '\n'.join(target_body) + '\n.end method'
    path = out_root / plan['targetFile']
    if not replace_block(path, target_sig, new_block):
        return False, 'target method replacement failed'
    audit_entry.update({'insertions': [len(lines) for _, lines in translated],
                        'deletions': len(deletes)})
    audit.append(audit_entry)
    return True, {'inserts': sum(len(group) for _, group in translated),
                  'deletes': len(deletes), 'alignment': round(alignment, 4),
                  'unmappedRegisters': unmapped}


def merge_resources(old, custom, new, out):
    old_public = public_map(old / 'res/values/public.xml')
    custom_public = public_map(custom / 'res/values/public.xml')
    tree = ET.parse(new / 'res/values/public.xml')
    root = tree.getroot()
    new_by_name = {(e.attrib.get('type'), e.attrib.get('name')): e for e in root if e.tag == 'public'}
    old_names = {(e.attrib.get('type'), e.attrib.get('name'))
                 for e in ET.parse(old / 'res/values/public.xml').getroot() if e.tag == 'public'}
    max_string = max((int(e.attrib['id'], 16) for e in root
                      if e.tag == 'public' and e.attrib.get('type') == 'string'), default=0x7f0f0000)
    custom_root = ET.parse(custom / 'res/values/public.xml').getroot()
    for entry in custom_root:
        if entry.tag != 'public' or entry.attrib.get('type') != 'string':
            continue
        key = (entry.attrib['type'], entry.attrib['name'])
        if key in old_names or key in new_by_name:
            continue
        max_string += 1
        clone = ET.Element('public', {'type': 'string', 'name': entry.attrib['name'],
                                      'id': '0x%08x' % max_string})
        root.append(clone)
        new_by_name[key] = clone
    ET.indent(tree, space='    ')
    tree.write(out / 'res/values/public.xml', encoding='utf-8', xml_declaration=True)
    target_ids = {(e.attrib.get('type'), e.attrib.get('name')): e.attrib['id']
                  for e in ET.parse(out / 'res/values/public.xml').getroot() if e.tag == 'public'}
    old_id_name = {e.attrib['id']: (e.attrib['type'], e.attrib['name'])
                   for e in ET.parse(old / 'res/values/public.xml').getroot() if e.tag == 'public'}
    custom_id_name = {e.attrib['id']: (e.attrib['type'], e.attrib['name'])
                      for e in ET.parse(custom / 'res/values/public.xml').getroot() if e.tag == 'public'}
    id_map = {}
    for source in (old_id_name, custom_id_name):
        for old_id, key in source.items():
            if key in target_ids and old_id != target_ids[key]:
                id_map[old_id] = target_ids[key]
    for locale in ('values', 'values-ru', 'values-zh-rCN', 'values-zh-rTW'):
        relative = f'res/{locale}/strings.xml'
        old_root = ET.parse(old / relative).getroot()
        custom_root = ET.parse(custom / relative).getroot()
        new_tree = ET.parse(new / relative)
        new_root = new_tree.getroot()
        old_items = {e.attrib.get('name'): e for e in old_root if e.tag == 'string'}
        custom_items = {e.attrib.get('name'): e for e in custom_root if e.tag == 'string'}
        new_items = {e.attrib.get('name'): e for e in new_root if e.tag == 'string'}
        for name, custom_entry in custom_items.items():
            old_entry = old_items.get(name)
            new_entry = new_items.get(name)
            if old_entry is not None and new_entry is not None and (old_entry.text, old_entry.attrib) != (custom_entry.text, custom_entry.attrib):
                new_entry.text = custom_entry.text
                for key, value in custom_entry.attrib.items():
                    if key != 'name':
                        new_entry.attrib[key] = value
            elif old_entry is None and new_entry is None:
                clone = ET.fromstring(ET.tostring(custom_entry, encoding='unicode'))
                new_root.append(clone)
                new_items[name] = clone
        ET.indent(new_tree, space='    ')
        new_tree.write(out / relative, encoding='utf-8', xml_declaration=True)
    return id_map


def merge_manifest(old, custom, new, out):
    ET.register_namespace('android', ANDROID[1:-1])
    tree = ET.parse(new / 'AndroidManifest.xml')
    root = tree.getroot()
    custom_root = ET.parse(custom / 'AndroidManifest.xml').getroot()
    existing = {(e.tag, e.attrib.get(ANDROID + 'name')): e for e in list(root)}
    added = 0
    for element in list(custom_root):
        if element.tag == 'application':
            continue
        key = (element.tag, element.attrib.get(ANDROID + 'name'))
        if key not in existing:
            clone = ET.fromstring(ET.tostring(element, encoding='unicode'))
            root.append(clone)
            existing[key] = clone
            added += 1
    target_app = next(e for e in root if e.tag == 'application')
    custom_app = next(e for e in custom_root if e.tag == 'application')
    app_items = {(e.tag, e.attrib.get(ANDROID + 'name')): e for e in list(target_app)}
    for element in list(custom_app):
        key = (element.tag, element.attrib.get(ANDROID + 'name'))
        if key not in app_items:
            clone = ET.fromstring(ET.tostring(element, encoding='unicode'))
            target_app.append(clone)
            app_items[key] = clone
            added += sum(1 for _ in clone.iter())
        else:
            target = app_items[key]
            known = {(child.tag, child.attrib.get(ANDROID + 'name')) for child in list(target)}
            for child in list(element):
                child_key = (child.tag, child.attrib.get(ANDROID + 'name'))
                if child_key not in known:
                    target.append(ET.fromstring(ET.tostring(child, encoding='unicode')))
                    known.add(child_key)
                    added += 1
    ET.indent(tree, space='    ')
    tree.write(out / 'AndroidManifest.xml', encoding='utf-8', xml_declaration=True)
    return added


def merge_field(out, mapper, target_class, declaration):
    path = out / 'smali' / (target_class[1:-1] + '.smali')
    if not path.is_file():
        return False, 'class missing ' + target_class
    text = path.read_text(errors='replace')
    match = re.match(r'^\.field\s+([^\n]*?)([A-Za-z_$][\w$]*):(\S+)', declaration)
    if not match:
        return False, 'bad declaration'
    name = match.group(2)
    if re.search(r'^\.field[^\n]*\b' + re.escape(name) + r':', text, re.M):
        return True, 'already exists ' + name
    new_declaration = mapper.line(declaration)
    lines = text.splitlines()
    fields = [i for i, line in enumerate(lines) if line.startswith('.field ')]
    pos = max(fields) + 1 if fields else next(i + 1 for i, line in enumerate(lines) if line.startswith('.class'))
    lines.insert(pos, new_declaration)
    path.write_text('\n'.join(lines) + '\n')
    return True, new_declaration


def validate_manual_map_targets(old_root, new_root):
    """Fail early if a reviewed name move no longer matches the pinned trees."""
    old_classes = class_descriptors(old_root)
    new_classes = class_descriptors(new_root)
    for old, new in MANUAL_TYPE_OVERRIDES.items():
        if old not in old_classes or new not in new_classes:
            raise ValueError(f'manual type override is not present in pinned trees: {old} -> {new}')

    for category, mappings in (('field', MANUAL_FIELD_OVERRIDES),
                               ('method', MANUAL_MEMBER_OVERRIDES)):
        for source, target in mappings.items():
            owner, signature = target.split('->', 1)
            if owner not in new_classes:
                raise ValueError(f'manual {category} target class is missing: {target}')
            path = new_root / 'smali' / (owner[1:-1] + '.smali')
            text = path.read_text(errors='replace')
            if category == 'method':
                declared = {line.split()[-1] for line in text.splitlines()
                            if line.startswith('.method ')}
            else:
                declared = {line.split()[-1].split('=', 1)[0]
                            for line in text.splitlines() if line.startswith('.field ')}
            if signature not in declared:
                raise ValueError(f'manual {category} target is not declared: {source} -> {target}')
    return old_classes, new_classes


def adapt_cfg_icon_builder(custom_root, out_root):
    """Use 171's split path builder for this custom icon-only call site."""
    relative = Path('smali/com/box/app/cfg/CfgIcon.smali')
    source_path, output_path = custom_root / relative, out_root / relative
    source = source_path.read_text(errors='replace')
    if 'Lmw;' not in source or 'Lhw;' in source:
        raise ValueError('CfgIcon no longer has the reviewed Lmw-only builder references')
    text = output_path.read_text(errors='replace')
    count = text.count(CFG_ICON_BUILDER_FROM)
    if count == 0:
        if CFG_ICON_BUILDER_TO in text:
            return 'already uses Lbx4 path builder'
        raise ValueError('CfgIcon has no globally mapped Lmw -> Lhw builder references')
    text = text.replace(CFG_ICON_BUILDER_FROM, CFG_ICON_BUILDER_TO)
    required = (
        'new-instance v3, Lbx4;',
        'Lbx4;-><init>()V',
        'Lbx4;->h(FF)V',
        'Lbx4;->f(FF)V',
        'Lbx4;->a()V',
        'Lbx4;->a:Ljava/util/ArrayList;',
    )
    missing = [reference for reference in required if reference not in text]
    if missing or CFG_ICON_BUILDER_FROM in text:
        raise ValueError('CfgIcon builder rewrite incomplete: ' + ', '.join(missing or [CFG_ICON_BUILDER_FROM]))
    output_path.write_text(text)
    return f'{count} Lhw owner references -> Lbx4 in CfgIcon only'


def validate_cfg_nav_composable_lambda_target(new_root):
    """Check the 171 wrapper, Composer guards, callback types, and group key."""
    helper_path = new_root / 'smali/tj.smali'
    if not helper_path.is_file():
        raise ValueError('171 Compose lambda helper is missing: ' + str(helper_path))
    helper_text = helper_path.read_text(errors='replace')
    signature = 'J(ILt92;Lla2;)Lyz0;'
    blocks = [match.group(0) for match in METHOD_RE.finditer(helper_text)
              if match.group(0).splitlines()[0].endswith(signature)]
    if len(blocks) != 1:
        raise ValueError('171 Ltj.J(ILt92;Lla2;)Lyz0; declaration is missing or ambiguous')
    factory = blocks[0]
    if ('Lyz0;-><init>(IZLjava/lang/Object;)V' not in factory
            or 'const/4 v1, 0x1' not in factory
            or 'Lla2;->k0(Ljava/lang/Object;)V' not in factory):
        raise ValueError('171 Ltj.J no longer creates and remembers a tracked Lyz0 wrapper')

    composer_path = new_root / 'smali/la2.smali'
    if not composer_path.is_file():
        raise ValueError('171 Composer class Lla2 is missing')
    composer = composer_path.read_text(errors='replace')
    if composer.count('.class public final Lla2;') != 1:
        raise ValueError('171 Composer class file does not declare Lla2')
    for method in ('.method public final S(IZ)Z', '.method public final V()V'):
        if composer.count(method) != 1:
            raise ValueError(f'171 Composer method {method} is missing or ambiguous')

    callback_path = new_root / 'smali/l92.smali'
    if not callback_path.is_file():
        raise ValueError('171 function interface Ll92 is missing')
    callback = callback_path.read_text(errors='replace')
    if (callback.count('.class public interface abstract Ll92;') != 1
            or callback.count('.implements Lt92;') != 1):
        raise ValueError('171 Ll92 callback interface is not a subtype of Lt92')

    key = int(CFG_ICON_LAMBDA_KEY, 0)
    if not -(1 << 31) <= key < (1 << 31):
        raise ValueError('CfgNav lambda key is outside the signed 32-bit Compose key range')
    unsigned_key = key & 0xffffffff
    const_re = re.compile(
        r'^\s*const(?P<wide>-wide)?(?P<form>/4|/16|/high16)?\s+'
        r'[vp]\d+,\s*(?P<value>-?(?:0x[0-9a-fA-F]+|\d+))(?=\s|$)'
    )
    for smali in (new_root / 'smali').rglob('*.smali'):
        for line_no, line in enumerate(smali.read_text(errors='replace').splitlines(), 1):
            match = const_re.match(line)
            if not match or match.group('wide'):
                continue
            value = int(match.group('value'), 0)
            form = match.group('form')
            if form == '/high16':
                value = (value & 0xffff) << 16
            elif form == '/16':
                value &= 0xffff
                if value & 0x8000:
                    value -= 0x10000
            elif form == '/4':
                value &= 0xf
                if value & 0x8:
                    value -= 0x10
            if (value & 0xffffffff) == unsigned_key:
                raise ValueError(
                    f'CfgNav lambda key {CFG_ICON_LAMBDA_KEY} collides with a '
                    f'171 integer constant at {smali}:{line_no}'
                )
    return (f'171 Ltj.J factory, Lla2.S/V Composer methods, and '
            f'Ll92-to-Lt92 callback interface verified; custom key '
            f'{CFG_ICON_LAMBDA_KEY} is unused by the pinned 171 Smali tree')


def adapt_cfg_nav_composer_api(text):
    """Map CfgNav's legacy Composer alias and guard methods to version 171."""
    old_signature = (
        '.method private static e(Lt72;Ljava/lang/Object;Landroid/content/Context;'
        'ILjava/lang/String;F)V'
    )
    new_signature = (
        '.method private static e(Lla2;Ljava/lang/Object;Landroid/content/Context;'
        'ILjava/lang/String;F)V'
    )
    old_call = (
        'invoke-static/range {v6 .. v11}, Lcom/box/app/cfg/CfgNav;->e('
        'Lt72;Ljava/lang/Object;Landroid/content/Context;ILjava/lang/String;F)V'
    )
    new_call = (
        'invoke-static/range {v6 .. v11}, Lcom/box/app/cfg/CfgNav;->e('
        'Lla2;Ljava/lang/Object;Landroid/content/Context;ILjava/lang/String;F)V'
    )
    legacy = (
        text.count('Lt72;') == 8
        and text.count(old_signature) == 1
        and text.count('check-cast v6, Lt72;') == 1
        and text.count('invoke-virtual {v6, v3, v4}, Lt72;->T(IZ)Z') == 1
        and text.count('invoke-virtual {v6}, Lt72;->W()V') == 1
        and text.count(old_call) == 3
    )
    fixed = (
        'Lt72;' not in text
        and text.count(new_signature) == 1
        and text.count('check-cast v6, Lla2;') == 1
        and text.count('invoke-virtual {v6, v3, v4}, Lla2;->S(IZ)Z') == 1
        and text.count('invoke-virtual {v6}, Lla2;->V()V') == 1
        and text.count(new_call) == 3
    )
    if fixed:
        return text, False
    if not legacy:
        raise ValueError('CfgNav Composer references differ from both reviewed 139 and 171 forms')

    text = text.replace('Lt72;', 'Lla2;')
    text = text.replace('Lla2;->T(IZ)Z', 'Lla2;->S(IZ)Z')
    text = text.replace('Lla2;->W()V', 'Lla2;->V()V')
    text = text.replace('Lla2;->T / W', 'Lla2;->S / V')
    if ('Lt72;' in text or text.count(new_signature) != 1
            or text.count('check-cast v6, Lla2;') != 1
            or text.count('invoke-virtual {v6, v3, v4}, Lla2;->S(IZ)Z') != 1
            or text.count('invoke-virtual {v6}, Lla2;->V()V') != 1
            or text.count(new_call) != 3):
        raise ValueError('CfgNav Composer API mapping did not produce the reviewed 171 form')
    return text, True


def validate_cfg_nav_composable_lambda_register_flow(text):
    """Prove the factory arguments and wrapped h-call keep their DEX types."""
    call = ('invoke-static/range {v4 .. v16}, '
            'Lhq;->h(Lw82;Lmz3;ZZJFFFLyz0;Lla2;II)V')
    factory_call = 'invoke-static {v3, v13, v14}, Ltj;->J(ILt92;Lla2;)Lyz0;'
    methods = [match.group(0) for match in METHOD_RE.finditer(text)
               if call in match.group(0)]
    if len(methods) != 1:
        raise ValueError(f'expected one CfgNav.e -> Lhq.h call, found {len(methods)}')
    lines = methods[0].splitlines()
    expected_header = (
        '.method private static e(Lla2;Ljava/lang/Object;Landroid/content/Context;'
        'ILjava/lang/String;F)V'
    )
    if not lines or lines[0].strip() != expected_header:
        raise ValueError('CfgNav lambda adapter must run in the Lla2-typed CfgNav.e method')
    locals_matches = [re.match(r'^\s*\.locals\s+(\d+)\s*$', line)
                      for line in lines]
    locals_matches = [match for match in locals_matches if match]
    if len(locals_matches) != 1 or int(locals_matches[0].group(1)) < 17:
        raise ValueError('CfgNav.e does not reserve the reviewed v13/v14 adapter registers')

    instructions = [line.strip() for line in lines
                    if line.strip() and not line.strip().startswith(('.', '#', ':'))]
    expected = (
        'new-instance v13, Lcom/box/app/cfg/CfgIcon;',
        'invoke-direct {v13, v2}, Lcom/box/app/cfg/CfgIcon;-><init>(I)V',
        'move-object/from16 v14, p0',
        f'const v3, {CFG_ICON_LAMBDA_KEY}',
        factory_call,
        'move-result-object v13',
        call,
    )
    positions = []
    for instruction in expected:
        matches = [i for i, line in enumerate(instructions) if line == instruction]
        if len(matches) != 1:
            raise ValueError(f'CfgNav lambda adapter instruction is missing or ambiguous: {instruction}')
        positions.append(matches[0])
    if positions != sorted(positions):
        raise ValueError('CfgNav lambda adapter instructions are out of type-safe order')

    def writes_register(instruction, register):
        match = re.match(r'^([A-Za-z][A-Za-z0-9_/-]*)\s+(v\d+)(?:,|\s|$)', instruction)
        if not match or match.group(2) != register:
            return False
        opcode = match.group(1)
        return not opcode.startswith((
            'if-', 'invoke-', 'iput', 'sput', 'aput', 'return', 'throw',
            'monitor-', 'goto', 'packed-switch', 'sparse-switch', 'fill-array-data',
        ))

    ctor_index, composer_index, factory_index = positions[1], positions[2], positions[4]
    if any(writes_register(line, 'v13')
           for line in instructions[ctor_index + 1:factory_index]):
        raise ValueError('CfgIcon callback register v13 is overwritten before Ltj.J')
    if any(writes_register(line, 'v14')
           for line in instructions[composer_index + 1:factory_index]):
        raise ValueError('Lla2 Composer register v14 is overwritten before Ltj.J')
    if positions[5] != factory_index + 1 or positions[6] != positions[5] + 1:
        raise ValueError('Ltj.J result is not immediately passed to the Lhq.h Composable slot')
    return 'CfgIcon/Lla2 factory arguments and Lyz0 result register flow verified'


def adapt_cfg_nav_composable_lambda(out_root, target_root=None):
    """Use 171's tracked ComposableLambda factory for the custom icon callback."""
    target_root = target_root or out_root
    validation = validate_cfg_nav_composable_lambda_target(target_root)
    icon_path = out_root / 'smali/com/box/app/cfg/CfgIcon.smali'
    if not icon_path.is_file():
        raise ValueError('mapped CfgIcon callback class is missing')
    icon_text = icon_path.read_text(errors='replace')
    if icon_text.count('.implements Ll92;') != 1 or 'Lt62;' in icon_text:
        raise ValueError('CfgIcon does not implement the mapped 171 Ll92 callback interface')

    path = out_root / 'smali/com/box/app/cfg/CfgNav.smali'
    text = path.read_text(errors='replace')
    text, composer_api_changed = adapt_cfg_nav_composer_api(text)
    call = ('invoke-static/range {v4 .. v16}, '
            'Lhq;->h(Lw82;Lmz3;ZZJFFFLyz0;Lla2;II)V')
    factory_call = 'invoke-static {v3, v13, v14}, Ltj;->J(ILt92;Lla2;)Lyz0;'
    if text.count(factory_call) == 1 and call in text:
        flow = validate_cfg_nav_composable_lambda_register_flow(text)
        if composer_api_changed:
            path.write_text(text)
        return ('already wraps CfgIcon with Ltj.J and uses the 171 Lla2 Composer API; '
                + flow + '; ' + validation)
    matches = [match for match in METHOD_RE.finditer(text) if call in match.group(0)]
    if len(matches) != 1:
        raise ValueError(f'expected one mapped CfgNav -> Lhq.h call, found {len(matches)}')

    match = matches[0]
    block = match.group(0).rstrip()
    lines = block.splitlines()
    call_indices = [i for i, line in enumerate(lines) if line.strip() == call]
    locals_indices = [i for i, line in enumerate(lines)
                      if re.match(r'^\s*\.locals\s+\d+\s*$', line)]
    if len(call_indices) != 1 or len(locals_indices) != 1:
        raise ValueError('CfgNav.e call or register frame is ambiguous')
    call_index, locals_index = call_indices[0], locals_indices[0]
    locals_match = re.match(r'^(\s*\.locals\s+)(\d+)(\s*)$', lines[locals_index])
    if not locals_match:
        raise ValueError('CfgNav.e has an unsupported register directive')
    local_count = int(locals_match.group(2))
    if local_count < 17:
        raise ValueError(f'CfgNav.e needs at least 17 locals for the reviewed adapter, got {local_count}')
    if any(re.search(r'\bv3\b', line) for line in lines[call_index:]):
        raise ValueError('CfgNav.e adapter register v3 is live after the wrapped-call site')

    indent = re.match(r'^\s*', lines[call_index]).group(0)
    adapter = [
        indent + f'const v3, {CFG_ICON_LAMBDA_KEY}',
        indent + factory_call,
        indent + 'move-result-object v13',
    ]
    lines[call_index:call_index] = adapter
    new_block = '\n'.join(lines)
    if text.count(block) != 1:
        raise ValueError('CfgNav.e method block is missing or ambiguous')
    updated = text.replace(block, new_block, 1)
    flow = validate_cfg_nav_composable_lambda_register_flow(updated)
    path.write_text(updated)
    return ('wrapped CfgIcon with 171 Ltj.J and mapped the Composer API to Lla2/S/V; '
            + flow + '; ' + validation)


def adapt_update_core_dingtalk_sources(out_root):
    """Restore DingTalk sources in the real v171 source-list screen.

    The new source manager reads ``sources_v1`` once on first composition, so
    updating only sd1.b() would leave users with an already-persisted seven-item
    list unchanged. Add the two reviewed GitHub release descriptors to the
    defaults, then do a one-time, ID-preserving merge into existing preferences
    from ba7's production loader.
    """
    out_root = Path(out_root)
    sd_path = out_root / 'smali/sd1.smali'
    ba_path = out_root / 'smali/ba7.smali'
    if not sd_path.is_file() or not ba_path.is_file():
        raise ValueError('v171 Update Core source manager classes sd1/ba7 are missing')

    sd_text = sd_path.read_text(errors='replace')
    sd_methods = method_blocks(sd_text)
    source_sig = 'b()Ljava/util/List;'
    source_block = sd_methods.get(source_sig)
    if not source_block:
        raise ValueError('sd1 default source-list method b() is missing')

    mihomo_id = 'mihomo_dingtalk'
    singbox_id = 'sing-box_dingtalk'
    ids_present = [name in source_block for name in (mihomo_id, singbox_id)]
    old_array = 'filled-new-array/range {v3 .. v9}, [Lqd1;'
    new_array = 'filled-new-array/range {v3 .. v11}, [Lqd1;'
    if ids_present == [False, False]:
        locals_match = re.search(r'^\s*\.locals\s+(\d+)\s*$', source_block, re.M)
        if not locals_match or int(locals_match.group(1)) < 24:
            raise ValueError('sd1.b has no v10-v22 registers for the reviewed source descriptors')
        if len(re.findall(r'^\s*new-instance\s+v\d+, Lqd1;\s*$', source_block, re.M)) != 7:
            raise ValueError('sd1.b no longer has the reviewed seven-source default list')
        if source_block.count(old_array) != 1:
            raise ValueError('sd1.b default source-array anchor is missing or ambiguous')
        descriptors = '''\
    new-instance v10, Lqd1;

    const-string v11, "mihomo_dingtalk"
    const-string v12, "Mihomo Smart + eBPF + \\u9489\\u9489\\u76f4\\u8fde"
    const-string v13, "mihomo"
    const-string v14, "github"
    const-string v15, "jieluojun/mihomo"
    const-string v16, "tag"
    const-string v17, "Prerelease-Alpha"
    const-string v18, "mihomo-android-arm64-v8-alpha-smart-[A-Za-z0-9._-]+\\\\.gz"
    const/4 v19, 0x1
    const-string v20, ""
    const-string v21, ""
    invoke-direct/range {v10 .. v21}, Lqd1;-><init>(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;ZLjava/lang/String;Ljava/lang/String;)V

    new-instance v11, Lqd1;

    const-string v12, "sing-box_dingtalk"
    const-string v13, "Sing-Box Smart + eBPF + \\u9489\\u9489\\u76f4\\u8fde"
    const-string v14, "sing-box"
    const-string v15, "github"
    const-string v16, "jieluojun/sing-box"
    const-string v17, "latest"
    const-string v18, ""
    const-string v19, "sing-box-.+-android-arm64-v8a-ebpf\\\\.tar\\\\.gz"
    const/4 v20, 0x1
    const-string v21, ""
    const-string v22, ""
    invoke-direct/range {v11 .. v22}, Lqd1;-><init>(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;ZLjava/lang/String;Ljava/lang/String;)V

    '''
        source_block_new = source_block.replace(
            old_array, descriptors + new_array, 1)
        source_file = sd_path.read_text(errors='replace')
        if source_file.count(source_block) != 1:
            raise ValueError('sd1.b method block is missing or ambiguous')
        sd_text = source_file.replace(source_block, source_block_new, 1)
        sd_path.write_text(sd_text)
        source_block = method_blocks(sd_text).get(source_sig)
    elif ids_present != [True, True] or new_array not in source_block:
        raise ValueError('sd1.b contains a partial or unsupported DingTalk source-list patch')

    migration_sig = 'h(Ljava/util/List;)Ljava/util/List;'
    helper = '''\
.method public static h(Ljava/util/List;)Ljava/util/List;
    .locals 12

    invoke-static {}, Lln;->w()Landroid/content/Context;
    move-result-object v0
    const-string v1, "tools_core_update"
    const/4 v2, 0x0
    invoke-virtual {v0, v1, v2}, Landroid/content/Context;->getSharedPreferences(Ljava/lang/String;I)Landroid/content/SharedPreferences;
    move-result-object v0
    const-string v1, "dingtalk_sources_migrated_v1"
    const/4 v2, 0x0
    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences;->getBoolean(Ljava/lang/String;Z)Z
    move-result v2
    if-eqz v2, :cond_migrate_sources
    return-object p0

    :cond_migrate_sources
    new-instance v3, Ljava/util/ArrayList;
    invoke-direct {v3, p0}, Ljava/util/ArrayList;-><init>(Ljava/util/Collection;)V
    const/4 v4, 0x0
    invoke-static {}, Lsd1;->b()Ljava/util/List;
    move-result-object v5
    invoke-interface {v5}, Ljava/lang/Iterable;->iterator()Ljava/util/Iterator;
    move-result-object v5

    :loop_default_sources
    invoke-interface {v5}, Ljava/util/Iterator;->hasNext()Z
    move-result v6
    if-eqz v6, :cond_finish_sources
    invoke-interface {v5}, Ljava/util/Iterator;->next()Ljava/lang/Object;
    move-result-object v6
    check-cast v6, Lqd1;
    iget-object v7, v6, Lqd1;->a:Ljava/lang/String;
    const-string v8, "mihomo_dingtalk"
    invoke-static {v7, v8}, Lf13;->p(Ljava/lang/Object;Ljava/lang/Object;)Z
    move-result v8
    if-nez v8, :cond_dingtalk_source
    const-string v8, "sing-box_dingtalk"
    invoke-static {v7, v8}, Lf13;->p(Ljava/lang/Object;Ljava/lang/Object;)Z
    move-result v8
    if-eqz v8, :cond_next_source

    :cond_dingtalk_source
    invoke-interface {v3}, Ljava/lang/Iterable;->iterator()Ljava/util/Iterator;
    move-result-object v9

    :loop_existing_sources
    invoke-interface {v9}, Ljava/util/Iterator;->hasNext()Z
    move-result v10
    if-eqz v10, :cond_add_source
    invoke-interface {v9}, Ljava/util/Iterator;->next()Ljava/lang/Object;
    move-result-object v10
    check-cast v10, Lqd1;
    iget-object v10, v10, Lqd1;->a:Ljava/lang/String;
    invoke-static {v7, v10}, Lf13;->p(Ljava/lang/Object;Ljava/lang/Object;)Z
    move-result v10
    if-eqz v10, :loop_existing_sources
    goto :cond_next_source

    :cond_add_source
    invoke-virtual {v3, v6}, Ljava/util/ArrayList;->add(Ljava/lang/Object;)Z
    move-result v10
    const/4 v4, 0x1

    :cond_next_source
    goto :loop_default_sources

    :cond_finish_sources
    if-eqz v4, :cond_mark_sources_migrated
    invoke-static {v3}, Lsd1;->f(Ljava/util/List;)V

    :cond_mark_sources_migrated
    invoke-interface {v0}, Landroid/content/SharedPreferences;->edit()Landroid/content/SharedPreferences$Editor;
    move-result-object v1
    const-string v2, "dingtalk_sources_migrated_v1"
    const/4 v4, 0x1
    invoke-interface {v1, v2, v4}, Landroid/content/SharedPreferences$Editor;->putBoolean(Ljava/lang/String;Z)Landroid/content/SharedPreferences$Editor;
    move-result-object v1
    invoke-interface {v1}, Landroid/content/SharedPreferences$Editor;->apply()V
    return-object v3
.end method
'''
    if migration_sig in sd_methods:
        migration_block = sd_methods[migration_sig]
        for required in ('dingtalk_sources_migrated_v1', 'mihomo_dingtalk',
                         'sing-box_dingtalk', 'Lsd1;->f(Ljava/util/List;)V'):
            if required not in migration_block:
                raise ValueError('sd1.h existing-source migration is incomplete: ' + required)
    else:
        sd_text = sd_path.read_text(errors='replace').rstrip() + '\n\n' + helper
        sd_path.write_text(sd_text)

    ba_text = ba_path.read_text(errors='replace')
    ba_methods = method_blocks(ba_text)
    loader_hits = [block for block in ba_methods.values()
                   if 'sources_v1' in block and 'Lsd1;->b()Ljava/util/List;' in block
                   and 'Lsd1;->f(Ljava/util/List;)V' in block]
    if len(loader_hits) != 1:
        raise ValueError(f'expected one ba7 Update Core sources loader, found {len(loader_hits)}')
    loader = loader_hits[0]
    hook = 'invoke-static {v0}, Lsd1;->h(Ljava/util/List;)Ljava/util/List;'
    if hook not in loader:
        anchor = (':goto_4\n'
                  '    invoke-static {v0}, Lmb3;->L(Ljava/lang/Object;)Liw4;')
        if loader.count(anchor) != 1:
            raise ValueError('ba7 source-loader state-initialization anchor is missing or ambiguous')
        loader_new = loader.replace(
            anchor,
            ':goto_4\n'
            '    invoke-static {v0}, Lsd1;->h(Ljava/util/List;)Ljava/util/List;\n'
            '    move-result-object v0\n'
            '    invoke-static {v0}, Lmb3;->L(Ljava/lang/Object;)Liw4;', 1)
        if ba_text.count(loader) != 1:
            raise ValueError('ba7 Update Core loader method is missing or ambiguous')
        ba_text = ba_text.replace(loader, loader_new, 1)
        ba_path.write_text(ba_text)
        loader = loader_new
    elif loader.count(hook) != 1:
        raise ValueError('ba7 source-loader migration hook is duplicated')
    if not (loader.index(hook) < loader.index('invoke-static {v0}, Lmb3;->L(Ljava/lang/Object;)Liw4;')
            and 'Luj;->B(Lob7;Lqd1;' in loader):
        raise ValueError('ba7 source-loader migration is not on the rendered Update Core path')

    return ('added both legacy GitHub DingTalk sources to sd1.b; one-time merged and saved '
            'them into existing sources_v1 preferences before ba7 renders the Qd1 list')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old', type=Path, default=Path('.tools/upstream-old/decompiled'))
    parser.add_argument('--new', type=Path, default=Path('.tools/upstream-new/decompiled'))
    parser.add_argument('--custom', type=Path, default=Path('decompiled'))
    parser.add_argument('--coverage', type=Path,
                        default=Path('upstream/26.11.16.25abc84/migration/coverage.json'))
    parser.add_argument('--maps', type=Path, default=Path('.tools/resolved-maps.json'))
    parser.add_argument('--output', type=Path, default=Path('.tools/migrated'))
    parser.add_argument('--replace-output', action='store_true')
    args = parser.parse_args()
    if not args.maps.is_file():
        raise SystemExit('missing map file; generate and review it first: ' + str(args.maps))
    maps = json.loads(args.maps.read_text())
    old_classes, new_classes = validate_manual_map_targets(args.old, args.new)
    if args.output.exists():
        if not args.replace_output:
            raise SystemExit('output already exists; use --replace-output to recreate scratch output')
        if args.output.resolve() in (Path('decompiled').resolve(), Path('.').resolve()):
            raise SystemExit('refusing to replace source/repository directory')
        shutil.rmtree(args.output)
    shutil.copytree(args.new, args.output)
    id_map = merge_resources(args.old, args.custom, args.new, args.output)
    type_pattern = r'L[A-Za-z0-9_/$-]+;'
    type_map = {old: item['new'] for old, item in maps.get('types', {}).items()
                if re.fullmatch(type_pattern, old) and re.fullmatch(type_pattern, item['new'])}
    if len(type_map) != len(maps.get('types', {})):
        raise SystemExit('type map contains invalid descriptor keys; rebuild and review it')
    type_map.update(MANUAL_TYPE_OVERRIDES)
    if any(not re.fullmatch(type_pattern, old) or not re.fullmatch(type_pattern, new)
           for old, new in MANUAL_TYPE_OVERRIDES.items()):
        raise SystemExit('manual type map contains invalid descriptor keys')
    destinations = list(type_map.values())
    if len(destinations) != len(set(destinations)):
        raise SystemExit('type map is not one-to-one; resolve class-map collisions before porting')
    field_map = {old: item['new'] for old, item in maps.get('fields', {}).items()}
    field_map.update(MANUAL_FIELD_OVERRIDES)
    field_map.update({
        'Lf55;->t:Lf55;': 'Lne5;->t:Lne5;',
        'Lnv;->e:Lq85;': 'Liv;->f:Llh5;',
        'Lq85;->j:Lpb6;': 'Llh5;->i:Lrk6;',
        'Lqm5;->cfgD:Z': 'Lpv5;->cfgD:Z',
    })
    member_map = {old: item['new'] for old, item in maps.get('members', {}).items()}
    member_map.update(MANUAL_MEMBER_OVERRIDES)
    member_map.update({
        'Lip1;-><init>(Ljava/lang/String;ZZLe62;Ljava/util/ArrayList;I)V':
            'Lyr1;-><init>(Ljava/lang/String;ZZLw82;Ljava/util/List;I)V',
        'Ldj3;->A(Lz11;)Lpv0;': 'Lub3;->H(Lla2;)Luv0;',
        'Lqu5;->o(ZLp62;Ljava/lang/String;Ljava/lang/String;Lqz0;ZLz11;III)V':
            'Lub3;->s(ZLh92;Ljava/lang/String;Ljava/lang/String;Lyz0;ZLla2;III)V',
        'Lag7;->I(Lwp3;FFFF)Lwp3;': 'Lif0;->S(Lmz3;FFFF)Lmz3;',
        'Ljh2;-><init>(Ljava/lang/String;Z)V': 'Lvo2;-><init>(Ljava/lang/String;Z)V',
    })
    mapper = Mapper(
        id_map,
        {'types': {k: {'new': v} for k, v in type_map.items()},
         'fields': {k: {'new': v} for k, v in field_map.items()},
         'members': {k: {'new': v} for k, v in member_map.items()}},
        old_classes, new_classes)
    r_old, r_new = public_map(args.old / 'res/values/public.xml'), public_map(args.new / 'res/values/public.xml')
    coverage = json.loads(args.coverage.read_text())
    report = {'ok': 0, 'errors': [], 'whole': 0, 'patch': 0, 'fields': 0,
              'additions': 0, 'toast': 0, 'manifest': 0, 'semanticFixes': []}
    audit = []
    for plan in coverage['completed']:
        try:
            ok, detail = patch_method(plan, mapper, args.old, args.custom, args.output,
                                      r_old, r_new, audit)
        except Exception as exc:
            ok, detail = False, repr(exc)
        if ok:
            report['ok'] += 1
            mode = plan.get('mode')
            if mode not in ('whole', 'patch'):
                report['errors'].append('PATCH ' + plan['old'] + ': unknown migration mode ' + str(mode))
            else:
                report[mode] += 1
            print('patched', plan['old'], '=>', plan['new'], detail)
        else:
            report['errors'].append('PATCH ' + plan['old'] + ': ' + str(detail))
            print('PATCH ERROR', plan['old'], detail)
    for target_class, declaration in (
        ('Lne5;', '.field public static final enum t:Lf55;'),
        ('Lpv5;', '.field public cfgD:Z'),
    ):
        ok, detail = merge_field(args.output, mapper, target_class, declaration)
        if ok:
            report['fields'] += 1
        else:
            report['errors'].append('FIELD ' + target_class + ' ' + str(detail))
        print('field', target_class, detail)
    for relative in coverage['added']:
        source, target = args.custom / relative, args.output / relative
        if not source.is_file():
            report['errors'].append('missing addition ' + relative)
            continue
        if target.exists():
            report['errors'].append('addition conflict ' + relative)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith('.smali'):
            target.write_text('\n'.join(mapper.line(line)
                                        for line in source.read_text(errors='replace').splitlines()) + '\n')
        else:
            shutil.copyfile(source, target)
        report['additions'] += 1
    for name, transform in (
        ('CfgIcon builder API', lambda: adapt_cfg_icon_builder(args.custom, args.output)),
        ('CfgNav Compose lambda', lambda: adapt_cfg_nav_composable_lambda(args.output, args.new)),
        ('Update Core DingTalk source metadata',
         lambda: adapt_update_core_dingtalk_sources(args.output)),
    ):
        try:
            detail = transform()
            report['semanticFixes'].append({'name': name, 'detail': detail})
            print('semantic fix', name, detail)
        except Exception as exc:
            report['errors'].append('API ' + name + ': ' + repr(exc))
            print('API ERROR', name, repr(exc))
    for path in args.output.rglob('*.smali'):
        text = path.read_text(errors='replace')
        if 'Landroid/widget/Toast;->makeText' in text:
            path.write_text(text.replace('Landroid/widget/Toast;->makeText',
                                         'Lcom/box/app/vpn/FToast;->makeText'))
            report['toast'] += 1
    report['manifest'] = merge_manifest(args.old, args.custom, args.new, args.output)
    Path('.tools/port-hunks.json').write_text(json.dumps(audit, indent=2) + '\n')
    Path('.tools/delta-stage6-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print('summary', json.dumps(report, indent=2))
    if report['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
