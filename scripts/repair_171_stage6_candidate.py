#!/usr/bin/env python3
"""Repair and verify the reviewed semantic edge cases in a generated 171 tree.

The stage-6 smali porter works in a disposable tree. This deterministic post-pass
protects sensitive R8/API deltas where text/register alignment is insufficient:
the VPN enum, core registry, range-call argument, Compose register order,
storage-directory branch, coroutine states, tar-entry matcher, and callback
receiver preservation. It never edits the source decompile.
"""
import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import check_smali_reference_moves as reference_moves

METHOD_RE = re.compile(r"^\.method[^\n]*$.*?^\.end method[ \t]*$", re.M | re.S)
LABEL_RE = re.compile(r"^(:\S+)\s*$")
DEBUG_PREFIXES = ('.line ', '.local ', '.end local ', '.restart local ',
                  '.param ', '.end param ', '.source ', '.prologue')
CORE_ENTRIES = (
    ('mihomo', 'proxy_core_mihomo'),
    ('mihomo_smart', 'proxy_core_mihomo_smart'),
    ('mihomo_dingtalk', 'proxy_core_mihomo_dingtalk'),
    ('sing-box', 'proxy_core_sing_box'),
    ('sing-box_ref1nd', 'proxy_core_sing_box_ref1nd'),
    ('sing-box_dingtalk', 'proxy_core_sing_box_dingtalk'),
    ('xray', 'proxy_core_xray'),
    ('v2fly', 'proxy_core_v2fly'),
    ('hysteria', 'proxy_core_hysteria'),
)


def method_signature(block):
    return block.splitlines()[0].split()[-1]


def get_method(text, signature):
    hits = [m.group(0).rstrip() for m in METHOD_RE.finditer(text)
            if method_signature(m.group(0)) == signature]
    if len(hits) != 1:
        raise ValueError(f'expected exactly one {signature}, found {len(hits)}')
    return hits[0]


def replace_method(text, signature, replacement):
    old = get_method(text, signature)
    if text.count(old) != 1:
        raise ValueError(f'ambiguous method text for {signature}')
    return text.replace(old, replacement, 1)


def update_method(text, signature, transform):
    old = get_method(text, signature)
    new = transform(old)
    if new == old:
        return text, False
    return replace_method(text, signature, new), True


def fix_ne5(text):
    signature = '<clinit>()V'

    def transform(block):
        if '.field public static final enum t:Lne5;' not in text:
            raise ValueError('ne5 is missing the custom VPN enum field')
        lines = block.splitlines()
        locals_indices = [i for i, line in enumerate(lines)
                          if re.match(r'^\s*\.locals\s+\d+\s*$', line)]
        if len(locals_indices) != 1:
            raise ValueError('ne5 <clinit> must have one .locals directive')
        li = locals_indices[0]
        m = re.match(r'^\s*\.locals\s+(\d+)', lines[li])
        count = int(m.group(1))
        old_value = re.compile(r'^(\s*)const-string\s+v2,\s*"vpn"\s*$')
        new_value = re.compile(r'^\s*const-string\s+v9,\s*"vpn"\s*$')
        old_hits = [i for i, line in enumerate(lines) if old_value.match(line)]
        new_hits = [i for i, line in enumerate(lines) if new_value.match(line)]
        if old_hits and new_hits:
            raise ValueError('ne5 has both aliased and repaired vpn string registers')
        if len(old_hits) > 1 or len(new_hits) != 1 and not old_hits:
            raise ValueError('ne5 <clinit> has an unexpected vpn string initializer')
        if old_hits:
            indent = old_value.match(lines[old_hits[0]]).group(1)
            lines[old_hits[0]] = indent + 'const-string v9, "vpn"'
        old_ctor = 'invoke-direct {v6, v7, v8, v2}, Lne5;-><init>(ILjava/lang/String;Ljava/lang/String;)V'
        new_ctor = 'invoke-direct {v6, v7, v8, v9}, Lne5;-><init>(ILjava/lang/String;Ljava/lang/String;)V'
        old_ctor_hits = [i for i, line in enumerate(lines) if old_ctor in line]
        new_ctor_hits = [i for i, line in enumerate(lines) if new_ctor in line]
        if old_ctor_hits and new_ctor_hits:
            raise ValueError('ne5 has both aliased and repaired VPN constructor arguments')
        if len(old_ctor_hits) > 1 or len(new_ctor_hits) != 1 and not old_ctor_hits:
            raise ValueError('ne5 <clinit> has an unexpected VPN constructor call')
        if old_ctor_hits:
            lines[old_ctor_hits[0]] = lines[old_ctor_hits[0]].replace(old_ctor, new_ctor)
        if count < 10:
            lines[li] = re.sub(r'(\.locals\s+)\d+', r'\g<1>10', lines[li])
        if not any(new_ctor in line for line in lines):
            raise ValueError('ne5 VPN enum constructor does not consume v9')
        return '\n'.join(lines)

    return update_method(text, signature, transform)


def fix_g65(text):
    signature = 'invoke(Ljava/lang/Object;)Ljava/lang/Object;'
    old = re.compile(r'^(\s*)iget-object\s+v5,\s*v2,\s*Ldc0;->h:Ljava/lang/String;\s*$')
    new = re.compile(r'^\s*iget-object\s+v10,\s*v2,\s*Ldc0;->h:Ljava/lang/String;\s*$')

    def transform(block):
        lines = block.splitlines()
        old_hits = [i for i, line in enumerate(lines) if old.match(line)]
        new_hits = [i for i, line in enumerate(lines) if new.match(line)]
        if old_hits and new_hits:
            raise ValueError('g65 contains both the clobbering and repaired field load')
        if len(old_hits) > 1 or len(new_hits) != 1 and not old_hits:
            raise ValueError('g65 invoke has an unexpected Ldc0.h field load')
        if old_hits:
            indent = old.match(lines[old_hits[0]]).group(1)
            lines[old_hits[0]] = indent + 'iget-object v10, v2, Ldc0;->h:Ljava/lang/String;'
        if not any('invoke-static/range {v2 .. v26}, Ldc0;->a(' in line for line in lines):
            raise ValueError('g65 invoke no longer uses the reviewed v2..v26 argument range')
        if not any(re.match(r'^\s*\.locals\s+(?:2[6-9]|[3-9]\d+)\s*$', line) for line in lines):
            raise ValueError('g65 invoke has no local v10 register')
        return '\n'.join(lines)

    return update_method(text, signature, transform)


def fix_r6_tar_matcher(text):
    """Restore the reviewed exact-name / large split-segment tar match."""
    signature = 'l(Ljava/io/InputStream;Ljava/lang/String;Ljava/io/File;Ljava/lang/Long;Z)V'
    compare = ('invoke-static {v3, p1}, '
               'Lf13;->p(Ljava/lang/Object;Ljava/lang/Object;)Z')
    max_size_call = ('invoke-virtual {p3}, '
                     'Ljava/lang/Long;->longValue()J')
    broken = [
        'move-result v3',
        'if-eqz v3, :cond_7',
        'const-wide/32 v6, 0x100000',
        'cmp-long v6, v4, v6',
        'if-ltz v6, :cond_6',
        ':boxproxy_match',
        'if-nez v6, :boxproxy_match',
        'const-string v6, "-"',
        'invoke-virtual {p1, v6}, Ljava/lang/String;->concat(Ljava/lang/String;)Ljava/lang/String;',
        'move-result-object v6',
        'invoke-virtual {v3, v6}, Ljava/lang/String;->startsWith(Ljava/lang/String;)Z',
        'move-result v6',
    ]
    corrected = [
        'move-result v6',
        'if-nez v6, :boxproxy_match',
        'const-string v6, "-"',
        'invoke-virtual {p1, v6}, Ljava/lang/String;->concat(Ljava/lang/String;)Ljava/lang/String;',
        'move-result-object v6',
        'invoke-virtual {v3, v6}, Ljava/lang/String;->startsWith(Ljava/lang/String;)Z',
        'move-result v6',
        'if-eqz v6, :cond_7',
        'const-wide/32 v6, 0x100000',
        'cmp-long v6, v4, v6',
        'if-ltz v6, :cond_7',
        ':boxproxy_match',
    ]

    def significant(line):
        value = line.strip()
        return (value and not value.startswith(DEBUG_PREFIXES)
                and not value.startswith('#'))

    def transform(block):
        lines = block.splitlines()
        compare_hits = [i for i, line in enumerate(lines) if line.strip() == compare]
        if len(compare_hits) != 1:
            raise ValueError('r6.l must have one reviewed entry-name equality check')
        compare_index = compare_hits[0]
        size_hits = [i for i, line in enumerate(lines)
                     if i > compare_index and line.strip() == max_size_call]
        if not size_hits:
            raise ValueError('r6.l is missing its size-limit check after entry matching')
        end = size_hits[0]
        previous = [i for i in range(compare_index + 1, end) if significant(lines[i])]
        old_code = [lines[i].strip() for i in previous]
        if old_code == corrected:
            return block
        if old_code != broken:
            raise ValueError('r6.l tar matcher differs from both the known broken and repaired forms')

        indent = re.match(r'^\s*', lines[previous[0]]).group(0)
        replacement = [indent + instruction for instruction in corrected]
        # Drop stale source-line annotations with the malformed hunk. They are
        # debug-only and would otherwise describe instructions that no longer exist.
        start = compare_index + 1
        lines[start:end] = replacement
        return '\n'.join(lines)

    return update_method(text, signature, transform)


def fix_xl4_callback_receiver(text):
    """Preserve xl4's receiver before its Compose-key register is reused."""
    signature = 'k(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;'
    bad_copy = 'move-object/from16 p0, p0'
    bad_field = 'iget-object v7, p0, Lxl4;->p:Lw82;'
    receiver_copy = 'move-object/from16 v9, p0'
    fixed_field = 'iget-object v7, v9, Lxl4;->p:Lw82;'

    def check_v9_scratch(lines, receiver_index, field_index):
        resets = [i for i, line in enumerate(lines)
                  if line.strip() == 'const/4 v9, 0x0']
        calls = [i for i, line in enumerate(lines)
                 if re.match(r'^\s*invoke-static/range \{v0 \.\. v9\}, ', line)]
        if (len(resets) != 2 or len(calls) != 2
                or not (receiver_index < resets[0] < calls[0] < field_index
                        < resets[1] < calls[1])):
            raise ValueError('xl4.k v9 is not free for the saved receiver on the reviewed callback path')
        allowed = {receiver_index, field_index, *resets, *calls}
        for index, line in enumerate(lines):
            value = line.strip()
            if (index not in allowed and value
                    and not value.startswith(DEBUG_PREFIXES)
                    and not value.startswith('#')
                    and re.search(r'\bv9\b', value)):
                raise ValueError('xl4.k v9 has an unreviewed use: ' + value)

    def transform(block):
        lines = block.splitlines()
        locals_hits = [i for i, line in enumerate(lines)
                       if re.match(r'^\s*\.locals\s+\d+\s*$', line)]
        if len(locals_hits) != 1:
            raise ValueError('xl4.k must have exactly one .locals directive')
        locals_index = locals_hits[0]
        local_count = int(re.match(r'^\s*\.locals\s+(\d+)', lines[locals_index])[1])
        bad_copies = [i for i, line in enumerate(lines) if line.strip() == bad_copy]
        saved_receivers = [i for i, line in enumerate(lines) if line.strip() == receiver_copy]
        fixed_fields = [i for i, line in enumerate(lines) if line.strip() == fixed_field]

        if bad_copies:
            if (len(bad_copies) != 1 or saved_receivers or fixed_fields
                    or local_count != 11):
                raise ValueError('xl4.k receiver hunk differs from the known broken form')
            if re.search(r'\bv11\b', block):
                raise ValueError('xl4.k local v11 is already in use; cannot save the receiver safely')
            bad_field_index = bad_copies[0] + 1
            while (bad_field_index < len(lines)
                   and (not lines[bad_field_index].strip()
                        or lines[bad_field_index].lstrip().startswith(DEBUG_PREFIXES)
                        or lines[bad_field_index].lstrip().startswith('#'))):
                bad_field_index += 1
            if bad_field_index >= len(lines) or lines[bad_field_index].strip() != bad_field:
                raise ValueError('xl4.k self-copy is not followed by the reviewed receiver field load')
            indent = re.match(r'^\s*', lines[locals_index]).group(0)
            lines.insert(locals_index + 1, indent + receiver_copy)
            lines[bad_field_index + 1] = (
                re.match(r'^\s*', lines[bad_field_index + 1]).group(0) + fixed_field)
            del lines[bad_copies[0] + 1]
            check_v9_scratch(lines, locals_index + 1, bad_field_index)
            return '\n'.join(lines)

        if (local_count == 11 and len(saved_receivers) == 1 and len(fixed_fields) == 1
                and saved_receivers[0] < fixed_fields[0]):
            check_v9_scratch(lines, saved_receivers[0], fixed_fields[0])
            return block
        raise ValueError('xl4.k receiver hunk differs from both the known broken and repaired forms')

    return update_method(text, signature, transform)


def fix_qc0_external_root_name(text):
    """Initialize qc0.k's File child on both external and internal storage paths."""
    signature = 'k()Lfc0;'
    external_files = ('invoke-virtual {v0, v2}, '
                      'Landroid/content/Context;->getExternalFilesDir(Ljava/lang/String;)Ljava/io/File;')
    use_internal = 'if-nez v0, :cond_external_files_ready'
    internal_files = ('invoke-virtual {v0}, '
                      'Landroid/content/Context;->getFilesDir()Ljava/io/File;')
    ready_label = ':cond_external_files_ready'
    root_name = 'const-string v2, "box"'
    file_object = 'new-instance v1, Ljava/io/File;'
    file_constructor = ('invoke-direct {v1, v0, v2}, '
                        'Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V')

    def is_instruction(line):
        value = line.strip()
        return bool(value and not value.startswith(DEBUG_PREFIXES)
                    and not value.startswith(('#', ':')))

    def transform(block):
        lines = block.splitlines()
        instructions = {
            'external_files': external_files,
            'use_internal': use_internal,
            'internal_files': internal_files,
            'ready_label': ready_label,
            'root_name': root_name,
            'file_object': file_object,
            'file_constructor': file_constructor,
        }
        positions = {}
        for name, instruction in instructions.items():
            hits = [i for i, line in enumerate(lines)
                    if line.strip() == instruction]
            if len(hits) != 1:
                raise ValueError('qc0.k is missing or has duplicate ' + name + ' instruction')
            positions[name] = hits[0]

        external = positions['external_files']
        branch = positions['use_internal']
        fallback = positions['internal_files']
        label = positions['ready_label']
        name = positions['root_name']
        file_new = positions['file_object']
        constructor = positions['file_constructor']
        join_start, join_end = sorted((label, name))
        if not (external < branch < fallback < join_start < join_end < file_new < constructor):
            raise ValueError('qc0.k storage-directory branch differs from the reviewed shape')

        fallback_result = [line.strip() for line in lines[fallback + 1:join_start]
                           if is_instruction(line)]
        if fallback_result != ['move-result-object v0']:
            raise ValueError('qc0.k internal-files fallback has an unexpected result sequence')
        if any(is_instruction(line) for line in lines[join_start + 1:join_end]):
            raise ValueError('qc0.k root name and ready label are not a common-path join')
        common_path = [line.strip() for line in lines[join_end + 1:constructor]
                       if is_instruction(line)]
        if common_path != [file_object]:
            raise ValueError('qc0.k reuses a path register before File construction')

        if name < label:
            # The branch skips the null-valued v2 assignment when external files
            # are available. Move the join before the literal so both paths set it.
            lines[name], lines[label] = lines[label], lines[name]
            return chr(10).join(lines)
        if label < name:
            return block
        raise ValueError('qc0.k root-name initialization differs from both known forms')

    return update_method(text, signature, transform)


def fix_eu0_battery_toggle_hunk(text):
    """Restore the battery-toggle Compose call and preserve nn3's change mask."""
    signature = 'a(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;'
    anchor = 'move-object/from16 v17, v5'
    end_marker = 'const v7, -0x236bac2a'
    broken = [
        'invoke-static/range {v16 .. v25}, Lub3;->s(ZLh92;Ljava/lang/String;Ljava/lang/String;Lyz0;ZLla2;III)V',
        'invoke-virtual {v3, v10}, Lla2;->r(Z)V',
        'const v3, 0x13f2fb70',
        'invoke-virtual {v3, v3}, Lla2;->b0(I)V',
        'const v3, 0x7f0f055b',
        'invoke-static {v3, v3}, Lub3;->a0(ILla2;)Ljava/lang/String;',
        'move-result-object v17',
        'const v3, 0x7f0f055c',
        'invoke-static {v3, v3}, Lub3;->a0(ILla2;)Ljava/lang/String;',
        'move-result-object v19',
        'invoke-static {}, Lcom/box/app/vpn/BattToggle;->create()Lcom/box/app/vpn/BattToggle;',
        'move-result-object v16',
        'invoke-static {}, Lcom/box/app/vpn/VpnPrefs;->battOn()Z',
        'move-result v16',
        'const/16 v24, 0x0',
        'const/16 v25, 0x3f58',
        'const/16 v21, 0x0',
        'const/high16 v23, 0xc00000',
        'move-object/from16 v22, v3',
        'move-object v12, v13',
        'move-object v13, v7',
        'invoke-static/range {v11 .. v20}, Lub3;->s(ZLh92;Ljava/lang/String;Ljava/lang/String;Lyz0;ZLla2;III)V',
        'invoke-virtual {v5, v10}, Lla2;->r(Z)V',
    ]
    fixed = [
        'move-object v12, v13',
        'move-object v13, v7',
        'invoke-static/range {v11 .. v20}, Lub3;->s(ZLh92;Ljava/lang/String;Ljava/lang/String;Lyz0;ZLla2;III)V',
        'invoke-virtual {v5, v10}, Lla2;->r(Z)V',
        'const v4, 0x13f2fb70',
        'invoke-virtual {v5, v4}, Lla2;->b0(I)V',
        'const v4, 0x7f0f055b',
        'invoke-static {v4, v5}, Lub3;->a0(ILla2;)Ljava/lang/String;',
        'move-result-object v18',
        'const v4, 0x7f0f055c',
        'invoke-static {v4, v5}, Lub3;->a0(ILla2;)Ljava/lang/String;',
        'move-result-object v19',
        'invoke-static {}, Lcom/box/app/vpn/BattToggle;->create()Lcom/box/app/vpn/BattToggle;',
        'move-result-object v17',
        'invoke-static {}, Lcom/box/app/vpn/VpnPrefs;->battOn()Z',
        'move-result v16',
        'move-object/from16 v20, v15',
        'const/16 v24, 0x0',
        'const/16 v25, 0x3f58',
        'const/16 v21, 0x0',
        'const/high16 v23, 0xc00000',
        'move-object/from16 v22, v5',
        'invoke-static/range {v16 .. v25}, Lub3;->s(ZLh92;Ljava/lang/String;Ljava/lang/String;Lyz0;ZLla2;III)V',
        'invoke-virtual {v5, v10}, Lla2;->r(Z)V',
        # The upstream wrapper later masks v6 with v4 (0xe) to build the
        # child composable flags for nn3.L. Resource IDs above use v4, so
        # restore that live mask before the wrapper consumes it.
        'const/16 v4, 0xe',
    ]
    legacy_fixed = fixed[:-1]

    def instructions(lines):
        return [line.strip() for line in lines
                if line.strip() and not line.strip().startswith(DEBUG_PREFIXES)
                and not line.strip().startswith(('#', ':'))]

    def transform(block):
        lines = block.splitlines()
        anchors = [i for i, line in enumerate(lines) if line.strip() == anchor]
        ends = [i for i, line in enumerate(lines) if line.strip() == end_marker]
        if len(anchors) != 1 or len(ends) != 1 or anchors[0] >= ends[0]:
            raise ValueError('eu0.a no longer has the reviewed battery-toggle merge hunk')
        start, end = anchors[0] + 1, ends[0]
        actual = instructions(lines[start:end])
        if actual == fixed:
            return block
        if actual not in (broken, legacy_fixed):
            raise ValueError('eu0.a battery-toggle hunk differs from known broken/repaired forms')
        anchor_line = lines[anchors[0]]
        indent = anchor_line[:len(anchor_line) - len(anchor_line.lstrip())]
        lines[start:end] = [indent + line for line in fixed]
        return chr(10).join(lines)

    return update_method(text, signature, transform)


def fix_uu0_core_version_script_register(text):
    """Pass the custom version script in uu0's String argument register."""
    signature = 'invokeSuspend(Ljava/lang/Object;)Ljava/lang/Object;'
    marker = "Match the root service's executable path"
    qc0_load = 'sget-object v11, Lqc0;->a:Lqc0;'
    string_call = ('invoke-static {v13, v7, v11, v2, v12}, '
                   'Lly1;->s(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;'
                   'Ljava/lang/String;Ljava/lang/String;)Ljava/lang/StringBuilder;')

    def transform(block):
        lines = block.splitlines()
        bad_strings = [i for i, line in enumerate(lines)
                       if line.strip().startswith('const-string v5, "') and marker in line]
        fixed_strings = [i for i, line in enumerate(lines)
                         if line.strip().startswith('const-string v11, "') and marker in line]
        qc0_loads = [i for i, line in enumerate(lines) if line.strip() == qc0_load]
        calls = [i for i, line in enumerate(lines) if line.strip() == string_call]
        if len(qc0_loads) != 1 or len(calls) != 1:
            raise ValueError('uu0.invokeSuspend no longer has the reviewed qc0/string-builder hunk')
        if len(bad_strings) == 1 and not fixed_strings:
            string_index = bad_strings[0]
            if not qc0_loads[0] < string_index < calls[0]:
                raise ValueError('uu0 core-version string is outside the reviewed call sequence')
            for line in lines[string_index + 1:calls[0]]:
                value = line.strip()
                if (value and not value.startswith(DEBUG_PREFIXES)
                        and re.search(r'\bv5\b', value)):
                    raise ValueError('uu0 v5 is used after the core-version literal assignment')
                if (value and not value.startswith(DEBUG_PREFIXES)
                        and re.search(r'\bv11\b', value)):
                    raise ValueError('uu0 v11 is overwritten before the StringBuilder call')
            lines[string_index] = lines[string_index].replace('const-string v5,',
                                                               'const-string v11,', 1)
            return '\n'.join(lines)
        if (not bad_strings and len(fixed_strings) == 1
                and qc0_loads[0] < fixed_strings[0] < calls[0]):
            for line in lines[fixed_strings[0] + 1:calls[0]]:
                value = line.strip()
                if (value and not value.startswith(DEBUG_PREFIXES)
                        and (re.search(r'\bv5\b', value)
                             or re.search(r'\bv11\b', value))):
                    raise ValueError('uu0 core-version String register is reused before its call')
            return block
        raise ValueError('uu0 core-version String register differs from both known forms')

    return update_method(text, signature, transform)


def public_string_ids(public_xml):
    resources = {}
    root = ET.parse(public_xml).getroot()
    for entry in root:
        if entry.tag == 'public' and entry.attrib.get('type') == 'string':
            resources[entry.attrib['name']] = entry.attrib['id']
    return resources


def core_resource_ids(resources):
    ids = []
    for _, resource_name in CORE_ENTRIES:
        value = resources.get(resource_name)
        if not value or not re.fullmatch(r'0x[0-9a-fA-F]{8}', value):
            raise ValueError('missing public string resource: ' + resource_name)
        ids.append(value)
    return ids


def verify_ui_resources_and_types(root, resources):
    hide_id = resources.get('proxy_selector_hide_unavailable')
    restore_id = resources.get('proxy_config_restore_default')
    if not hide_id or not restore_id:
        raise ValueError('custom settings/restore string resources are missing')

    settings = (root / 'smali/t36.smali').read_text(errors='replace')
    if hide_id not in settings or 'VpnPrefs;->items(Ljava/util/List;Ljava/lang/String;)Ljava/util/List;' not in settings:
        raise ValueError('t36 settings list does not use the mapped hide-unavailable resource/helper')
    for rel in ('smali/k.smali', 'smali/q75.smali'):
        text = (root / rel).read_text(errors='replace')
        if restore_id not in text or 'RestoreCfg;->MENU' not in text:
            raise ValueError(rel + ' does not use the mapped restore-menu resource')

    prefs = (root / 'smali/com/box/app/vpn/VpnPrefs.smali').read_text(errors='replace')
    items = get_method(prefs, 'items(Ljava/util/List;Ljava/lang/String;)Ljava/util/List;')
    if ('new-instance v1, Lyr1;' not in items
            or 'Lyr1;-><init>(Ljava/lang/String;ZZLw82;Ljava/util/List;I)V' not in items
            or 'Lip1;' in items or 'Le62;' in items):
        raise ValueError('VpnPrefs.items is not mapped to the 171 Lyr1/Lw82 option types')
    callback = (root / 'smali/com/box/app/vpn/PanelToggle.smali').read_text(errors='replace')
    if '.implements Lw82;' not in callback or '.implements Le62;' in callback:
        raise ValueError('PanelToggle does not implement the 171 callback interface Lw82')


def fix_r57(text, ids):
    signature = '<clinit>()V'

    def transform(old_block):
        header = old_block.splitlines()[0]
        body = ['    .locals 10', '']
        for reg, (name, _) in enumerate(CORE_ENTRIES):
            body.append(f'    const-string v{reg}, "{name}"')
        body += [
            '    filled-new-array/range {v0 .. v8}, [Ljava/lang/String;',
            '    move-result-object v0',
            '    invoke-static {v0}, Lkm;->e0([Ljava/lang/Object;)Ljava/util/List;',
            '    move-result-object v0',
            '    sput-object v0, Lr57;->a:Ljava/util/List;',
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
            '    sput-object v0, Lr57;->b:Ljava/util/List;',
            '    return-void',
        ]
        return '\n'.join([header] + body + ['.end method'])

    return update_method(text, signature, transform)


def executable_label_definitions(lines):
    labels = {}
    switch_depth = 0
    for index, line in enumerate(lines):
        s = line.strip()
        if s.startswith(('.packed-switch ', '.sparse-switch')):
            switch_depth += 1
            continue
        if switch_depth and s in ('.end packed-switch', '.end sparse-switch'):
            switch_depth -= 1
            continue
        if switch_depth:
            continue
        m = LABEL_RE.fullmatch(s)
        if m:
            labels.setdefault(m.group(1)[1:], []).append(index)
    return labels


def handler_instructions(lines, label_index):
    out = []
    for line in lines[label_index + 1:]:
        s = line.strip()
        if not s or s.startswith(('#', *DEBUG_PREFIXES)):
            continue
        if LABEL_RE.fullmatch(s):
            break
        out.append(s)
    return out


def fix_pd1(text):
    signature = 'g(Ljava/lang/String;Lda1;)Ljava/lang/Object;'

    def transform(block):
        lines = block.splitlines()
        labels = executable_label_definitions(lines)
        for dest in ('goto_dd', 'goto_sd'):
            if len(labels.get(dest, [])) != 1:
                raise ValueError(f'pd1 coroutine continuation :{dest} is missing or ambiguous')

        # Keep the existing target pswitch_0 handler (the one which goes to
        # :goto_4); remove any label-aliased copy and rebuild custom states 9/10
        # immediately before it. Removing whole handler ranges avoids deleting a
        # neighboring :pswitch_9/:pswitch_10 block when labels were coalesced.
        def ps0_candidates():
            out = []
            for pos in executable_label_definitions(lines).get('pswitch_0', []):
                instructions = handler_instructions(lines, pos)
                if (len(instructions) == 2 and instructions[0].startswith('invoke-static {v1}, ')
                        and instructions[1] == 'goto/16 :goto_4'):
                    out.append((pos, instructions[0]))
            return out

        candidates = ps0_candidates()
        if not candidates:
            raise ValueError('pd1 has no reviewed pswitch_0 -> :goto_4 handler')
        keep_pos, throw_on_failure = candidates[-1]
        labels = executable_label_definitions(lines)
        remove_labels = [pos for pos in labels.get('pswitch_0', []) if pos != keep_pos]
        remove_labels += labels.get('pswitch_9', []) + labels.get('pswitch_10', [])
        ranges = []
        all_labels = sorted(i for positions in labels.values() for i in positions)
        for start in sorted(set(remove_labels)):
            end = next((i for i in all_labels if i > start), len(lines))
            ranges.append((start, end))
        for start, end in sorted(ranges, reverse=True):
            del lines[start:end]

        labels = executable_label_definitions(lines)
        candidates = ps0_candidates()
        if len(candidates) != 1:
            raise ValueError('pd1 pswitch_0 merge did not leave exactly one target handler')
        keep_pos, throw_on_failure = candidates[0]
        state_handlers = [
            '    :pswitch_9',
            '    ' + throw_on_failure,
            '    goto/16 :goto_dd',
            '    :pswitch_10',
            '    ' + throw_on_failure,
            '    goto/16 :goto_sd',
        ]
        lines[keep_pos:keep_pos] = state_handlers

        # The switch data is not a label definition; rewrite its entries as the
        # exact 0..10 mapping required by the target state machine.
        packed = [(i, line.strip()) for i, line in enumerate(lines)
                  if line.strip().startswith('.packed-switch ')]
        ends = [i for i, line in enumerate(lines)
                if line.strip() == '.end packed-switch']
        if len(packed) != 1 or len(ends) != 1 or ends[0] <= packed[0][0]:
            raise ValueError('pd1 coroutine method must have exactly one packed-switch block')
        start, directive = packed[0]
        if directive != '.packed-switch 0x0':
            raise ValueError('pd1 coroutine packed-switch no longer starts at state zero')
        expected = ['pswitch_8', 'pswitch_7', 'pswitch_6', 'pswitch_5',
                    'pswitch_4', 'pswitch_3', 'pswitch_2', 'pswitch_1',
                    'pswitch_0', 'pswitch_9', 'pswitch_10']
        end = ends[0]
        lines[start + 1:end] = ['        :' + label for label in expected]

        labels = executable_label_definitions(lines)
        for label, dest in (('pswitch_9', 'goto_dd'), ('pswitch_10', 'goto_sd')):
            if len(labels.get(label, [])) != 1:
                raise ValueError(f'pd1 has no unique executable {label} state')
            instructions = handler_instructions(lines, labels[label][0])
            if (len(instructions) != 2 or instructions[0] != throw_on_failure
                    or instructions[1] != f'goto/16 :{dest}'):
                raise ValueError(f'{label} does not resume through :{dest}')
        if len(labels.get('pswitch_0', [])) != 1:
            raise ValueError('pd1 still has duplicate executable pswitch_0 labels')

        # State 10 re-enters the sing-box DingTalk continuation directly, so
        # v15 cannot rely on the String assigned earlier in the initial invoke.
        # The resumed and synchronous paths both need the first Lfd1 String.
        sd_pos = labels['goto_sd'][0]
        next_label = min((pos for positions in labels.values() for pos in positions
                          if pos > sd_pos), default=len(lines))
        sd_call = ('invoke-direct/range {v14 .. v21}, Lfd1;-><init>('
                   'Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;'
                   'Lwa1;Lga1;Ljava/lang/String;)V')
        sd_calls = [i for i in range(sd_pos + 1, next_label)
                    if lines[i].strip() == sd_call]
        if len(sd_calls) != 1:
            raise ValueError('pd1 :goto_sd must have one reviewed Lfd1 constructor call')
        sd_name = 'const-string v15, "sing-box_dingtalk"'
        sd_names = [i for i in range(sd_pos + 1, next_label)
                    if lines[i].strip() == sd_name]
        if len(sd_names) > 1 or sd_names and sd_names[0] > sd_calls[0]:
            raise ValueError('pd1 :goto_sd has an invalid v15 constructor String assignment')
        if not sd_names:
            indent = re.match(r'^\s*', lines[sd_calls[0]]).group(0)
            lines.insert(sd_calls[0], indent + sd_name)
        return '\n'.join(lines)

    return update_method(text, signature, transform)


def duplicate_labels(root, replacements):
    errors = []
    for path in root.rglob('*.smali'):
        text = replacements.get(path, path.read_text(errors='replace'))
        active = False
        switch_depth = 0
        labels = {}
        for number, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if s.startswith('.method '):
                active = True
                switch_depth = 0
                labels = {}
                continue
            if s == '.end method':
                for label, lines in labels.items():
                    if len(lines) > 1:
                        errors.append(f'{path}:{label}:{lines}')
                active = False
                continue
            if not active:
                continue
            if s.startswith(('.packed-switch ', '.sparse-switch')):
                switch_depth += 1
                continue
            if switch_depth and s in ('.end packed-switch', '.end sparse-switch'):
                switch_depth -= 1
                continue
            if switch_depth:
                continue
            m = LABEL_RE.fullmatch(s)
            if m:
                labels.setdefault(m.group(1), []).append(number)
    return errors


def verify_version(root):
    text = (root / 'apktool.yml').read_text()
    if not re.search(r'^\s+versionCode:\s*171\s*$', text, re.M):
        raise ValueError('candidate apktool.yml is not versionCode 171')
    if not re.search(r'^\s+versionName:\s*26\.11\.16\.25abc84\s*$', text, re.M):
        raise ValueError('candidate apktool.yml is not 26.11.16.25abc84')


def repair(root):
    root = Path(root)
    verify_version(root)
    if not (root / 'smali').is_dir():
        raise ValueError('candidate has no smali tree')
    public = root / 'res/values/public.xml'
    resources = public_string_ids(public)
    ids = core_resource_ids(resources)
    verify_ui_resources_and_types(root, resources)
    replacements = {}
    changed = []
    operations = (
        (root / 'smali/ne5.smali', lambda text: fix_ne5(text), 'ne5 VPN enum register'),
        (root / 'smali/g65.smali', lambda text: fix_g65(text), 'g65 range-call field register'),
        (root / 'smali/r6.smali', lambda text: fix_r6_tar_matcher(text), 'r6 tar entry matcher'),
        (root / 'smali/xl4.smali', lambda text: fix_xl4_callback_receiver(text), 'xl4 callback receiver'),
        (root / 'smali/uu0.smali', lambda text: fix_uu0_core_version_script_register(text), 'uu0 core-version script register'),
        (root / 'smali/qc0.smali', lambda text: fix_qc0_external_root_name(text), 'qc0 external-files root name'),
        (root / 'smali/eu0.smali', lambda text: fix_eu0_battery_toggle_hunk(text), 'eu0 battery-toggle Compose register order'),
        (root / 'smali/r57.smali', lambda text: fix_r57(text, ids), 'r57 nine-entry core registry'),
        (root / 'smali/pd1.smali', lambda text: fix_pd1(text), 'pd1 coroutine dispatch labels'),
    )
    for path, operation, description in operations:
        if not path.is_file():
            raise ValueError('candidate is missing ' + str(path.relative_to(root)))
        old = path.read_text(errors='replace')
        new, did_change = operation(old)
        replacements[path] = new
        if did_change:
            changed.append(description)
    errors = duplicate_labels(root, replacements)
    if errors:
        raise ValueError('duplicate executable smali labels remain: ' + '; '.join(errors[:10]))
    _, errors = reference_moves.scan_project(root, replacements)
    if errors:
        raise ValueError('verifier-unsafe object register moves remain: ' + '; '.join(errors[:10]))

    # Stage each replacement beside its source, then atomically publish all edits
    # only after every structural check has passed.
    staged = []
    try:
        for path, text in replacements.items():
            temp = path.with_name(path.name + '.repair-tmp')
            temp.write_text(text)
            staged.append((temp, path))
        for temp, path in staged:
            temp.replace(path)
    finally:
        for temp, _ in staged:
            if temp.exists():
                temp.unlink()
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path, help='generated 171 apktool tree, e.g. .tools/migrated')
    args = parser.parse_args()
    changed = repair(args.candidate)
    print('Verified 171 stage-6 semantic repairs; changed:', ', '.join(changed) if changed else 'none')


if __name__ == '__main__':
    main()
