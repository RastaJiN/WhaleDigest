"""Regression tests for real-production H3 fixes (v4.5.9).

Covers:
1. Positive-only nudity lock (no garment/shirt/trousers negative token roots).
2. Wardrobe mode explicit override (nude_all / dressed_all) without cross-bleeding
   dressed dialogue scenes into intimacy soundscapes.
3. Supine/intimate emotion body/face variants (no standing 'floor'/'lap' conflicts).
4. Anti-clipping sealed pelvic junction and sweat-preserving positive sanitizer.
5. Landscape solo camera wording & static_top_90 / static / static_top availability.
6. Silent SPEECH declaration tolerance vs mixed silent+spoken rejection.
7. Non-dict dialogue field resilience in whale_diff_audit.
"""
import json
import re
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

compiler = import_module("whale_compiler")
core = import_module("whale_core")
diff_audit = import_module("whale_diff_audit")
scene = import_module("whale_scene")


class ProductionFixesV459(unittest.TestCase):
    def test_nude_all_keeps_nudity_lock_and_intimate_sound_without_garment_roots(self):
        poses = core.load_poses()
        shots, actual = scene.build_scene(["env_establish", "srs_female", "cowgirl", "outro_solo"], 24.0, poses)
        with tempfile.TemporaryDirectory() as tmp:
            _, _, bj = scene.save_project_artifacts(
                tmp, shots, actual, 24.0, scene="hotel suite", aspect="16:9", wardrobe_mode="nude_all"
            )
            batch = json.loads(Path(bj).read_text(encoding="utf-8"))
            for row in batch["batch_shots"]:
                self.assertEqual(row["wardrobe_state"], "nude", row["shot_id"])
                prompt = row["prompt"]
                # Must pass compiler cleanly
                errors, _ = compiler.lint_task_prompt(row, batch)
                self.assertEqual(errors, [], f"{row['shot_id']}: {errors}")
                # Must NOT inject negative garment roots that trigger clothing hallucinations in H3
                self.assertFalse(
                    re.search(r"\b(no garment|shirt|trousers|underwear)\b", prompt, re.I),
                    f"{row['shot_id']} leaked garment root: {prompt}",
                )
                # Soundscape must NOT revert to dressed fabric/footsteps in a nude segment
                self.assertNotIn("Crisp fabric rustle, measured footsteps", prompt, row["shot_id"])
                if row["tier"] != "C_empty_cut":
                    self.assertIn("completely unclothed", prompt, row["shot_id"])

    def test_dressed_dialogue_srs_does_not_bleed_into_intimate_sound_or_nudity(self):
        poses = core.load_poses()
        shots, actual = scene.build_scene(["env_establish", "srs_female", "srs_male"], 18.0, poses)
        with tempfile.TemporaryDirectory() as tmp:
            _, _, bj = scene.save_project_artifacts(
                tmp, shots, actual, 18.0, scene="office", aspect="16:9", wardrobe_mode="dressed_all"
            )
            batch = json.loads(Path(bj).read_text(encoding="utf-8"))
            for row in batch["batch_shots"]:
                self.assertEqual(row["wardrobe_state"], "dressed", row["shot_id"])
                prompt = row["prompt"]
                self.assertNotIn("completely unclothed", prompt)
                self.assertNotIn("skin-on-skin collision slaps", prompt)
                self.assertNotIn("Close heavy breathing, soft bare skin contact", prompt)
                if row["tier"] in ("B_solo_female", "B_solo_male"):
                    self.assertNotIn("both subjects", prompt)

    def test_supine_emotion_avoids_standing_conflicts_and_no_piston_or_sweat_erasure(self):
        shot = {"pose": "missionary", "pose_zh": "传教士", "size": "mcu", "cam": "static_top_90", "text_en": "light sweat on shoulders"}
        prompt = core.single_shot_prompt(
            shot, 0, 1, 5.0, "medium close-up", scene.CAMS_EN_LANDSCAPE["static_top_90"],
            emotion="submission", aspect="16:9", nudity=True
        )
        self.assertIn("Sealed pelvic junction", prompt)
        self.assertNotIn("piston strokes", prompt)
        self.assertIn("light sweat", prompt)
        self.assertNotIn("dry matte skin", prompt)
        self.assertNotIn("folding in the lap", prompt)
        self.assertNotIn("lowered toward the floor", prompt)
        self.assertIn("Sealed pelvic junction", core.insert_hint("missionary"))
        self.assertNotIn("piston strokes", core.insert_hint("missionary"))

    def test_landscape_cameras_include_top_down_and_solo_variants(self):
        for key in ("static", "static_top_90", "static_top"):
            self.assertIn(key, scene.CAMS_EN_LANDSCAPE)
        for key in ("static_side", "static_rear", "static_front", "pan_left_right"):
            self.assertIn(key, scene.CAMS_EN_LANDSCAPE_SOLO)
            self.assertRegex(scene.CAMS_EN_LANDSCAPE_SOLO[key], r"single[- ]subject")

    def test_compiler_allows_silent_speech_line_and_blocks_mixed_silent_and_spoken(self):
        base_prompt = (
            "subject_definitions:\n"
            "<Subject 1> is the woman from <Picture 1>.\n"
            "<Subject 3> is the room from <Picture 3>.\n"
            "summary: Quiet reaction.\n"
            "retention_analysis:\n"
            "<Subject 1>: fully_preserved from <Picture 1>.\n"
            "<Subject 3>: weak_reference from <Picture 3>.\n"
            "detailed_description:\n"
            "Camera: Static close-up.\n"
            "[Shot 1] <Subject 1> breathes quietly.\n"
            "SPEECH: No spoken dialogue; natural breathing only.\n"
            "overall_soundscape: Quiet room tone.\n"
            "non_diegetic_music: N/A"
        )
        errors, _ = compiler.lint_whale_prompt(base_prompt)
        self.assertEqual(errors, [])

        mixed = base_prompt + "\nSPEECH: From 1.00s to 2.00s, only <Subject 1> (S1) says: <d>[Chinese]你好。</d>."
        mixed_errors, _ = compiler.lint_whale_prompt(mixed)
        self.assertTrue(any("只允许一条独立台词" in e for e in mixed_errors), mixed_errors)

    def test_diff_audit_handles_string_or_list_dialogue_without_crashing(self):
        png_bytes = import_module("dryrun_test").png_bytes
        poses = core.load_poses()
        shots, actual = scene.build_scene(["blocking_2s"], 6.0, poses)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / "00_资产"
            assets.mkdir()
            for name in ("female_ref.png", "male_ref.png", "scene_main.png"):
                (assets / name).write_bytes(png_bytes())
            _, _, bj = scene.save_project_artifacts(
                tmp, shots, actual, 6.0, lines="1:男子A:开会了。", scene="office", aspect="16:9"
            )
            batch = json.loads(Path(bj).read_text(encoding="utf-8"))
            batch["batch_shots"][0]["dialogue"] = "开会了。"
            Path(bj).write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
            rep = diff_audit.audit_project(tmp)
            self.assertIsInstance(rep, dict)
            self.assertIn("violations", rep)


if __name__ == "__main__":
    unittest.main()
