import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_smali_branch_offsets as branch_offsets  # noqa: E402
import check_smali_reference_moves as reference_moves  # noqa: E402
from repair_171_stage6_candidate import repair  # noqa: E402


class ReferenceMoveCheckTest(unittest.TestCase):
    def test_resolves_parameter_register_aliases(self):
        method = '''\
.method public final callback(Ljava/lang/Object;)V
    .locals 11
    move-object/from16 v11, p0
.end method
'''
        errors = reference_moves.scan_text(method)
        self.assertEqual(len(errors), 1)
        self.assertIn('aliases v11', errors[0])

        reserved = method.replace('.locals 11', '.locals 12')
        self.assertEqual(reference_moves.scan_text(reserved), [])


class Stage6RepairTest(unittest.TestCase):
    def make_candidate(self, root):
        (root / 'smali').mkdir(parents=True)
        (root / 'res/values').mkdir(parents=True)
        (root / 'apktool.yml').write_text(
            'version: 2.9.3\n\napkFileName: BoxProxy.apk\n'
            'versionInfo:\n  versionCode: 171\n  versionName: 26.11.16.25abc84\n')
        public = ET.Element('resources')
        ids = {
            'proxy_core_mihomo': '0x7f0f034a',
            'proxy_core_mihomo_smart': '0x7f0f034b',
            'proxy_core_mihomo_dingtalk': '0x7f0f0554',
            'proxy_core_sing_box': '0x7f0f034c',
            'proxy_core_sing_box_ref1nd': '0x7f0f034d',
            'proxy_core_sing_box_dingtalk': '0x7f0f0555',
            'proxy_core_xray': '0x7f0f0350',
            'proxy_core_v2fly': '0x7f0f034f',
            'proxy_core_hysteria': '0x7f0f0349',
            'proxy_selector_hide_unavailable': '0x7f0f0553',
            'proxy_config_restore_default': '0x7f0f0556',
        }
        for name, resource_id in ids.items():
            ET.SubElement(public, 'public', {
                'type': 'string', 'name': name, 'id': resource_id,
            })
        ET.ElementTree(public).write(root / 'res/values/public.xml', encoding='utf-8')
        (root / 'smali/t36.smali').write_text('''\
.class public Lt36;
.method public O()Ljava/util/List;
    const v1, 0x7f0f0553
    invoke-static {v1, v10}, Lub3;->a0(ILla2;)Ljava/lang/String;
    invoke-static {v0, v1}, Lcom/box/app/vpn/VpnPrefs;->items(Ljava/util/List;Ljava/lang/String;)Ljava/util/List;
.end method
''')
        (root / 'smali/k.smali').write_text('''\
.class public Lk;
    const p1, 0x7f0f0556
    sget-object v10, Lcom/box/app/vpn/RestoreCfg;->MENU:Lcom/box/app/vpn/RestoreCfg;
''')
        (root / 'smali/q75.smali').write_text('''\
.class public Lq75;
    const p0, 0x7f0f0556
    sget-object v5, Lcom/box/app/vpn/RestoreCfg;->MENU:Lcom/box/app/vpn/RestoreCfg;
''')
        (root / 'smali/com/box/app/vpn').mkdir(parents=True)
        (root / 'smali/com/box/app/vpn/VpnPrefs.smali').write_text('''\
.class public final Lcom/box/app/vpn/VpnPrefs;
.method public static items(Ljava/util/List;Ljava/lang/String;)Ljava/util/List;
    new-instance v1, Lyr1;
    invoke-direct/range {v1 .. v7}, Lyr1;-><init>(Ljava/lang/String;ZZLw82;Ljava/util/List;I)V
.end method
''')
        (root / 'smali/com/box/app/vpn/PanelToggle.smali').write_text('''\
.class public final Lcom/box/app/vpn/PanelToggle;
.implements Lw82;
''')

        (root / 'smali/ne5.smali').write_text('''\
.class public final enum Lne5;
.super Ljava/lang/Enum;
.field public static final enum t:Lne5;
.method static constructor <clinit>()V
    .locals 9
    new-instance v6, Lne5;
    const/4 v7, 0x0
    const-string v8, "Vpn"
    const-string v2, "vpn"
    invoke-direct {v6, v7, v8, v2}, Lne5;-><init>(ILjava/lang/String;Ljava/lang/String;)V
    sput-object v6, Lne5;->t:Lne5;
    return-void
.end method
''')
        (root / 'smali/g65.smali').write_text('''\
.class public final Lg65;
.method public final invoke(Ljava/lang/Object;)Ljava/lang/Object;
    .locals 27
    iget-object v5, v2, Ldc0;->h:Ljava/lang/String;
    invoke-static/range {v2 .. v26}, Ldc0;->a(Ldc0;)Ldc0;
    return-object v0
.end method
''')
        (root / 'smali/r57.smali').write_text('''\
.class public abstract Lr57;
.field public static final a:Ljava/util/List;
.field public static final b:Ljava/util/List;
.method static constructor <clinit>()V
    .locals 8
    return-void
.end method
''')
        (root / 'smali/r6.smali').write_text('''\
.class public final Lr6;
.method public static l(Ljava/io/InputStream;Ljava/lang/String;Ljava/io/File;Ljava/lang/Long;Z)V
    .locals 8
    invoke-static {v3, p1}, Lf13;->p(Ljava/lang/Object;Ljava/lang/Object;)Z
    move-result v3
    if-eqz v3, :cond_7
    const-wide/32 v6, 0x100000
    cmp-long v6, v4, v6
    if-ltz v6, :cond_6
    :boxproxy_match
    if-nez v6, :boxproxy_match
    const-string v6, "-"
    invoke-virtual {p1, v6}, Ljava/lang/String;->concat(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v6
    invoke-virtual {v3, v6}, Ljava/lang/String;->startsWith(Ljava/lang/String;)Z
    move-result v6
    invoke-virtual {p3}, Ljava/lang/Long;->longValue()J
    move-result-wide v0
    return-void
    :cond_7
    return-void
.end method
''')
        (root / 'smali/xl4.smali').write_text('''\
.class public final Lxl4;
.method public final k(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;
    .locals 11
    if-eqz p1, :cond_a
    const/4 v9, 0x0
    invoke-static/range {v0 .. v9}, Lxl4;->first()V
    goto :done
    :cond_a
    const/16 p0, 0xf
    move-object/from16 p0, p0
    iget-object v7, p0, Lxl4;->p:Lw82;
    const/4 v9, 0x0
    invoke-static/range {v0 .. v9}, Lxl4;->second()V
    :done
    return-object v7
.end method
''')

        (root / 'smali/uu0.smali').write_text('''\
.class public final Luu0;
.method public final invokeSuspend(Ljava/lang/Object;)Ljava/lang/Object;
    .locals 23
    sget-object v11, Lqc0;->a:Lqc0;
    const-string v5, "Match the root service's executable path (emulated storage may be noexec)."
    const-string v12, "separator"
    const-string v13, "core_path"
    invoke-static {v13, v7, v11, v2, v12}, Lly1;->s(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)Ljava/lang/StringBuilder;
    return-object v2
.end method
''')

        (root / 'smali/pd1.smali').write_text('''\
.class public final Lpd1;
.method public final g(Ljava/lang/String;Lda1;)Ljava/lang/Object;
    .locals 3
    packed-switch v5, :pswitch_data_0
    return-object v7
    :pswitch_0
    invoke-static {v1}, Lcb3;->L(Ljava/lang/Object;)V
    goto/16 :goto_sd
    :pswitch_9
    invoke-static {v1}, Lcb3;->L(Ljava/lang/Object;)V
    goto/16 :goto_dd
    :pswitch_10
    invoke-static {v1}, Lcb3;->L(Ljava/lang/Object;)V
    goto/16 :goto_sd
    :pswitch_0
    invoke-static {v1}, Lcb3;->L(Ljava/lang/Object;)V
    goto/16 :goto_4
    :goto_4
    return-object v0
    :goto_dd
    return-object v0
    :goto_sd
    return-object v0
    :pswitch_data_0
    .packed-switch 0x0
        :pswitch_8
        :pswitch_7
        :pswitch_6
        :pswitch_5
        :pswitch_4
        :pswitch_3
        :pswitch_2
        :pswitch_1
        :pswitch_0
        :pswitch_0
    .end packed-switch
.end method
''')

    def test_repairs_known_register_and_state_merge_hazards(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_candidate(root)
            before_errors = branch_offsets.scan_project(root)[1]
            self.assertEqual(len(before_errors), 1)
            self.assertIn('r6.smali', before_errors[0])
            reference_errors = reference_moves.scan_project(root)[1]
            self.assertEqual(len(reference_errors), 1)
            self.assertIn('xl4.smali', reference_errors[0])
            self.assertIn('aliases v11', reference_errors[0])
            broken_uu0 = (root / 'smali/uu0.smali').read_text()
            self.assertIn('const-string v5, "Match the root service', broken_uu0)

            changed = repair(root)
            self.assertEqual(len(changed), 7)
            self.assertIn('r6 tar entry matcher', changed)
            self.assertIn('xl4 callback receiver', changed)
            self.assertIn('uu0 core-version script register', changed)

            ne5 = (root / 'smali/ne5.smali').read_text()
            self.assertIn('.locals 10', ne5)
            self.assertIn('const-string v9, "vpn"', ne5)
            self.assertNotIn('const-string v2, "vpn"', ne5)

            g65 = (root / 'smali/g65.smali').read_text()
            self.assertIn('iget-object v10, v2, Ldc0;->h:Ljava/lang/String;', g65)
            self.assertNotIn('iget-object v5, v2, Ldc0;->h:Ljava/lang/String;', g65)

            r6 = (root / 'smali/r6.smali').read_text()
            self.assertIn('move-result v6', r6)
            self.assertIn('if-nez v6, :boxproxy_match', r6)
            self.assertIn('if-eqz v6, :cond_7', r6)
            self.assertIn('if-ltz v6, :cond_7', r6)
            self.assertEqual(branch_offsets.scan_project(root)[1], [])

            xl4 = (root / 'smali/xl4.smali').read_text()
            self.assertIn('.locals 11', xl4)
            self.assertIn('move-object/from16 v9, p0', xl4)
            self.assertLess(xl4.index('move-object/from16 v9, p0'),
                            xl4.index('const/16 p0, 0xf'))
            self.assertNotIn('move-object/from16 p0, p0', xl4)
            self.assertIn('iget-object v7, v9, Lxl4;->p:Lw82;', xl4)
            self.assertEqual(reference_moves.scan_project(root)[1], [])

            uu0 = (root / 'smali/uu0.smali').read_text()
            self.assertIn('const-string v11, "Match the root service', uu0)
            self.assertNotIn('const-string v5, "Match the root service', uu0)
            self.assertLess(uu0.index('const-string v11, "Match the root service'),
                            uu0.index('invoke-static {v13, v7, v11, v2, v12},'))

            r57 = (root / 'smali/r57.smali').read_text()
            self.assertIn('filled-new-array/range {v0 .. v8}, [Ljava/lang/String;', r57)
            self.assertIn('filled-new-array/range {v1 .. v9}, [Ljava/lang/Integer;', r57)
            expected_names = [
                'mihomo', 'mihomo_smart', 'mihomo_dingtalk', 'sing-box',
                'sing-box_ref1nd', 'sing-box_dingtalk', 'xray', 'v2fly', 'hysteria',
            ]
            self.assertEqual(
                [line.strip().split(', ', 1)[1] for line in r57.splitlines()
                 if 'const-string v' in line],
                [f'"{name}"' for name in expected_names],
            )
            for resource_id in ('0x7f0f034a', '0x7f0f034b', '0x7f0f0554',
                                '0x7f0f034c', '0x7f0f034d', '0x7f0f0555',
                                '0x7f0f0350', '0x7f0f034f', '0x7f0f0349'):
                self.assertIn(resource_id, r57)

            pd1 = (root / 'smali/pd1.smali').read_text()
            self.assertIn('goto/16 :goto_dd', pd1)
            self.assertIn('goto/16 :goto_sd', pd1)
            self.assertIn('        :pswitch_9\n        :pswitch_10', pd1)
            self.assertEqual(repair(root), [])


if __name__ == '__main__':
    unittest.main()
