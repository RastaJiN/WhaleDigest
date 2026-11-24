# -*- coding: utf-8 -*-
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from whale_pose_guard import load_poses_matrix, suggest_safe_pose, validate_pose_entry
from whale_pipeline_check import check_workspace


class TestPoseGuardAndPipeline(unittest.TestCase):
    def test_matrix_loaded_94_poses(self):
        m = load_poses_matrix()
        self.assertGreaterEqual(len(m), 94)
        self.assertIn("bj", m)
        self.assertIn("cowgirl", m)

    def test_standard_drama_blocks_adult_pose(self):
        ok, errs, _ = validate_pose_entry("cowgirl", "standard_drama")
        self.assertFalse(ok)
        self.assertTrue(any("正剧模式" in e for e in errs))

        ok_empty, errs_empty, _ = validate_pose_entry("", "standard_drama")
        self.assertTrue(ok_empty)
        self.assertEqual(errs_empty, [])

    def test_adult_drama_accepts_truth_pose_and_converts_high_risk(self):
        ok, errs, _ = validate_pose_entry("missionary", "adult_drama")
        self.assertTrue(ok)
        self.assertEqual(errs, [])

        ok_bad, errs_bad, _ = validate_pose_entry("standing_carry", "adult_drama")
        self.assertFalse(ok_bad)
        self.assertTrue(any("missionary" in e for e in errs_bad))

        fb = suggest_safe_pose("standing_fuck")
        self.assertIsNotNone(fb)
        self.assertEqual(fb["fallback"], "doggy")

    def test_unknown_invented_pose_rejected(self):
        ok, errs, _ = validate_pose_entry("fake_invented_pose_xyz", "adult_drama")
        self.assertFalse(ok)
        self.assertTrue(any("不在 94 条真源" in e for e in errs))

    def test_pipeline_check_workspace_catches_bad_pose(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "批量任务.json").write_text(
                json.dumps({
                    "project_mode": "adult_drama",
                    "shots": [{"shot_id": "S01", "pose": "standing_carry"}],
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            rep = check_workspace(str(ws), "adult_drama")
            self.assertFalse(rep["ok"])
            self.assertEqual(len(rep["pose_errors"]), 1)
            self.assertIn("S01", rep["pose_errors"][0])


if __name__ == "__main__":
    unittest.main()
