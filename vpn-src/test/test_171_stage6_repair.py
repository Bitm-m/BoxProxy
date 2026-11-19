import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_smali_branch_offsets as branch_offsets  # noqa: E402
import check_smali_reference_moves as reference_moves  # noqa: E402
from repair_171_stage6_candidate import (  # noqa: E402
    fix_zo2_vpn_bridge_result_register,
    fix_zu5_cfg_nav_wrapper_registers,
    repair,
)


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
    .locals 0
    return-object p0
.end method
''')
        (root / 'smali/com/box/app/vpn/PanelToggle.smali').write_text('''\
.class public final Lcom/box/app/vpn/PanelToggle;
.implements Lw82;
''')
        (root / 'smali/zo2.smali').write_text('''\
.class public final Lzo2;
.method public final a(Ljava/lang/String;JLda1;)Ljava/lang/Object;
    .locals 8
    invoke-static/range {p1 .. p1}, Lcom/box/app/vpn/VpnBridge;->control(Ljava/lang/String;)Lvo2;
    move-result-object p2
    if-eqz p2, :cond_vpn_none
    return-object p2
    :cond_vpn_none
    long-to-int p4, p2
    return-object p0
.end method
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

        (root / 'smali/qc0.smali').write_text('''\
.class public final Lqc0;
.method public static k()Lfc0;
    .locals 9
    invoke-static {}, Lln;->w()Landroid/content/Context;
    move-result-object v0
    const/4 v2, 0x0
    invoke-virtual {v0, v2}, Landroid/content/Context;->getExternalFilesDir(Ljava/lang/String;)Ljava/io/File;
    move-result-object v0
    if-nez v0, :cond_external_files_ready
    invoke-static {}, Lln;->w()Landroid/content/Context;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Context;->getFilesDir()Ljava/io/File;
    move-result-object v0
    const-string v2, "box"
    :cond_external_files_ready
    new-instance v1, Ljava/io/File;
    invoke-direct {v1, v0, v2}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V
    return-object v1
.end method
''')

        (root / 'smali/eu0.smali').write_text('''\
.class public final Leu0;
.method public final a(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;
    .locals 37
    const/16 v4, 0xe
    move-object/from16 v17, v5
    invoke-static/range {v16 .. v25}, Lub3;->s(ZLh92;Ljava/lang/String;Ljava/lang/String;Lyz0;ZLla2;III)V
    invoke-virtual {v3, v10}, Lla2;->r(Z)V
    const v3, 0x13f2fb70
    invoke-virtual {v3, v3}, Lla2;->b0(I)V
    const v3, 0x7f0f055b
    invoke-static {v3, v3}, Lub3;->a0(ILla2;)Ljava/lang/String;
    move-result-object v17
    const v3, 0x7f0f055c
    invoke-static {v3, v3}, Lub3;->a0(ILla2;)Ljava/lang/String;
    move-result-object v19
    invoke-static {}, Lcom/box/app/vpn/BattToggle;->create()Lcom/box/app/vpn/BattToggle;
    move-result-object v16
    invoke-static {}, Lcom/box/app/vpn/VpnPrefs;->battOn()Z
    move-result v16
    const/16 v24, 0x0
    const/16 v25, 0x3f58
    const/16 v21, 0x0
    const/high16 v23, 0xc00000
    move-object/from16 v22, v3
    move-object v12, v13
    move-object v13, v7
    invoke-static/range {v11 .. v20}, Lub3;->s(ZLh92;Ljava/lang/String;Ljava/lang/String;Lyz0;ZLla2;III)V
    invoke-virtual {v5, v10}, Lla2;->r(Z)V
    const v7, -0x236bac2a
    const/high16 v0, 0x180000
    and-int/2addr v6, v4
    or-int v23, v6, v0
    return-object v0
.end method
''')

        (root / 'smali/y75.smali').write_text('''\
.class public final Ly75;
.method public final a(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;
    .locals 44
    iget-object v14, v0, Ly75;->t:Lne5;
    invoke-static {v14}, Lcom/box/app/vpn/VpnBridge;->key(Lne5;)I
    move/from16 p3, v1
    move-result v1
    return-object v1
.end method
''')

        (root / 'smali/ij4.smali').write_text('''
.class public final synthetic Lij4;
.method public synthetic constructor <init>(Ljava/util/List;Ljava/lang/String;Lb34;Lqn3;Lme5;Lb34;Lb34;Ljava/lang/String;Le65;Landroid/content/Context;Ljava/lang/String;Lh92;Ljava/lang/String;Lqn3;Lb34;Lb34;Lb34;Lb34;)V
    .locals 1
    iput-object p8, p0, Lij4;->r:Ljava/lang/Object;
    invoke-static {p8}, Lcom/box/app/vpn/RestoreCfg;->vm(Le65;)V
    iput-object p9, p0, Lij4;->s:Ljava/lang/Object;
    iput-object p10, p0, Lij4;->t:Ljava/lang/Object;
    return-void
.end method
''')

        (root / 'smali/zu5.smali').write_text('''
.class public final Lzu5;
.method public final invoke(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;
    .locals 33
    iget-object v7, v0, Lzu5;->j:Lpv5;
    iget-object v2, v7, Lpv5;->l:Liw4;
    invoke-virtual {v2}, Liw4;->getValue()Ljava/lang/Object;
    move-result-object v2
    check-cast v2, Ljava/lang/String;
    new-instance v3, Lx65;
    const/4 v6, 0x7
    invoke-direct {v3, v4, v6}, Lx65;-><init>(Lw82;B)V
    iget-object v8, v0, Lzu5;->l:Landroid/content/Context;
    invoke-static {v3, v7, v8}, Lcom/box/app/cfg/CfgNav;->wrap(Ll92;Lpv5;Landroid/content/Context;)Ll92;
    move-result-object v3
    const v4, -0x7a21ea59
    invoke-static {v4, v3, v1}, Ltj;->J(ILt92;Lla2;)Lyz0;
    move-result-object v3
    new-instance v2, Lsu5;
    iget-object v3, v0, Lzu5;->j:Lpv5;
    const/4 v9, 0x1
    invoke-direct {v2, v3, v9}, Lsu5;-><init>(Lpv5;B)V
    const v9, 0x1e3dbaa1
    invoke-static {v9, v2, v13}, Ltj;->J(ILt92;Lla2;)Lyz0;
    move-result-object v2
    new-instance v9, Lx65;
    invoke-direct {v9, v4, v6}, Lx65;-><init>(Lw82;B)V
    iget-object v8, v0, Lzu5;->l:Landroid/content/Context;
    invoke-static {v2, v3, v8}, Lcom/box/app/cfg/CfgNav;->wrap(Ll92;Lpv5;Landroid/content/Context;)Ll92;
    move-result-object v2
    const v4, 0x6cb9fadf
    invoke-static {v4, v9, v13}, Ltj;->J(ILt92;Lla2;)Lyz0;
    move-result-object v10
    move-object v13, v8
    move-object v8, v2
    invoke-static/range {v8 .. v18}, Lzo;->c(Lyz0;Lmz3;Lyz0;Lyz0;FLue3;Lz57;Lbt4;Lla2;II)V
    return-object v2
.end method
''')

        (root / 'smali/pd1.smali').write_text('''\
.class public final Lpd1;
.method public final g(Ljava/lang/String;Lda1;)Ljava/lang/Object;
    .locals 22
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
    new-instance v14, Lfd1;
    const-string v16, "sing-box"
    const-string v17, "Sing-Box Smart + eBPF"
    const-string v18, "download-url"
    const/4 v19, 0x0
    sget-object v20, Lga1;->j:Lga1;
    const-string v21, "sing-box"
    invoke-direct/range {v14 .. v21}, Lfd1;-><init>(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Lwa1;Lga1;Ljava/lang/String;)V
    return-object v14
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

    def test_zo2_vpn_result_does_not_overwrite_long_parameter(self):
        method = '''\
.method public final a(Ljava/lang/String;JLda1;)Ljava/lang/Object;
    .locals 8
    invoke-static/range {p1 .. p1}, Lcom/box/app/vpn/VpnBridge;->control(Ljava/lang/String;)Lvo2;
    move-result-object p2
    if-eqz p2, :cond_vpn_none
    return-object p2
    :cond_vpn_none
    long-to-int p4, p2
    return-object p0
.end method
'''
        fixed, changed = fix_zo2_vpn_bridge_result_register(method)
        self.assertTrue(changed)
        self.assertIn('move-result-object v5', fixed)
        self.assertIn('if-eqz v5, :cond_vpn_none', fixed)
        self.assertIn('return-object v5', fixed)
        self.assertIn('long-to-int p4, p2', fixed)
        self.assertNotIn('move-result-object p2', fixed)
        fixed_again, changed_again = fix_zo2_vpn_bridge_result_register(fixed)
        self.assertFalse(changed_again)
        self.assertEqual(fixed_again, fixed)
        with self.assertRaisesRegex(ValueError, 'v5 local'):
            fix_zo2_vpn_bridge_result_register(method.replace('.locals 8', '.locals 5'))

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
            broken_qc0 = (root / 'smali/qc0.smali').read_text()
            self.assertLess(broken_qc0.index('\n    const-string v2, "box"'),
                            broken_qc0.index('\n    :cond_external_files_ready\n'))
            broken_eu0 = (root / 'smali/eu0.smali').read_text()
            self.assertIn('invoke-static/range {v16 .. v25}, Lub3;->s(', broken_eu0)
            self.assertLess(broken_eu0.index('invoke-static/range {v16 .. v25}, Lub3;->s('),
                            broken_eu0.index('invoke-static {}, Lcom/box/app/vpn/VpnPrefs;->battOn()Z'))
            broken_y75 = (root / 'smali/y75.smali').read_text()
            self.assertLess(broken_y75.index('invoke-static {v14}, Lcom/box/app/vpn/VpnBridge;->key('),
                            broken_y75.index('move/from16 p3, v1'))
            self.assertLess(broken_y75.index('move/from16 p3, v1'),
                            broken_y75.index('move-result v1'))
            broken_ij4 = (root / 'smali/ij4.smali').read_text()
            self.assertIn('invoke-static {p8}, Lcom/box/app/vpn/RestoreCfg;->vm(Le65;)V',
                          broken_ij4)
            self.assertLess(broken_ij4.index('invoke-static {p8}, Lcom/box/app/vpn/RestoreCfg;'),
                            broken_ij4.index('iput-object p9, p0, Lij4;->s:Ljava/lang/Object;'))
            broken_zu5 = (root / 'smali/zu5.smali').read_text()
            self.assertEqual(broken_zu5.count('CfgNav;->wrap('), 2)
            self.assertIn('invoke-static {v3, v7, v8}, Lcom/box/app/cfg/CfgNav;->wrap(',
                          broken_zu5)
            self.assertIn('invoke-static {v2, v3, v8}, Lcom/box/app/cfg/CfgNav;->wrap(',
                          broken_zu5)
            self.assertEqual(broken_zu5.count('iget-object v8, v0, Lzu5;->l:Landroid/content/Context;'), 2)
            self.assertIn('move-result-object v2', broken_zu5)
            broken_zo2 = (root / 'smali/zo2.smali').read_text()
            self.assertIn('move-result-object p2', broken_zo2)
            self.assertIn('long-to-int p4, p2', broken_zo2)

            changed = repair(root)
            self.assertEqual(len(changed), 13)
            self.assertIn('r6 tar entry matcher', changed)
            self.assertIn('xl4 callback receiver', changed)
            self.assertIn('uu0 core-version script register', changed)
            self.assertIn('qc0 external-files root name', changed)
            self.assertIn('eu0 battery-toggle Compose register order', changed)
            self.assertIn('y75 enum-key invoke result order', changed)
            self.assertIn('ij4 RestoreCfg e65 constructor argument', changed)
            self.assertIn('zu5 CfgNav wrapper argument registers', changed)
            self.assertIn('zo2 VPN control result register', changed)
            fixed_zo2 = (root / 'smali/zo2.smali').read_text()
            self.assertIn('move-result-object v5', fixed_zo2)
            self.assertIn('if-eqz v5, :cond_vpn_none', fixed_zo2)
            self.assertIn('return-object v5', fixed_zo2)
            self.assertNotIn('move-result-object p2', fixed_zo2)
            self.assertIn('long-to-int p4, p2', fixed_zo2)

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

            qc0 = (root / 'smali/qc0.smali').read_text()
            qc0_k = qc0.split('.method public static k()Lfc0;', 1)[1].split('.end method', 1)[0]
            self.assertIn('if-nez v0, :cond_external_files_ready', qc0_k)
            self.assertLess(qc0_k.index('\n    :cond_external_files_ready\n'),
                            qc0_k.index('\n    const-string v2, "box"'))
            self.assertLess(qc0_k.index('const-string v2, "box"'),
                            qc0_k.index('invoke-direct {v1, v0, v2},'))

            eu0 = (root / 'smali/eu0.smali').read_text()
            eu0_method = eu0.split('.method public final a(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;', 1)[1].split('.end method', 1)[0]
            eu0_hunk = eu0_method.split('move-object/from16 v17, v5', 1)[1].split('const v7, -0x236bac2a', 1)[0]
            first_call = 'invoke-static/range {v11 .. v20}, Lub3;->s('
            toggle_call = 'invoke-static/range {v16 .. v25}, Lub3;->s('
            self.assertLess(eu0_hunk.index(first_call), eu0_hunk.index('const v4, 0x13f2fb70'))
            self.assertLess(eu0_hunk.index('move-result-object v18'),
                            eu0_hunk.index('invoke-static {}, Lcom/box/app/vpn/BattToggle;->create()'))
            self.assertIn('move-result-object v17', eu0_hunk)
            self.assertLess(eu0_hunk.index('VpnPrefs;->battOn()Z'), eu0_hunk.index(toggle_call))
            self.assertIn('invoke-static {v4, v5}, Lub3;->a0(ILla2;)Ljava/lang/String;', eu0_hunk)
            self.assertIn('move-object/from16 v22, v5', eu0_hunk)
            self.assertEqual(eu0_hunk.count('invoke-virtual {v5, v10}, Lla2;->r(Z)V'), 2)
            self.assertIn('const/16 v4, 0xe', eu0_hunk)
            eu0_lines = eu0_method.splitlines()
            flag_mask = next(index for index, line in enumerate(eu0_lines)
                             if line.strip() == 'and-int/2addr v6, v4')
            v4_resets = [index for index, line in enumerate(eu0_lines)
                         if line.strip() == 'const/16 v4, 0xe']
            self.assertEqual(len(v4_resets), 2)
            resource_id = next(index for index, line in enumerate(eu0_lines)
                               if line.strip() == 'const v4, 0x7f0f055c')
            self.assertGreater(v4_resets[-1], resource_id)
            self.assertLess(v4_resets[-1], flag_mask)

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
            pd1_method = pd1.split('.method public final g(', 1)[1].split('.end method', 1)[0]
            sd_start = pd1_method.index('\n    :goto_sd\n')
            sd_name = pd1_method.index('const-string v15, "sing-box_dingtalk"', sd_start)
            sd_call = pd1_method.index('invoke-direct/range {v14 .. v21}, Lfd1;-><init>(', sd_start)
            self.assertLess(sd_name, sd_call)

            y75 = (root / 'smali/y75.smali').read_text()
            y75_method = y75.split('.method public final a(', 1)[1].split('.end method', 1)[0]
            y75_instructions = [line.strip() for line in y75_method.splitlines()
                                if line.strip() and not line.strip().startswith(('.', '#', ':'))]
            key_index = y75_instructions.index(
                'invoke-static {v14}, Lcom/box/app/vpn/VpnBridge;->key(Lne5;)I')
            self.assertEqual(y75_instructions[key_index - 1], 'move/from16 p3, v1')
            self.assertEqual(y75_instructions[key_index + 1], 'move-result v1')

            ij4 = (root / 'smali/ij4.smali').read_text()
            ij4_method = ij4.split('.method public synthetic constructor <init>(', 1)[1].split('.end method', 1)[0]
            ij4_instructions = [line.strip() for line in ij4_method.splitlines()
                                if line.strip() and not line.strip().startswith(('.', '#', ':'))]
            p9_store = ij4_instructions.index('iput-object p9, p0, Lij4;->s:Ljava/lang/Object;')
            restore_call = ij4_instructions.index(
                'invoke-static {p9}, Lcom/box/app/vpn/RestoreCfg;->vm(Le65;)V')
            self.assertEqual(restore_call, p9_store + 1)
            self.assertNotIn('invoke-static {p8}, Lcom/box/app/vpn/RestoreCfg;->vm(Le65;)V',
                             ij4_instructions)

            zu5 = (root / 'smali/zu5.smali').read_text()
            zu5_method = zu5.split('.method public final invoke(', 1)[1].split('.end method', 1)[0]
            zu5_instructions = [line.strip() for line in zu5_method.splitlines()
                                if line.strip() and not line.strip().startswith(('.', '#', ':'))]
            wrap_indices = [i for i, line in enumerate(zu5_instructions)
                            if 'CfgNav;->wrap(' in line]
            fixed_wrap = (
                'invoke-static/range {v32 .. v34}, '
                'Lcom/box/app/cfg/CfgNav;->wrap(Ll92;Lpv5;Landroid/content/Context;)Ll92;'
            )
            self.assertEqual([zu5_instructions[i] for i in wrap_indices],
                             [fixed_wrap, fixed_wrap])
            self.assertIn('.locals 35', zu5_method)
            self.assertEqual([zu5_instructions[i - 4] for i in wrap_indices], [
                'iget-object v4, v0, Lzu5;->l:Landroid/content/Context;',
                'iget-object v4, v0, Lzu5;->l:Landroid/content/Context;',
            ])
            self.assertEqual([zu5_instructions[i - 3] for i in wrap_indices], [
                'move-object/from16 v32, v3', 'move-object/from16 v32, v2',
            ])
            self.assertEqual([zu5_instructions[i - 2] for i in wrap_indices], [
                'move-object/from16 v33, v7', 'move-object/from16 v33, v3',
            ])
            self.assertEqual([zu5_instructions[i - 1] for i in wrap_indices], [
                'move-object/from16 v34, v4', 'move-object/from16 v34, v4',
            ])
            self.assertEqual([zu5_instructions[i + 1] for i in wrap_indices], [
                'move-result-object v3', 'move-result-object v10',
            ])
            self.assertNotIn('iget-object v7, v0, Lzu5;->p:Lsv5;', zu5_instructions)
            self.assertNotIn('iget-object v8, v0, Lzu5;->p:Lsv5;', zu5_instructions)
            self.assertIn('iget-object v7, v0, Lzu5;->j:Lpv5;', zu5_instructions)
            self.assertIn('move-object v13, v8', zu5_instructions)
            second_wrap_index = wrap_indices[1]
            source_yz0_call = zu5_instructions.index(
                'invoke-static {v9, v2, v13}, Ltj;->J(ILt92;Lla2;)Lyz0;')
            self.assertLess(source_yz0_call, second_wrap_index)
            self.assertEqual(zu5_instructions[source_yz0_call + 1], 'move-result-object v2')
            following_j = zu5_instructions.index(
                'invoke-static {v4, v9, v13}, Ltj;->J(ILt92;Lla2;)Lyz0;',
                second_wrap_index)
            self.assertEqual(zu5_instructions[following_j + 1], 'move-result-object v10')
            lzo_index = next(i for i, line in enumerate(zu5_instructions)
                             if line.startswith('invoke-static/range {v8 .. v18}, Lzo;->c('))
            self.assertEqual(zu5_instructions[lzo_index - 1], 'move-object v8, v2')
            v2_uses = [line for line in zu5_instructions[second_wrap_index + 2:lzo_index]
                       if re.search(r'\bv2\b', line)]
            self.assertEqual(v2_uses, ['move-object v8, v2'])
            self.assertEqual(repair(root), [])

    def test_repairs_stage6_generated_zu5_cfg_nav_register_form(self):
        method = '''\
.method public final invoke(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;
    .locals 33
    iget-object v7, v0, Lzu5;->j:Lpv5;
    new-instance v3, Lx65;
    iget-object v7, v0, Lzu5;->p:Lsv5;
    invoke-static {v3, v2, v7}, Lcom/box/app/cfg/CfgNav;->wrap(Ll92;Lpv5;Landroid/content/Context;)Ll92;
    move-result-object v3
    const v4, -0x7a21ea59
    invoke-static {v4, v3, v1}, Ltj;->J(ILt92;Lla2;)Lyz0;
    move-result-object v3
    invoke-static {v9, v2, v13}, Ltj;->J(ILt92;Lla2;)Lyz0;
    move-result-object v2
    iget-object v3, v0, Lzu5;->j:Lpv5;
    iget-object v8, v0, Lzu5;->p:Lsv5;
    invoke-static {v2, v3, v8}, Lcom/box/app/cfg/CfgNav;->wrap(Ll92;Lpv5;Landroid/content/Context;)Ll92;
    move-result-object v2
    const v4, 0x6cb9fadf
    invoke-static {v4, v9, v13}, Ltj;->J(ILt92;Lla2;)Lyz0;
    move-result-object v10
    move-object v8, v2
    invoke-static/range {v8 .. v18}, Lzo;->c(Lyz0;Lmz3;Lyz0;Lyz0;FLue3;Lz57;Lbt4;Lla2;II)V
    return-object v2
.end method
'''
        fixed, changed = fix_zu5_cfg_nav_wrapper_registers(method)
        self.assertTrue(changed)
        self.assertIn('.locals 35', fixed)
        self.assertEqual(fixed.count(
            'invoke-static/range {v32 .. v34}, '
            'Lcom/box/app/cfg/CfgNav;->wrap('), 2)
        self.assertIn('move-object/from16 v32, v3', fixed)
        self.assertIn('move-object/from16 v33, v7', fixed)
        self.assertIn('move-object/from16 v32, v2', fixed)
        self.assertIn('move-object/from16 v33, v3', fixed)
        self.assertEqual(fixed.count(
            'iget-object v4, v0, Lzu5;->l:Landroid/content/Context;'), 2)
        self.assertNotIn('Lzu5;->p:Lsv5;', fixed)
        self.assertIn('move-result-object v3', fixed)
        self.assertIn('move-result-object v10', fixed)
        fixed_again, changed_again = fix_zu5_cfg_nav_wrapper_registers(fixed)
        self.assertFalse(changed_again)
        self.assertEqual(fixed_again, fixed)

    def test_upgrades_legacy_eu0_fix_that_clobbered_nn3_flag_mask(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_candidate(root)
            self.assertEqual(len(repair(root)), 13)

            eu0_path = root / 'smali/eu0.smali'
            eu0 = eu0_path.read_text()
            anchor = 'move-object/from16 v17, v5'
            start = eu0.index(anchor) + len(anchor)
            end = eu0.index('const v7, -0x236bac2a', start)
            hunk = eu0[start:end]
            reset = '    const/16 v4, 0xe\n'
            self.assertEqual(hunk.count(reset), 1)
            eu0_path.write_text(eu0[:start] + hunk.replace(reset, '', 1) + eu0[end:])

            changed = repair(root)
            self.assertEqual(changed, ['eu0 battery-toggle Compose register order'])
            repaired = eu0_path.read_text()
            method = repaired.split(
                '.method public final a(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;',
                1)[1].split('.end method', 1)[0]
            lines = method.splitlines()
            resets = [index for index, line in enumerate(lines)
                      if line.strip() == 'const/16 v4, 0xe']
            mask = next(index for index, line in enumerate(lines)
                        if line.strip() == 'and-int/2addr v6, v4')
            self.assertEqual(len(resets), 2)
            self.assertLess(resets[-1], mask)
            self.assertEqual(repair(root), [])

    def test_upgrades_legacy_pd1_resume_path_with_undefined_string_register(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_candidate(root)
            repair(root)

            pd1_path = root / 'smali/pd1.smali'
            pd1 = pd1_path.read_text()
            method_start = pd1.index('.method public final g(')
            sd_start = pd1.index('\n    :goto_sd\n', method_start)
            sd_end = pd1.index('\n    :pswitch_data_0', sd_start)
            block = pd1[sd_start:sd_end]
            assignment = '    const-string v15, "sing-box_dingtalk"\n'
            self.assertEqual(block.count(assignment), 1)
            pd1_path.write_text(pd1[:sd_start] + block.replace(assignment, '', 1) + pd1[sd_end:])

            changed = repair(root)
            self.assertEqual(changed, ['pd1 coroutine dispatch labels'])
            repaired = pd1_path.read_text()
            method = repaired.split('.method public final g(', 1)[1].split('.end method', 1)[0]
            sd_start = method.index('\n    :goto_sd\n')
            sd_name = method.index('const-string v15, "sing-box_dingtalk"', sd_start)
            sd_call = method.index('invoke-direct/range {v14 .. v21}, Lfd1;-><init>(', sd_start)
            self.assertLess(sd_name, sd_call)
            self.assertEqual(repair(root), [])


if __name__ == '__main__':
    unittest.main()
