"""Regression tests for v4.5.11 intimate camera/framing/stance fixes:
1. POSE_SHOT_PLAN & dynamic_cycle never pair B_solo_* with ots_depth, rear poses with ots_depth/static_rear,
   standing poses with wide, or two-person penetration poses with face (which would silently drop male ref).
2. STANCE_LOCKS_EN injects positive-only physical stance locks (no forbidden negation words) for standing/rear/
   supine/cowgirl/oral poses, and standing/solo shots do not inherit supine 'against the support surface'.
3. stand_doggy_wall / missionary / anal beatsEn[0] include sustained action beyond 2 seconds.
4. whale_diff_audit rejects solo+ots_depth, standing+wide, rear+static_rear, and two-person pose + solo tier.
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
diff_audit = import_module("whale_diff_audit")
compiler = import_module("whale_compiler")


class ProductionV4511Test(unittest.TestCase):
    def test_pose_shot_plan_removes_known_camera_framing_traps(self):
        # Single-subject male reverse shot must not default to over-the-shoulder
        for _, cam in scene.POSE_SHOT_PLAN["srs_male"]:
            self.assertNotIn("ots", cam)
        # Rear-entry poses must not default to ots_depth or static_rear
        for pid in ("stand_doggy_wall", "stand_bend_doggy", "doggy", "table_doggy"):
            for sz, cam in scene.POSE_SHOT_PLAN[pid]:
                self.assertNotIn(cam, ("ots_depth", "ots", "static_rear"), f"{pid} bad cam {cam}")
                self.assertNotEqual(sz, "wide", f"{pid} bad wide framing")
                self.assertNotEqual(sz, "face", f"{pid} face triggers silent B_solo_female")
        # Standing carry_insert must not default to wide
        for sz, _ in scene.POSE_SHOT_PLAN["carry_insert"]:
            self.assertNotEqual(sz, "wide")
        # Two-person penetration plans must not use face (which silently strips male slot)
        for pid in ("missionary", "missionary_legup", "cowgirl"):
            for sz, _ in scene.POSE_SHOT_PLAN[pid]:
                self.assertNotEqual(sz, "face", f"{pid} should not use face")

    def test_stance_lock_injected_positive_only_and_no_supine_leak(self):
        poses = core.load_poses()
        # Stand doggy wall beatsEn[0] must specify standing & sustained rhythm
        b0 = poses["stand_doggy_wall"]["beatsEn"][0]
        self.assertIn("stands upright", b0.lower())
        self.assertIn("continuing", b0.lower())

        shot = {
            "pose": "stand_doggy_wall",
            "size": "mcu",
            "text_en": b0,
        }
        prompt = core.single_shot_prompt(
            shot, 0, 2, 5.0,
            scene.SHOT_SIZES_EN_LANDSCAPE["mcu"],
            scene.CAMS_EN_LANDSCAPE["static_side"],
            aspect="16:9", nudity=True, tier="A_two_shot",
        )
        errs, _ = compiler.lint_whale_prompt(prompt)
        self.assertEqual([], errs, errs)
        self.assertIn("Stance lock:", prompt)
        self.assertIn("feet planted firmly on the floor", prompt)
        self.assertIn("traveling laterally across the frame", prompt)
        # Positive-only: must not inject supine phrasing or negative 'no bed' / 'never kneel'
        self.assertNotIn("against the support surface", prompt.lower())
        self.assertNotIn("no bed", prompt.lower())
        self.assertNotIn("never kneel", prompt.lower())

        # Nude solo reverse shot must also not force supine body action
        solo_shot = {"pose": "srs_male", "size": "cu", "text_en": "Man A presses close in tense questioning"}
        solo_prompt = core.single_shot_prompt(
            solo_shot, 1, 2, 5.17,
            scene.SHOT_SIZES_EN_LANDSCAPE["cu"],
            scene.CAMS_EN_LANDSCAPE_SOLO["static_front"],
            lines="你老公平时也这么弄你吗？", speaker="男子A",
            aspect="16:9", nudity=True, tier="B_solo_male",
        )
        self.assertNotIn("against the support surface", solo_prompt.lower())

    def test_diff_audit_blocks_framing_camera_tier_mismatches(self):
        valid_prompt = (
            "subject_definitions:\n"
            "<Subject 1> is the woman from <Picture 1>.\n"
            "<Subject 2> is the man from <Picture 2>.\n"
            "<Subject 3> is the bedroom from <Picture 3>.\n"
            "summary: Intimate wall scene.\n"
            "retention_analysis:\n"
            "<Subject 1>: fully_preserved for identity from <Picture 1>.\n"
            "<Subject 2>: fully_preserved for identity from <Picture 2>.\n"
            "<Subject 3>: weak_reference for framing from <Picture 3>.\n"
            "detailed_description:\n"
            "Camera: medium close-up, 90-degree side profile angle, tripod locked.\n"
            "[Shot 1] Inside <Subject 3>, <Subject 1> braces on the wall while <Subject 2> stands behind her.\n"
            "overall_soundscape: Soft breathing.\n"
            "non_diegetic_music: N/A"
        )
        cases = [
            ("solo_ots", {"pose": "srs_male", "tier": "B_solo_male", "shot_size": "cu", "camera_motion": "ots_depth"}, "单人镜禁配过肩机位"),
            ("standing_wide", {"pose": "stand_doggy_wall", "tier": "A_two_shot", "shot_size": "wide", "camera_motion": "static_side"}, "站立系禁配wide全景"),
            ("rear_static_rear", {"pose": "stand_doggy_wall", "tier": "A_two_shot", "shot_size": "mcu", "camera_motion": "static_rear"}, "后入系禁配正后方static_rear"),
            ("two_pose_solo_tier", {"pose": "cowgirl", "tier": "B_solo_female", "shot_size": "mcu", "camera_motion": "low_upward"}, "双人体位误配单人tier"),
        ]
        for label, overrides, expected_tag in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                shot = {
                    "id": 1,
                    "shot_id": "shot_01",
                    "frames": 90,
                    "duration": 3.75,
                    "ref_images": ["f.png", "m.png", "s.png"],
                    "prompt": valid_prompt,
                    **overrides,
                }
                batch = {
                    "schema": "h3-drama-task",
                    "total_frames": 90,
                    "total_duration": 3.75,
                    "batch_shots": [shot],
                }
                (Path(tmp) / "批量任务.json").write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
                rep = diff_audit.audit_project(tmp)
                self.assertTrue(
                    any(expected_tag in v for v in rep["violations"]),
                    f"{label}: expected '{expected_tag}' in {rep['violations']}",
                )


if __name__ == "__main__":
    unittest.main()
