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


if __name__ == '__main__':
    unittest.main()
