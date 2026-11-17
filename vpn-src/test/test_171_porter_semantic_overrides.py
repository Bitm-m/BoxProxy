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
    invoke-static/range {v6 .. v11}, Lcom/box/app/cfg/CfgNav;->e(Lt72;Ljava/lang/Object;Landroid/content/Context;ILjava/lang/String;F)V
    invoke-static/range {v6 .. v11}, Lcom/box/app/cfg/CfgNav;->e(Lt72;Ljava/lang/Object;Landroid/content/Context;ILjava/lang/String;F)V
    invoke-static/range {v6 .. v11}, Lcom/box/app/cfg/CfgNav;->e(Lt72;Ljava/lang/Object;Landroid/content/Context;ILjava/lang/String;F)V
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
            self.assertEqual(text.count('CfgNav;->e(Lla2;'), 3)
            cfg_nav_e = text.split('.method private static e(Lla2;', 1)[1].split(
                '.end method', 1)[0]
            self.assertLess(
                cfg_nav_e.index('move-object/from16 v14, p0'),
                cfg_nav_e.index('invoke-static {v3, v13, v14}, Ltj;->J('))
            self.assertIn('wrapped CfgIcon with 171 Ltj.J', detail)
            self.assertIn('mapped the Composer API to Lla2/S/V', detail)
            self.assertIn('factory arguments and Lyz0 result register flow verified', detail)
            self.assertIn('unused by the pinned 171 Smali tree', detail)
            self.assertEqual(
                porter.adapt_cfg_nav_composable_lambda(root, target),
                'already wraps CfgIcon with Ltj.J and uses the 171 Lla2 Composer API; '
                'CfgIcon/Lla2 factory arguments and Lyz0 result register flow verified; ' +
                porter.validate_cfg_nav_composable_lambda_target(target))
            bad_flow = path.read_text().replace(
                'move-object/from16 v14, p0', 'move-object/from16 v14, p1')
            path.write_text(bad_flow)
            with self.assertRaisesRegex(ValueError, 'adapter instruction is missing or ambiguous'):
                porter.adapt_cfg_nav_composable_lambda(root, target)


if __name__ == '__main__':
    unittest.main()
