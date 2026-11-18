"""Reproducibility and contract test for the reviewed 171 -> 176 migration.

The 176 candidate is produced by `scripts/migrate_176.py`, which derives every
input from committed artifacts: the pinned 171 upstream snapshot, the pinned
176 upstream snapshot, the reviewed class map and the reviewed coverage plan.
The test re-runs the whole pipeline in a temporary directory and asserts the
published tree carries the reviewed customizations.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_171 = ROOT / 'upstream/26.11.16.25abc84'
SNAPSHOT_176 = ROOT / 'upstream/26.11.17.73f2816'
VERSION_NAME = '26.11.17.73f2816'
VERSION_CODE = '176'


class Full176MigrationTest(unittest.TestCase):
    """The 176 port must be reproducible and must keep the 171 customizations."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='boxproxy-176-test-')
        cls.output = Path(cls._tmp.name) / 'candidate'
        subprocess.run(
            [sys.executable, 'scripts/migrate_176.py', '--output', str(cls.output)],
            cwd=ROOT, check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @property
    def project(self):
        return self.output / 'decompiled'

    def smali(self, name):
        return (self.project / 'smali' / name).read_text()

    def test_published_project_carries_the_176_version(self):
        config = (self.project / 'apktool.yml').read_text().splitlines()
        self.assertIn('  versionCode: ' + str(VERSION_CODE), config)
        self.assertIn('  versionName: ' + VERSION_NAME, config)

    def test_core_registry_keeps_the_nine_reviewed_cores(self):
        registry = self.smali('p77.smali')
        names = ['mihomo', 'mihomo_smart', 'mihomo_dingtalk', 'sing-box',
                 'sing-box_ref1nd', 'sing-box_dingtalk', 'xray', 'v2fly', 'hysteria']
        positions = []
        for name in names:
            marker = 'const-string v%d, "%s"' % (names.index(name), name)
            self.assertIn(marker, registry)
            positions.append(registry.index(marker))
        self.assertEqual(positions, sorted(positions))

    def test_core_registry_resource_ids_match_the_176_resource_table(self):
        registry = self.smali('p77.smali')
        public = {}
        for match in __import__('re').finditer(
                r'<public type="(\w+)" name="([^"]+)" id="(0x[0-9a-fA-F]+)"',
                (self.project / 'res/values/public.xml').read_text()):
            public[match.group(3)] = match.group(2)
        expected = {
            '0x7f0f0384': 'proxy_core_mihomo',
            '0x7f0f0385': 'proxy_core_mihomo_smart',
            '0x7f0f0590': 'proxy_core_mihomo_dingtalk',
            '0x7f0f0386': 'proxy_core_sing_box',
            '0x7f0f0387': 'proxy_core_sing_box_ref1nd',
            '0x7f0f0591': 'proxy_core_sing_box_dingtalk',
            '0x7f0f038a': 'proxy_core_xray',
            '0x7f0f0389': 'proxy_core_v2fly',
            '0x7f0f0383': 'proxy_core_hysteria',
        }
        for resource_id, name in expected.items():
            self.assertEqual(public.get(resource_id), name, resource_id)
            self.assertIn('const v0, ' + resource_id, registry)

    def test_vpn_mode_enum_adds_the_vpn_entry(self):
        enum = self.smali('jg5.smali')
        self.assertIn('.field public static final enum t:Ljg5;', enum)
        self.assertIn('const-string v9, "vpn"', enum)
        self.assertIn('sput-object v6, Ljg5;->t:Ljg5;', enum)

    def test_settings_list_carries_the_localized_hide_unavailable_entry(self):
        settings = self.smali('ub3.smali')
        self.assertIn('const v1, 0x7f0f058f', settings)
        self.assertIn('invoke-static {v1, v10}, Lkb3;->d0(ILub2;)Ljava/lang/String;',
                      settings)
        self.assertIn(
            'invoke-static {v0, v1}, Lcom/box/app/vpn/VpnPrefs;->items(Ljava/util/List;Ljava/lang/String;)Ljava/util/List;',
            settings)

    def test_restore_menu_entry_survives_the_port(self):
        import re
        for name in ('k.smali', 'q95.smali'):
            text = self.smali(name)
            self.assertRegex(text, r'const p\d+, 0x7f0f0592', name)
            self.assertIn('Lcom/box/app/vpn/RestoreCfg;->MENU:Lcom/box/app/vpn/RestoreCfg;',
                          text)
            self.assertRegex(text, r'new-instance v\d+, Lkx4;', name)

    def test_dingtalk_core_sources_are_added_to_the_default_source_list(self):
        sources = self.smali('re1.smali')
        self.assertIn('const-string v23, "mihomo_dingtalk"', sources)
        self.assertIn('const-string v36, "sing-box_dingtalk"', sources)
        self.assertIn('const-string v27, "jieluojun/mihomo"', sources)
        self.assertIn('const-string v40, "jieluojun/sing-box"', sources)

    def test_core_version_rules_accept_the_dingtalk_repositories(self):
        rules = self.smali('t6.smali')
        self.assertIn('const-string v3, "jieluojun/sing-box"', rules)
        self.assertIn('const-string v4, "jieluojun/mihomo"', rules)
        self.assertIn(':cond_dingtalk_smart_repo', rules)

    def test_core_path_probe_reads_the_configured_core_path(self):
        probe = self.smali('f85.smali')
        self.assertIn('iget-object v10, v2, Lhc0;->h:Ljava/lang/String;', probe)

    def test_coroutine_states_keep_the_dingtalk_branches(self):
        states = self.smali('oe1.smali')
        self.assertIn(':pswitch_9', states)
        self.assertIn(':pswitch_10', states)
        self.assertIn(':goto_dd', states)
        self.assertIn(':goto_sd', states)
        self.assertIn('-0x7fc2cadc -> :sswitch_6', states)
        self.assertIn('-0x54707cda -> :sswitch_6_custom', states)

    def test_external_files_branch_builds_the_base_on_both_paths(self):
        import re
        text = self.smali('uc0.smali')
        match = re.search(r'\.method public static k\(\)Ljc0;\n(.*?)\.end method',
                          text, re.S)
        self.assertIsNotNone(match, 'uc0.k() is missing')
        lines = [line.strip() for line in match.group(1).splitlines()
                 if line.strip() and not line.strip().startswith('.')]

        def index(needle):
            hits = [i for i, line in enumerate(lines) if line == needle]
            self.assertEqual(len(hits), 1, '%r appears %d times' % (needle, len(hits)))
            return hits[0]

        branch = index('if-nez v0, :cond_external_files_ready')
        label = index(':cond_external_files_ready')
        fallback = index('invoke-virtual {v0}, Landroid/content/Context;'
                         '->getFilesDir()Ljava/io/File;')
        literal = index('const-string v2, "box"')
        allocate = index('new-instance v1, Ljava/io/File;')
        construct = index('invoke-direct {v1, v0, v2}, Ljava/io/File;'
                          '-><init>(Ljava/io/File;Ljava/lang/String;)V')
        # The non-null external files path jumps straight to the label, so the
        # label has to sit in front of the literal and the allocation; moving
        # it behind them leaves v1 undefined and ART rejects uc0 with a
        # VerifyError during AppApplication.onCreate.
        self.assertLess(branch, label)
        self.assertLess(label, literal)
        self.assertLess(label, allocate)
        # The null path falls through the getFilesDir fallback to the label.
        self.assertLess(branch, fallback)
        self.assertLess(fallback, label)
        # Both paths construct the File from the prepared registers.
        self.assertLess(literal, construct)
        self.assertLess(allocate, construct)

    def test_coverage_plan_is_fully_migrated(self):
        coverage = json.loads((SNAPSHOT_176 / 'migration/coverage.json').read_text())
        self.assertEqual(len(coverage['completed']), 51)
        self.assertEqual(coverage['collisions'], [])
        self.assertEqual(coverage['pending'], [])
        for plan in coverage['completed']:
            target = self.project / plan['targetFile']
            self.assertTrue(target.is_file(), plan['new'])

    def test_reviewed_class_map_covers_every_migrated_class(self):
        class_map = json.loads((SNAPSHOT_176 / 'migration/class-map.json').read_text())
        self.assertEqual(class_map['mapped'], len(class_map['candidates']))
        self.assertEqual(class_map['mapped'], 8467)

    @staticmethod
    def _significant(text):
        return [line.strip() for line in text.splitlines()
                if line.strip() and not line.strip().startswith('.')]

    def test_battery_unrestricted_row_lands_in_wq4(self):
        """The row follows the page: wq4.a, not iu0.a, with wq4's registers.

        The 176 upstream dropped the171 case3 auto-start service page from
        the iu0 compose factory and rebuilt it as wq4, so a row inserted into
        iu0.a would hand a boolean register to the row invoke and ART rejects
        iu0 with a VerifyError during UI composition.
        """
        iu0 = self.smali('iu0.smali')
        self.assertNotIn('BattToggle', iu0)
        self.assertNotIn('0x13f2fb70', iu0)
        self.assertNotIn('VpnPrefs;->battOn', iu0)

        lines = self._significant(self.smali('wq4.smali'))
        anchor = 'const v9, -0x5325d91'
        hits = [i for i, line in enumerate(lines) if line == anchor]
        self.assertEqual(len(hits), 1,
                         'wq4.a battery anchor appears %d times' % len(hits))
        row = [
            'const v9, 0x13f2fb70',
            'invoke-virtual {v4, v9}, Lub2;->b0(I)V',
            'const v9, 0x7f0f0597',
            'invoke-static {v9, v4}, Lkb3;->d0(ILub2;)Ljava/lang/String;',
            'move-result-object v18',
            'const v9, 0x7f0f0598',
            'invoke-static {v9, v4}, Lkb3;->d0(ILub2;)Ljava/lang/String;',
            'move-result-object v19',
            'invoke-static {}, Lcom/box/app/vpn/BattToggle;->create()'
            'Lcom/box/app/vpn/BattToggle;',
            'move-result-object v17',
            'invoke-static {}, Lcom/box/app/vpn/VpnPrefs;->battOn()Z',
            'move-result v16',
            'move-object/from16 v20, v15',
            'const/16 v24, 0x0',
            'const/16 v25, 0x3f58',
            'const/16 v21, 0x0',
            'const/high16 v23, 0xc00000',
            'move-object/from16 v22, v4',
            'invoke-static/range {v16 .. v25}, Lat6;->c(ZLqa2;'
            'Ljava/lang/String;Ljava/lang/String;Lc01;ZLub2;III)V',
            'invoke-virtual {v4, v3}, Lub2;->r(Z)V',
            'const/16 v9, 0xe',
        ]
        start = hits[0] - len(row)
        self.assertGreaterEqual(start, 0, 'battery row missing before anchor')
        self.assertEqual(lines[start:hits[0]], row,
                         'the battery unrestricted row must sit directly in '
                         'front of the wq4.a anchor in wq4 registers')
        self.assertEqual(sum(1 for line in lines if 'BattToggle' in line), 1)

    def test_vpn_mode_res_shortcut_keeps_the_mode_result_register(self):
        """modeRes lands in v15, not in the enum register v13.

        The generic delta spelled the shortcut with `move-result v13`, which
        both clobbers the enum on the fall-through path and leaves the row
        lookup's third argument unset on the jump path, so the verifier
        rejects the merge at :goto_6 with `register v15 ... expected Integer`.
        """
        lines = self._significant(self.smali('ra1.smali'))
        shortcut = [
            'check-cast v13, Ljg5;',
            'invoke-static {v13}, Lcom/box/app/vpn/VpnBridge;'
            '->modeRes(Ljg5;)I',
            'move-result v15',
            'if-eqz v15, :cond_pv_novpn',
            'const v13, -0x1c301169',
            'const/4 v14, 0x0',
            'goto :goto_6',
            ':cond_pv_novpn',
        ]
        found = any(lines[i:i + len(shortcut)] == shortcut
                    for i in range(len(lines) - len(shortcut) + 1))
        self.assertTrue(found, 'the modeRes shortcut block is missing or has '
                               'the wrong register layout')
        for index, line in enumerate(lines):
            if 'VpnBridge;->modeRes' in line:
                self.assertEqual(lines[index + 1], 'move-result v15',
                                 'the modeRes result must land in v15')

    def test_register_flow_checker_accepts_the_migrated_tree(self):
        result = subprocess.run(
            [sys.executable, 'scripts/check_smali_register_flow.py',
             str(self.project)],
            cwd=ROOT, capture_output=True, text=True, timeout=600)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('0 undefined register reads, 0 type conflicts',
                      result.stdout)

    @staticmethod
    def _flow_module():
        sys.path.insert(0, str(ROOT / 'scripts'))
        import check_smali_register_flow as flow
        return flow

    def test_register_flow_checker_detects_type_conflicts(self):
        """The kind pass must keep catching the two device VerifyErrors."""
        flow = self._flow_module()

        # iu0 shape: a boolean register handed to a reference receiver.
        boolean_receiver = (
            '.method public final a(Lub2;)V\n'
            '    .locals 1\n'
            '    iget-boolean v0, p0, Lx;->flag:Z\n'
            '    invoke-virtual {v0, v0}, Lub2;->b0(I)V\n'
            '    return-void\n'
            '.end method')
        findings, _ = flow.analyze_kinds(boolean_receiver)
        self.assertTrue(any(f[2] == 'v0' and f[4] == 'Reference'
                            for f in findings),
                        'boolean receiver must be reported')

        # ra1 shape: the mode result and the row id disagree at the join.
        conflicting_join = (
            '.method public static a(Z)V\n'
            '    .locals 2\n'
            '    if-eqz p0, :alt\n'
            '    invoke-static {}, Lx;->it()Ljava/util/Iterator;\n'
            '    move-result-object v1\n'
            '    goto :join\n'
            '    :alt\n'
            '    const/4 v1, 0x1\n'
            '    :join\n'
            '    invoke-static {v1}, Lx;->n(I)V\n'
            '    return-void\n'
            '.end method')
        findings, _ = flow.analyze_kinds(conflicting_join)
        self.assertTrue(any(f[2] == 'v1' and f[4] == 'Int'
                            for f in findings),
                        'the reference/integer join must be reported')

        clean = (
            '.method public static a(I)V\n'
            '    .locals 1\n'
            '    invoke-static {}, Lx;->it()Ljava/util/Iterator;\n'
            '    move-result-object v0\n'
            '    invoke-static {v0}, Lx;->m(Ljava/util/Iterator;)V\n'
            '    invoke-static {p0}, Lx;->n(I)V\n'
            '    return-void\n'
            '.end method')
        findings, _ = flow.analyze_kinds(clean)
        self.assertEqual(findings, [])

    def test_register_flow_checker_still_reports_undefined_reads(self):
        flow = self._flow_module()
        undefined_shape = (
            '.method public static a(Z)V\n'
            '    .locals 1\n'
            '    if-eqz p0, :alt\n'
            '    const/4 v0, 0x1\n'
            '    :alt\n'
            '    invoke-static {v0}, Lx;->n(I)V\n'
            '    return-void\n'
            '.end method')
        findings, _ = flow.analyze(undefined_shape)
        self.assertTrue(any(f[2] == 'v0' for f in findings),
                        'the undefined pass must keep working')
        kind_findings, _ = flow.analyze_kinds(undefined_shape)
        self.assertEqual(kind_findings, [],
                         'undefined reads belong to the first pass')


if __name__ == '__main__':
    unittest.main()
