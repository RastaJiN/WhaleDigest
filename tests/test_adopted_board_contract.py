"""Regression at the adopted Markdown -> execution board -> audit boundary."""
from importlib import import_module
from pathlib import Path
import sys
import tempfile
import unittest

from test_scene_blocking import build

# Exercise the same script-path imports used by the production CLIs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
audit_project = import_module('whale_diff_audit').audit_project
audit_step_3 = import_module('whale_gatekeeper').audit_step_3
stage_record = import_module('whale_task_source').stage_record


class AdoptedBoardContract(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def board(self, text):
        path = self.root / '分镜.md'
        path.write_text(text, encoding='utf-8')
        return path

    def test_quoted_side_and_room_name_are_not_stage_directions(self):
        self.board('## 场次 A\n### SHOT-01\n- 地点：门口\n- 台词：S1：“这次男左女右，S2在门口。”\n')
        _, rows = build(self.root, ['blocking_2s'])
        plan = rows[0]['blocking_state']
        self.assertEqual((plan['scene_id'], plan['source']), ('A', '分镜补定'))
        self.assertEqual(plan['start']['world'], {})

    def test_two_plain_scenes_bind_to_their_own_shots_and_roles(self):
        (self.root / '剧本.md').write_text('## 场次 A\n两人交谈。\n## 场次 B\n继续交谈。', encoding='utf-8')
        text = ('## 场次 A\n### SHOT-01\n- 站位：女左男右\n- 空间：S1在门口，S2坐着\n'
                '### SHOT-02\n- 用途：反打\n## 场次 B\n### SHOT-03\n- 站位：男左女右\n')
        path = self.board(text)
        original = path.read_bytes()
        exe, rows = build(self.root, ['blocking_2s', 'srs_male', 'blocking_2s'])
        plans = [r['blocking_state'] for r in rows]
        self.assertEqual([p['scene_id'] for p in plans], ['A', 'A', 'B'])
        self.assertEqual([p['screen_left'] for p in plans], ['S1', 'S1', 'S2'])
        self.assertEqual([p['source'] for p in plans], ['分镜明示', '同场继承', '分镜明示'])
        self.assertEqual(plans[1]['start']['world'], {'S1': 'at the doorway', 'S2': 'seated'})
        self.assertEqual(plans[2]['start']['world'], {})
        self.assertEqual(path.read_bytes(), original)
        self.assertNotEqual(exe, path)

    def test_plain_conflict_stops_before_writing_over_anything(self):
        (self.root / '剧本.md').write_text('## 场次 A\n站位：男左女右\n', encoding='utf-8')
        text = '## 场次 A\n### SHOT-01\n- 站位：女左男右\n'
        path = self.board(text)
        batch = self.root / '批量任务.json'
        batch.write_bytes(b'prior batch')
        with self.assertRaisesRegex(ValueError, '冲突'):
            build(self.root, ['blocking_2s'])
        self.assertEqual(batch.read_bytes(), b'prior batch')
        self.assertEqual(path.read_text(encoding='utf-8'), text)

    def test_gate_and_audit_use_bound_execution_board_not_an_arbitrary_sibling(self):
        from dryrun_test import png_bytes
        assets = self.root / '00_资产'
        assets.mkdir(exist_ok=True)
        for name in ('female_dressed.png', 'male_dressed.png', 'female_nude.png', 'male_nude.png', 'scene_main.png'):
            (assets / name).write_bytes(png_bytes())
        text = '## 场次 A\n### SHOT-01\n- 用途：听者反应\n'
        path = self.board(text)
        exe, _ = build(self.root, ['srs_female'], lines='1:S2(VO):等等。')
        ok, reason = audit_step_3(self.root)
        self.assertTrue(ok, reason)
        evidence = stage_record(self.root, 3)['project_inputs']
        self.assertIn(path.name, evidence)
        self.assertIn(exe.name, evidence)
        audit = audit_project(self.root)
        self.assertFalse(audit['violations'], audit['violations'])
        self.assertTrue(audit['files_checked'][exe.name])
        # Leave the plan untouched but alter only the execution board after sign-off.
        exe.write_bytes(exe.read_bytes() + b'\nchanged\n')
        ok, reason = audit_step_3(self.root)
        self.assertFalse(ok)
        self.assertRegex(reason, '变更|重新编译')
        self.assertTrue(audit_project(self.root)['violations'])


if __name__ == '__main__':
    unittest.main()
