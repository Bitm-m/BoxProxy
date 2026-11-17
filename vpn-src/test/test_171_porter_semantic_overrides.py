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
        return path

    def test_cfg_nav_lambda_key_is_available_in_pinned_171(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / '171'
            self.write_compose_lambda_target(target)
            detail = porter.validate_cfg_nav_composable_lambda_target(target)
            self.assertIn('171 Ltj.J factory verified', detail)
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
            path = root / 'smali/com/box/app/cfg/CfgNav.smali'
            path.parent.mkdir(parents=True)
            path.write_text('''\
.class public final Lcom/box/app/cfg/CfgNav;
.method private static e()V
    .locals 20
    invoke-static/range {v4 .. v16}, Lhq;->h(Lw82;Lmz3;ZZJFFFLyz0;Lla2;II)V
    return-void
.end method
''')

            detail = porter.adapt_cfg_nav_composable_lambda(root, target)
            text = path.read_text()
            self.assertIn('.locals 20', text)
            self.assertIn(f'const v3, {porter.CFG_ICON_LAMBDA_KEY}', text)
            self.assertIn(
                'invoke-static {v3, v13, v14}, Ltj;->J(ILt92;Lla2;)Lyz0;', text)
            self.assertIn('move-result-object v13', text)
            self.assertNotIn('new-instance v17, Lyz0;', text)
            self.assertIn('wrapped CfgIcon with 171 Ltj.J', detail)
            self.assertIn('unused by the pinned 171 Smali tree', detail)
            self.assertEqual(
                porter.adapt_cfg_nav_composable_lambda(root, target),
                'already wraps CfgIcon with Ltj.J; ' +
                porter.validate_cfg_nav_composable_lambda_target(target))


if __name__ == '__main__':
    unittest.main()
