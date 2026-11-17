"""Reproducibility test for the hash-pinned 171 migration candidate."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_smali_branch_offsets as branch_offsets  # noqa: E402
import check_smali_reference_moves as reference_moves  # noqa: E402
import check_smali_references as references  # noqa: E402
import migrate_upstream as migration  # noqa: E402
from repair_171_stage6_candidate import repair  # noqa: E402

SNAPSHOT = ROOT / 'upstream/26.11.16.25abc84'


class Full171MigrationTest(unittest.TestCase):
    def test_pinned_candidate_rebuilds_with_stage6_and_reference_checks(self):
        plan = json.loads((SNAPSHOT / 'migration/full.json').read_text())
        coverage = json.loads((SNAPSHOT / 'migration/coverage.json').read_text())
        self.assertEqual(plan['stage6Report']['ok'], 51)
        self.assertEqual(plan['stage6Report']['errors'], [])
        self.assertEqual(plan['stage6Report']['whole'], 16)
        self.assertEqual(plan['stage6Report']['patch'], 35)
        semantic_fixes = {item['name'] for item in plan['stage6Report']['semanticFixes']}
        self.assertIn('r6 tar-entry matching and nonzero branch offsets', semantic_fixes)
        self.assertIn('xl4 Compose callback receiver preservation', semantic_fixes)
        self.assertIn('uu0 coroutine core-version String register', semantic_fixes)
        self.assertIn('qc0 external-files root name on both branches', semantic_fixes)
        self.assertIn('eu0 battery-toggle Compose register order', semantic_fixes)
        self.assertIn('y75 enum-key invoke result order', semantic_fixes)
        self.assertIn('ij4 RestoreCfg e65 constructor argument', semantic_fixes)
        self.assertIn('pd1 resumed sing-box DingTalk constructor register', semantic_fixes)
        self.assertEqual(coverage['inventory']['wholeMethods'], 16)
        self.assertEqual(coverage['inventory']['patchedMethods'], 35)

        with tempfile.TemporaryDirectory() as temporary:
            project = migration.prepare(SNAPSHOT, Path(temporary) / 'reproduced')
            apktool = (project / 'apktool.yml').read_text()
            self.assertIn('  versionCode: 171', apktool)
            self.assertIn('  versionName: 26.11.16.25abc84', apktool)
            self.assertEqual(repair(project), [])

            result = references.check(project)
            self.assertEqual(result['classes'], 9879)
            self.assertEqual(result['references'], 578921)
            self.assertEqual(result['errors'], [])
            smali_files, branch_errors = branch_offsets.scan_project(project)
            self.assertEqual(smali_files, 9879)
            self.assertEqual(branch_errors, [])
            move_files, move_errors = reference_moves.scan_project(project)
            self.assertEqual(move_files, 9879)
            self.assertEqual(move_errors, [])

            xl4 = (project / 'smali/xl4.smali').read_text()
            self.assertIn('.locals 11', xl4)
            self.assertIn('move-object/from16 v9, p0', xl4)
            self.assertIn('iget-object v7, v9, Lxl4;->p:Lw82;', xl4)
            self.assertNotIn('move-object/from16 p0, p0', xl4)

            uu0 = (project / 'smali/uu0.smali').read_text()
            script_lines = [line.strip() for line in uu0.splitlines()
                            if "Match the root service's executable path" in line]
            self.assertEqual(len(script_lines), 1)
            self.assertTrue(script_lines[0].startswith('const-string v11, "'))
            self.assertIn(
                'invoke-static {v13, v7, v11, v2, v12}, '
                'Lly1;->s(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;'
                'Ljava/lang/String;Ljava/lang/String;)Ljava/lang/StringBuilder;', uu0)

            qc0 = (project / 'smali/qc0.smali').read_text()
            qc0_k = qc0.split('.method public static k()Lfc0;', 1)[1].split('.end method', 1)[0]
            self.assertIn('if-nez v0, :cond_external_files_ready', qc0_k)
            self.assertLess(qc0_k.index('\n    :cond_external_files_ready\n'),
                            qc0_k.index('\n    const-string v2, "box"'))
            self.assertLess(qc0_k.index('const-string v2, "box"'),
                            qc0_k.index('invoke-direct {v1, v0, v2},'))

            eu0 = (project / 'smali/eu0.smali').read_text()
            eu0_method = eu0.split('.method public final a(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;', 1)[1].split('.end method', 1)[0]
            eu0_hunk = eu0_method.split('move-object/from16 v17, v5', 1)[1].split('const v7, -0x236bac2a', 1)[0]
            self.assertLess(eu0_hunk.index('invoke-static/range {v11 .. v20}, Lub3;->s('),
                            eu0_hunk.index('const v4, 0x13f2fb70'))
            self.assertLess(eu0_hunk.index('VpnPrefs;->battOn()Z'),
                            eu0_hunk.index('invoke-static/range {v16 .. v25}, Lub3;->s('))
            self.assertIn('move-result-object v18', eu0_hunk)
            self.assertIn('move-result-object v17', eu0_hunk)
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

            r6 = (project / 'smali/r6.smali').read_text()
            self.assertIn('if-nez v6, :boxproxy_match', r6)
            self.assertIn('if-ltz v6, :cond_7', r6)

            cfg_nav = (project / 'smali/com/box/app/cfg/CfgNav.smali').read_text()
            self.assertIn(
                'invoke-static {v3, v13, v14}, Ltj;->J(ILt92;Lla2;)Lyz0;',
                cfg_nav)

            pd1 = (project / 'smali/pd1.smali').read_text()
            pd1_method = pd1.split('.method public final g(', 1)[1].split('.end method', 1)[0]
            sd_start = pd1_method.index('\n    :goto_sd\n')
            sd_name = pd1_method.index('const-string v15, "sing-box_dingtalk"', sd_start)
            sd_call = pd1_method.index('invoke-direct/range {v14 .. v21}, Lfd1;-><init>(', sd_start)
            self.assertLess(sd_name, sd_call)

            y75 = (project / 'smali/y75.smali').read_text()
            y75_method = y75.split(
                '.method public final a(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;',
                1)[1].split('.end method', 1)[0]
            y75_instructions = [line.strip() for line in y75_method.splitlines()
                                if line.strip() and not line.strip().startswith(('.', '#', ':'))]
            key_index = y75_instructions.index(
                'invoke-static {v14}, Lcom/box/app/vpn/VpnBridge;->key(Lne5;)I')
            self.assertEqual(y75_instructions[key_index - 1], 'move/from16 p3, v1')
            self.assertEqual(y75_instructions[key_index + 1], 'move-result v1')

            ij4 = (project / 'smali/ij4.smali').read_text()
            ij4_method = ij4.split(
                '.method public synthetic constructor <init>(Ljava/util/List;',
                1)[1].split('.end method', 1)[0]
            ij4_instructions = [line.strip() for line in ij4_method.splitlines()
                                if line.strip() and not line.strip().startswith(('.', '#', ':'))]
            p9_store = ij4_instructions.index(
                'iput-object p9, p0, Lij4;->s:Ljava/lang/Object;')
            restore_call = ij4_instructions.index(
                'invoke-static {p9}, Lcom/box/app/vpn/RestoreCfg;->vm(Le65;)V')
            self.assertEqual(restore_call, p9_store + 1)
            self.assertNotIn('invoke-static {p8}, Lcom/box/app/vpn/RestoreCfg;->vm(Le65;)V',
                             ij4_instructions)


if __name__ == '__main__':
    unittest.main()
