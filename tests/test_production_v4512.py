"""Regression tests for v4.5.12 dual-track upgrades:
1. Intimate scenes: automatic male/female multi-angle emotional reaction insertion,
   varied opening camera angles across poses, >=3 junction close-ups, and coverage metrics.
2. Standard/animated drama separation: Node 400 MysticXXX LoRA defaults to 0.0 when
   not an intimate pose, advisor omits adult phrasing, and producer receipt uses clean
   non-intimate wording for standard/animated projects.
"""
import json
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

core = import_module("whale_core")
scene = import_module("whale_scene")
runner = import_module("whale_runner")
diff_audit = import_module("whale_diff_audit")
advisor = import_module("whale_advisor")


class ProductionV4512Test(unittest.TestCase):
    def test_intimate_chain_has_pose_switch_three_closeups_dual_reactions_and_camera_variety(self):
        poses = core.load_poses()
        shots, actual = scene.build_scene(["stand_doggy_wall", "doggy", "missionary", "creampie"], 75.0, poses)
        self.assertGreater(actual, 40.0)

        # 1) Pose switch transitions present
        transitions = [s for s in shots if s.get("type") == "transition"]
        self.assertGreaterEqual(len(transitions), 2)

        # 2) >= 3 junction close-ups (hip / macro)
        closeups = [s for s in shots if s["size"] in ("hip", "macro")]
        self.assertGreaterEqual(len(closeups), 3)

        # 3) Both male and female independent emotional reactions inserted automatically
        srs_m = [s for s in shots if s["pose"] == "srs_male"]
        srs_f = [s for s in shots if s["pose"] == "srs_female"]
        self.assertTrue(srs_m, "Expected automatic male emotional reaction shot")
        self.assertTrue(srs_f, "Expected automatic female emotional reaction shot")
        self.assertNotIn("ots", srs_m[0]["cam"])
        self.assertNotEqual(srs_m[0]["cam"], srs_f[0]["cam"])

        # 4) Opening camera variety across stand_doggy_wall / doggy / missionary
        first_cams = {}
        for pid in ("stand_doggy_wall", "doggy", "missionary"):
            first_cams[pid] = next(s["cam"] for s in shots if s["pose"] == pid)
        self.assertEqual(len(set(first_cams.values())), 3, f"Expected distinct opening cams, got {first_cams}")

        # 5) Overall shot-size & camera diversity
        self.assertGreaterEqual(len({s["size"] for s in shots}), 4)
        self.assertGreaterEqual(len({s["cam"] for s in shots}), 5)

        # 6) Intimate audit metrics & receipt
        with tempfile.TemporaryDirectory() as tmp:
            scene.save_project_artifacts(tmp, shots, actual, 75.0, aspect="16:9", wardrobe_mode="nude_all")
            rep = diff_audit.audit_project(tmp)
            self.assertEqual(rep["violations"], [], rep["violations"])
            self.assertEqual(rep["metrics"]["project_mode"], "intimate_drama")
            icov = rep["metrics"]["intimate_coverage"]
            self.assertGreaterEqual(icov["pose_switch_count"], 2)
            self.assertGreaterEqual(icov["junction_closeup_count"], 3)
            self.assertTrue(icov["has_male_reaction"])
            self.assertTrue(icov["has_female_reaction"])
            receipt = Path(diff_audit.write_producer_receipt(tmp, rep)).read_text("utf-8")
            self.assertIn("含肉戏剧集", receipt)
            self.assertIn("交合特写与情绪反馈", receipt)

    def test_standard_animation_defaults_mystic_lora_zero_and_uses_clean_reports(self):
        # 1) Runner must zero MysticXXX LoRA (Node 400) for standard/animated shots when unspecified
        template = json.loads(Path(runner.DEFAULT_WF).read_text(encoding="utf-8"))
        prompt = (
            "subject_definitions:\n"
            "<Subject 1> is the young ranger from <Picture 1>.\n"
            "<Subject 2> is the sunlit office from <Picture 2>.\n"
            "summary: The ranger checks his notebook.\n"
            "retention_analysis:\n"
            "<Subject 1>: fully_preserved for identity from <Picture 1>.\n"
            "<Subject 2>: weak_reference for framing from <Picture 2>.\n"
            "detailed_description:\n"
            "Camera: medium close-up, slow dolly push-in, matte velvet skin finish.\n"
            "[Shot 1] Inside <Subject 2>, <Subject 1> flips his notebook and smiles.\n"
            "overall_soundscape: Morning birdsong and gentle breeze.\n"
            "non_diegetic_music: N/A"
        )
        anim_shot = {
            "id": 1,
            "shot_id": "R01-01",
            "pose": "env_establish",
            "shot_size": "mcu",
            "camera_motion": "push_tension",
            "frames": 90,
            "duration": 3.75,
            "ref_images": ["ranger.png", "office.png"],
            "prompt": prompt,
        }
        batch = {
            "schema": "h3-drama-task",
            "aspect": "16:9",
            "total_frames": 90,
            "total_duration": 3.75,
            "batch_shots": [anim_shot],
        }
        wf = runner.build_shot_workflow(template, anim_shot, aspect="16:9", batch=batch)
        self.assertEqual(wf["400"]["inputs"]["strength_model"], 0.0)

        # 2) Standard drama receipt & advisor must not leak adult/intimate phrasing
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "00_资产").mkdir()
            (root / "剧本.md").write_text(
                "# EP001 环保巡查\n- 林川：<d>[Chinese]今天天气不错，咱们去巡查吧。</d>\n",
                encoding="utf-8",
            )
            (root / "批量任务.json").write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")

            rep = diff_audit.audit_project(tmp)
            self.assertEqual(rep["violations"], [], rep["violations"])
            self.assertEqual(rep["metrics"]["project_mode"], "standard_drama")
            receipt = Path(diff_audit.write_producer_receipt(tmp, rep)).read_text("utf-8")
            self.assertIn("纯正剧/动画", receipt)
            for forbidden in ("交合微距", "女槽", "男槽", "体位与换位"):
                self.assertNotIn(forbidden, receipt)

            diag = advisor.diagnose_project(tmp)
            diag_text = json.dumps(diag, ensure_ascii=False)
            for forbidden in ("前戏躺回床上", "主力冲撞", "ots_depth"):
                self.assertNotIn(forbidden, diag_text)


if __name__ == "__main__":
    unittest.main()
