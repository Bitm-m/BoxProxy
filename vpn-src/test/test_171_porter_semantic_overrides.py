"""Regression tests for reviewed 139 -> 171 API moves in the candidate porter."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import port_171_stage6_candidate as porter  # noqa: E402


class Stage6SemanticOverridesTest(unittest.TestCase):
    @staticmethod
    def write_class(root, descriptor, declarations=()):
        path = root / 'smali' / (descriptor[1:-1] + '.smali')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('\n'.join([
            f'.class public {descriptor}',
            '.super Ljava/lang/Object;',
            *declarations,
            '',
        ]))
        return path

    def test_manual_maps_are_checked_against_declared_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, new = root / 'old', root / 'new'
            for descriptor in porter.MANUAL_TYPE_OVERRIDES:
                self.write_class(old, descriptor)
            for descriptor in porter.MANUAL_TYPE_OVERRIDES.values():
                declarations = []
                if descriptor == 'Lfb0;':
                    declarations += [
                        '.field public static final a:Lfb0;',
                        '.method public final p(Lh92;)Ljava/lang/Object;',
                    ]
                self.write_class(new, descriptor, declarations)
            targets = {
                'Lbb1;': ['.method public final d(Ljava/lang/String;Lda1;)Ljava/lang/Object;'],
                'Lln;': ['.method public static w()Landroid/content/Context;'],
                'Lq9;': ['.method public final o(Landroid/content/Context;)Liv;'],
                'Liv;': ['.field public static final g:Lq9;'],
                'Lod6;': ['.method public static b()Ljava/io/File;'],
                'Lhq;': ['.method public static final h(Lw82;Lmz3;ZZJFFFLyz0;Lla2;II)V'],
                'Loq;': ['.method public static D(Ljava/io/InputStream;Ljava/io/OutputStream;)J'],
            }
            for descriptor, declarations in targets.items():
                self.write_class(new, descriptor, declarations)

            old_classes, new_classes = porter.validate_manual_map_targets(old, new)
            self.assertTrue(set(porter.MANUAL_TYPE_OVERRIDES).issubset(old_classes))
            self.assertTrue(set(porter.MANUAL_TYPE_OVERRIDES.values()).issubset(new_classes))

    def test_url_download_alias_uses_only_171_single_url_overload(self):
        mapper = porter.Mapper(
            {},
            {
                'types': {'Lca1;': {'new': 'Lbb1;'}, 'Lz81;': {'new': 'Lda1;'}},
                'fields': {},
                'members': {key: {'new': value}
                            for key, value in porter.MANUAL_MEMBER_OVERRIDES.items()},
            },
        )
        mapped = mapper.line(
            'invoke-virtual {v2, v0, v3}, '
            'Lca1;->c(Ljava/lang/String;Lz81;)Ljava/lang/Object;'
        )
        self.assertIn('Lbb1;->d(Ljava/lang/String;Lda1;)Ljava/lang/Object;', mapped)
        same_named_other_overload = mapper.line(
            'invoke-virtual {v2, v0, v5, v3}, '
            'Lbb1;->c(Ljava/lang/String;Ljava/lang/String;Lda1;)Ljava/lang/Object;'
        )
        self.assertIn(
            'Lbb1;->c(Ljava/lang/String;Ljava/lang/String;Lda1;)Ljava/lang/Object;',
            same_named_other_overload)

    def test_legacy_stream_copy_call_maps_to_v171_helper(self):
        mapper = porter.Mapper(
            {},
            {
                'types': {},
                'fields': {},
                'members': {key: {'new': value}
                            for key, value in porter.MANUAL_MEMBER_OVERRIDES.items()},
            },
        )
        mapped = mapper.line(
            'invoke-static {v2, v3}, '
            'Lcs;->u(Ljava/io/InputStream;Ljava/io/OutputStream;)J'
        )
        self.assertEqual(
            mapped,
            'invoke-static {v2, v3}, '
            'Loq;->D(Ljava/io/InputStream;Ljava/io/OutputStream;)J')
        self.assertNotIn('Lcs;->u(', mapped)

    @staticmethod
    def write_update_core_source_targets(root):
        sd1 = root / 'smali/sd1.smali'
        sd1.parent.mkdir(parents=True, exist_ok=True)
        sd1.write_text('''\\
.class public abstract Lsd1;
.method public static b()Ljava/util/List;
    .locals 24
    new-instance v3, Lqd1;
    new-instance v4, Lqd1;
    new-instance v5, Lqd1;
    new-instance v6, Lqd1;
    new-instance v7, Lqd1;
    new-instance v8, Lqd1;
    new-instance v9, Lqd1;
    filled-new-array/range {v3 .. v9}, [Lqd1;
    return-object v0
.end method
.method public static f(Ljava/util/List;)V
    return-void
.end method
''')
        ba7 = root / 'smali/ba7.smali'
        ba7.write_text('''\\
.class public final Lba7;
.method public static k()V
    .locals 37
    const-string v1, "sources_v1"
    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences;->getString(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;
    move-result-object v0
    if-nez v0, :cond_saved_sources
    invoke-static {}, Lsd1;->b()Ljava/util/List;
    move-result-object v0
    invoke-static {v0}, Lsd1;->f(Ljava/util/List;)V
    goto :goto_4
    :cond_saved_sources
    new-instance v1, Lorg/json/JSONArray;
    invoke-direct {v1, v0}, Lorg/json/JSONArray;-><init>(Ljava/lang/String;)V
    invoke-static {}, Lsd1;->b()Ljava/util/List;
    move-result-object v0
    :goto_4
    invoke-static {v0}, Lmb3;->L(Ljava/lang/Object;)Liw4;
    invoke-static/range {v0 .. v9}, Luj;->B(Lob7;Lqd1;ZLw82;Lw82;Lw82;Lw82;Lw82;Lla2;I)V
    return-void
.end method
''')
        return sd1, ba7

    def test_update_core_dingtalk_sources_follow_v171_defaults_and_saved_list_loader(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sd1, ba7 = self.write_update_core_source_targets(root)

            detail = porter.adapt_update_core_dingtalk_sources(root)
            sd1_text = sd1.read_text()
            source_defaults = porter.method_blocks(sd1_text)['b()Ljava/util/List;']
            self.assertIn('mihomo_dingtalk', source_defaults)
            smali_unicode_escape = chr(92)
            smali_regex_escape = chr(92) * 2
            chinese_suffix = ''.join(smali_unicode_escape + code
                                     for code in ('u9489', 'u9489', 'u76f4', 'u8fde'))
            self.assertIn('Mihomo Smart + eBPF + ' + chinese_suffix, source_defaults)
            self.assertIn('jieluojun/mihomo', source_defaults)
            self.assertIn('Prerelease-Alpha', source_defaults)
            mihomo_pattern = ('mihomo-android-arm64-v8-alpha-smart-[A-Za-z0-9._-]+'
                              + smali_regex_escape + '.gz')
            self.assertIn(mihomo_pattern, source_defaults)
            self.assertIn('const-string v16, "tag"', source_defaults)
            self.assertIn('const-string v17, "Prerelease-Alpha"', source_defaults)
            self.assertIn('const/16 v19, 0x1', source_defaults)
            self.assertIn('const-string v20, ""', source_defaults)  # no archive entry
            self.assertIn('const-string v21, ""', source_defaults)  # no pinned checksum
            self.assertIn('sing-box_dingtalk', source_defaults)
            self.assertIn('Sing-Box Smart + eBPF + ' + chinese_suffix, source_defaults)
            self.assertIn('jieluojun/sing-box', source_defaults)
            self.assertIn('const-string v17, "latest"', source_defaults)
            self.assertIn('sing-box-.+-android-arm64-v8a-ebpf' + smali_regex_escape
                          + '.tar' + smali_regex_escape + '.gz', source_defaults)
            self.assertIn('const/16 v20, 0x1', source_defaults)
            self.assertIn('const-string v21, ""', source_defaults)  # no archive entry
            self.assertIn('const-string v22, ""', source_defaults)  # no pinned checksum
            self.assertIn('filled-new-array/range {v3 .. v11}, [Lqd1;', source_defaults)

            migration = porter.method_blocks(sd1_text)['h(Ljava/util/List;)Ljava/util/List;']
            migration_instructions = [line.strip() for line in migration.splitlines()
                                      if line.strip() and not line.strip().startswith(('.', '#', ':'))]
            for marker in ('dingtalk_sources_migrated_v1', 'mihomo_dingtalk',
                           'sing-box_dingtalk', 'Lsd1;->b()Ljava/util/List;',
                           'Lsd1;->f(Ljava/util/List;)V',
                           'Ljava/util/ArrayList;-><init>(Ljava/util/Collection;)V',
                           'invoke-static {v7, v10}, Lf13;->p('
                           'Ljava/lang/Object;Ljava/lang/Object;)Z',
                           'if-eqz v10, :loop_existing_sources',
                           'goto :cond_next_source',
                           'Ljava/util/ArrayList;->add(Ljava/lang/Object;)Z',
                           '->putBoolean(Ljava/lang/String;Z)'):
                self.assertIn(marker, migration)
            self.assertIn('if-eqz v2, :cond_migrate_sources', migration_instructions)
            self.assertIn('return-object p0', migration_instructions)
            self.assertIn(
                'invoke-interface {v3}, Ljava/lang/Iterable;->iterator()Ljava/util/Iterator;',
                migration_instructions)
            self.assertIn('if-eqz v4, :cond_mark_sources_migrated', migration_instructions)
            self.assertLess(
                migration_instructions.index(
                    'invoke-static {v7, v10}, Lf13;->p('
                    'Ljava/lang/Object;Ljava/lang/Object;)Z'),
                migration_instructions.index(
                    'invoke-virtual {v3, v6}, '
                    'Ljava/util/ArrayList;->add(Ljava/lang/Object;)Z'))
            self.assertLess(
                migration_instructions.index('if-eqz v10, :loop_existing_sources'),
                migration_instructions.index('goto :cond_next_source'))
            self.assertLess(
                migration_instructions.index('invoke-static {v3}, Lsd1;->f(Ljava/util/List;)V'),
                migration_instructions.index(
                    'invoke-interface {v1, v2, v4}, '
                    'Landroid/content/SharedPreferences$Editor;->putBoolean('
                    'Ljava/lang/String;Z)Landroid/content/SharedPreferences$Editor;'))
            loader = next(block for block in porter.method_blocks(ba7.read_text()).values()
                          if 'sources_v1' in block)
            hook = 'invoke-static {v0}, Lsd1;->h(Ljava/util/List;)Ljava/util/List;'
            state = 'invoke-static {v0}, Lmb3;->L(Ljava/lang/Object;)Liw4;'
            self.assertIn('if-nez v0, :cond_saved_sources', loader)
            fresh_defaults = loader.split('if-nez v0, :cond_saved_sources', 1)[1].split(
                ':cond_saved_sources', 1)[0]
            saved_sources = loader.split(':cond_saved_sources', 1)[1].split(
                '\n    :goto_4\n', 1)[0]
            self.assertIn('invoke-static {}, Lsd1;->b()Ljava/util/List;', fresh_defaults)
            self.assertIn('invoke-static {v0}, Lsd1;->f(Ljava/util/List;)V', fresh_defaults)
            self.assertIn('new-instance v1, Lorg/json/JSONArray;', saved_sources)
            self.assertIn('Lorg/json/JSONArray;-><init>(Ljava/lang/String;)V', saved_sources)
            self.assertEqual(loader.count(hook), 1)
            self.assertLess(loader.index(hook), loader.index(state))
            self.assertIn('Luj;->B(Lob7;Lqd1;', loader)
            self.assertIn('before ba7 renders the Qd1 list', detail)

            self.assertEqual(porter.adapt_update_core_dingtalk_sources(root), detail)
            self.assertEqual(sd1.read_text().count('mihomo_dingtalk'), 2)
            self.assertEqual(sd1.read_text().count('sing-box_dingtalk'), 2)
            self.assertEqual(ba7.read_text().count(hook), 1)

    def test_cfg_icon_builder_rewrite_is_scoped_to_custom_icon(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            custom = root / 'custom'
            output = root / 'output'
            relative = Path('smali/com/box/app/cfg/CfgIcon.smali')
            source = custom / relative
            source.parent.mkdir(parents=True)
            source.write_text('new-instance v3, Lmw;\ninvoke-virtual {v3}, Lmw;->a()V\n')
            target = output / relative
            target.parent.mkdir(parents=True)
            target.write_text('''\
.class public final Lcom/box/app/cfg/CfgIcon;
new-instance v3, Lhw;
invoke-direct {v3}, Lhw;-><init>()V
invoke-virtual {v3, v0, v1}, Lhw;->h(FF)V
invoke-virtual {v3, v0, v1}, Lhw;->f(FF)V
invoke-virtual {v3}, Lhw;->a()V
iget-object v3, v3, Lhw;->a:Ljava/util/ArrayList;
''')
            other = output / 'smali/Other.smali'
            other.parent.mkdir(parents=True, exist_ok=True)
            other.write_text('Lhw;->c()Ljava/lang/Object;\n')

            detail = porter.adapt_cfg_icon_builder(custom, output)
            migrated = target.read_text()
            self.assertIn('Lbx4;->h(FF)V', migrated)
            self.assertIn('Lbx4;->a:Ljava/util/ArrayList;', migrated)
            self.assertNotIn('Lhw;', migrated)
            self.assertIn('Lhw;->c()', other.read_text())
            self.assertIn('Lbx4', detail)

    @staticmethod
    def write_compose_lambda_target(root):
        path = root / 'smali/tj.smali'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('''\
.class public final Ltj;
.method public static final J(ILt92;Lla2;)Lyz0;
    .locals 2
    const/4 v1, 0x1
    invoke-direct {v0, p0, v1, p1}, Lyz0;-><init>(IZLjava/lang/Object;)V
    invoke-virtual {p2, v0}, Lla2;->k0(Ljava/lang/Object;)V
    return-object v0
.end method
''')
        composer = root / 'smali/la2.smali'
        composer.write_text('''\
.class public final Lla2;
.method public final S(IZ)Z
.end method
.method public final V()V
.end method
''')
        callback = root / 'smali/l92.smali'
        callback.write_text('''\
.class public interface abstract Ll92;
.super Ljava/lang/Object;
.implements Lt92;
''')
        return path

    def test_cfg_nav_lambda_key_is_available_in_pinned_171(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / '171'
            self.write_compose_lambda_target(target)
            detail = porter.validate_cfg_nav_composable_lambda_target(target)
            self.assertIn('171 Ltj.J factory', detail)
            self.assertIn('Lla2.S/V Composer methods', detail)
            self.assertIn('Ll92-to-Lt92 callback interface', detail)
            self.assertIn(porter.CFG_ICON_LAMBDA_KEY, detail)

            collision = target / 'smali/collision.smali'
            collision.write_text(f'const v0, {porter.CFG_ICON_LAMBDA_KEY}\n')
            with self.assertRaisesRegex(ValueError, 'collides with a 171 integer constant'):
                porter.validate_cfg_nav_composable_lambda_target(target)

    def test_cfg_nav_wraps_icon_with_171_composable_lambda_factory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / '171'
            self.write_compose_lambda_target(target)
            icon = root / 'smali/com/box/app/cfg/CfgIcon.smali'
            icon.parent.mkdir(parents=True)
            icon.write_text('''.class public final Lcom/box/app/cfg/CfgIcon;\n.implements Ll92;\n''')
            path = root / 'smali/com/box/app/cfg/CfgNav.smali'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('''\
.class public final Lcom/box/app/cfg/CfgNav;
# Guard copied from the legacy Composer API (Lt72;->T / W).
.method private static e(Lt72;Ljava/lang/Object;Landroid/content/Context;ILjava/lang/String;F)V
    .locals 20
    new-instance v13, Lcom/box/app/cfg/CfgIcon;
    const/4 v2, 0x0
    invoke-direct {v13, v2}, Lcom/box/app/cfg/CfgIcon;-><init>(I)V
    move-object/from16 v14, p0
    const/4 v15, 0x0
    const/16 v16, 0xfc
    invoke-static/range {v4 .. v16}, Lhq;->h(Lw82;Lmz3;ZZJFFFLyz0;Lla2;II)V
    return-void
.end method
.method public final invoke(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;
    .locals 12
    check-cast v6, Lt72;
    invoke-virtual {v6, v3, v4}, Lt72;->T(IZ)Z
    invoke-static {v7}, Lcom/box/app/cfg/CfgGlue;->isMihomo(Ljava/lang/Object;)Z
    move-result v3
    if-nez v3, :cond_mihomo
    invoke-static {v7}, Lcom/box/app/cfg/CfgGlue;->isSingBox(Ljava/lang/Object;)Z
    move-result v3
    if-eqz v3, :goto_done
    const/4 v9, 0x1
    const-string v10, "\\u53ef\\u89c6"
    const/high16 v11, 0x42600000
    invoke-static/range {v6 .. v11}, Lcom/box/app/cfg/CfgNav;->e(Lt72;Ljava/lang/Object;Landroid/content/Context;ILjava/lang/String;F)V
    goto :goto_done
    :cond_mihomo
    const/4 v9, 0x1
    const-string v10, "\\u53ef\\u89c6"
    const/high16 v11, 0x42600000
    invoke-static/range {v6 .. v11}, Lcom/box/app/cfg/CfgNav;->e(Lt72;Ljava/lang/Object;Landroid/content/Context;ILjava/lang/String;F)V
    :goto_done
    invoke-virtual {v6}, Lt72;->W()V
    return-object v0
.end method
''')

            legacy_text = path.read_text()
            mapped, changed = porter.adapt_cfg_nav_composer_api(legacy_text)
            self.assertTrue(changed)
            self.assertNotIn('Lt72;', mapped)
            self.assertIn('.method private static e(Lla2;', mapped)
            self.assertIn('Lla2;->S(IZ)Z', mapped)
            self.assertIn('Lla2;->V()V', mapped)
            mapped_again, changed_again = porter.adapt_cfg_nav_composer_api(mapped)
            self.assertFalse(changed_again)
            self.assertEqual(mapped_again, mapped)
            unexpected = legacy_text.replace('Lt72;->T(IZ)Z', 'Lt72;->R(IZ)Z')
            with self.assertRaisesRegex(ValueError, 'differ from both reviewed'):
                porter.adapt_cfg_nav_composer_api(unexpected)

            detail = porter.adapt_cfg_nav_composable_lambda(root, target)
            text = path.read_text()
            self.assertIn('.locals 20', text)
            self.assertIn(f'const v3, {porter.CFG_ICON_LAMBDA_KEY}', text)
            self.assertIn(
                'invoke-static {v3, v13, v14}, Ltj;->J(ILt92;Lla2;)Lyz0;', text)
            self.assertIn('move-result-object v13', text)
            self.assertNotIn('new-instance v17, Lyz0;', text)
            self.assertNotIn('Lt72;', text)
            self.assertIn('.method private static e(Lla2;', text)
            self.assertIn('check-cast v6, Lla2;', text)
            self.assertIn('Lla2;->S(IZ)Z', text)
            self.assertIn('Lla2;->V()V', text)
            self.assertEqual(text.count('CfgNav;->e(Lla2;'), 2)
            cfg_nav_e = text.split('.method private static e(Lla2;', 1)[1].split(
                '.end method', 1)[0]
            self.assertLess(
                cfg_nav_e.index('move-object/from16 v14, p0'),
                cfg_nav_e.index('invoke-static {v3, v13, v14}, Ltj;->J('))
            self.assertIn('wrapped CfgIcon with 171 Ltj.J', detail)
            self.assertIn('mapped the Composer API to Lla2/S/V', detail)
            self.assertIn('Mihomo and Sing-Box each keep one kind-1 visual action at 56dp', detail)
            self.assertIn('kind 1 maps to CfgIcon selector 0', detail)
            self.assertIn('no anchor toolbar action', detail)
            self.assertIn('factory arguments and Lyz0 result register flow verified', detail)
            self.assertIn('unused by the pinned 171 Smali tree', detail)
            self.assertEqual(
                porter.adapt_cfg_nav_composable_lambda(root, target),
                'already wraps CfgIcon with Ltj.J and uses the 171 Lla2 Composer API; '
                'Mihomo and Sing-Box each keep one kind-1 visual action at 56dp; '
                'kind 1 maps to CfgIcon selector 0; no anchor toolbar action; '
                'CfgIcon/Lla2 factory arguments and Lyz0 result register flow verified; ' +
                porter.validate_cfg_nav_composable_lambda_target(target))
            bad_flow = path.read_text().replace(
                'move-object/from16 v14, p0', 'move-object/from16 v14, p1')
            path.write_text(bad_flow)
            with self.assertRaisesRegex(ValueError, 'adapter instruction is missing or ambiguous'):
                porter.adapt_cfg_nav_composable_lambda(root, target)


if __name__ == '__main__':
    unittest.main()
