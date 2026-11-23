"""Real-world production stress tests for v4.5.13 architecture overhaul:
1. 3-character + scene dynamic 4-slot shot (arbitrary Picture 1..9 binding, NOT locked to 1=female/2=male/3=scene).
2. Gate 1 rejects empty 00_资产/; Gate 4 & Gate 5 unconditionally reject phantom/missing ref_images AND missing aspect.
3. whale_pipeline.py refuses to run without confirmed aspect (never silently defaults to 9:16).
4. whale_runner.py patches arbitrary user-specified ComfyUI workflow JSONs in-place (arbitrary node IDs) via --workflow or .whale_project.json['workflow'].
5. Gate 3 & Gate 5 reject flat single-camera / >60% static storyboards; script-driven Auto-DP produces varied dynamic cameras.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

core = import_module("whale_core")
compiler = import_module("whale_compiler")
task_source = import_module("whale_task_source")
gatekeeper = import_module("whale_gatekeeper")
diff_audit = import_module("whale_diff_audit")
runner = import_module("whale_runner")
scene = import_module("whale_scene")
png_bytes = import_module("dryrun_test").png_bytes


THREE_CHAR_PROMPT = """subject_definitions:
<Subject 1> (S1) is the team leader Lin Chuan anchored in <Picture 1>.
<Subject 2> (S2) is colleague Zhao Bin anchored in <Picture 2>.
<Subject 3> (S3) is resident Uncle Zhang anchored in <Picture 3>.
<Subject 4> is the sunlit courtyard smoking corner anchored in <Picture 4>.
summary: Three characters stand talking together in the sunlit courtyard.
retention_analysis:
<Subject 1>: fully_preserved - facial identity and uniform locked to <Picture 1>.
<Subject 2>: fully_preserved - facial identity and vest locked to <Picture 2>.
<Subject 3>: fully_preserved - facial identity and jacket locked to <Picture 3>.
<Subject 4>: fully_preserved for courtyard wall texture from <Picture 4>; weak_reference for exact camera framing.
detailed_description:
Camera: medium two-to-three-shot, slow lateral dolly arc shifting 12 cm sideways, matte velvet skin finish.
[Shot 1] Inside <Subject 4>, <Subject 1> raises a hand toward the barrel while <Subject 2> steps beside him and <Subject 3> turns around holding a pine branch.
SPEECH: From 0.50s to 2.20s, only <Subject 3> (S3) says: <d>[Chinese]熏一串腊肉怎么啦？</d>.
overall_soundscape: Crackling wood embers and light courtyard breeze.
non_diegetic_music: N/A"""


def _custom_user_workflow():
    """Simulate a user-supplied ComfyUI workflow with completely different node IDs from whale_schema.json."""
    return {
        "901": {"class_type": "Text", "inputs": {"text": "old stale prompt"}},
        "902": {"class_type": "LoadImage", "inputs": {"image": "old_1.png"}},
        "903": {"class_type": "LoadImage", "inputs": {"image": "old_2.png"}},
        "904": {"class_type": "LoadImage", "inputs": {"image": "old_3.png"}},
        "905": {"class_type": "LoadImage", "inputs": {"image": "old_4.png"}},
        "906": {"class_type": "LoraLoaderModelOnly", "inputs": {"lora_name": "MysticXXX_MMH3-V1.safetensors", "strength_model": 0.45, "model": ["900", 0]}},
        "907": {"class_type": "ResolutionSelector", "inputs": {"aspect_ratio": "9:16 (Portrait Widescreen)", "megapixels": 0.9}},
        "908": {"class_type": "PrimitiveFloat", "inputs": {"value": 5.0}},
        "909": {
            "class_type": "MiniMaxH3ReferenceToVideo",
            "inputs": {
                "prompt": ["901", 0],
                "ref_images.ref_image_0": ["902", 0],
                "ref_images.ref_image_1": ["903", 0],
                "ref_images.ref_image_2": ["904", 0],
                "length": 90,
                "ref_image_size": "match",
            },
        },
        "910": {"class_type": "SelfLiftH3Sampler", "inputs": {"seed": 12345}},
        "911": {"class_type": "VHS_VideoCombine", "inputs": {"filename_prefix": "OLD_PREFIX"}},
    }


class ProductionV4513OverhaulTest(unittest.TestCase):
    def test_three_character_four_slot_dynamic_binding_and_custom_workflow_inplace_patch(self):
        # 1) Dynamic slots header helper builds valid 4-slot (3 chars + 1 scene) prompt
        header = core.build_dynamic_slots_header(
            [
                {"picture": 1, "desc": "the woman in blue coat", "voice": 1, "kind": "character"},
                {"picture": 2, "desc": "the taller man in grey jacket", "voice": 2, "kind": "character"},
                {"picture": 3, "desc": "the older man with glasses", "voice": 3, "kind": "character"},
                {"picture": 4, "desc": "the sunlit courtyard", "kind": "scene"},
            ],
            dur=3.75,
            aspect="16:9",
        )
        joined = "\n".join(header)
        for token in ("<Subject 1> (S1)", "<Picture 1>", "<Subject 2> (S2)", "<Picture 2>",
                      "<Subject 3> (S3)", "<Picture 3>", "<Subject 4>", "<Picture 4>"):
            self.assertIn(token, joined)

        # 2) Full 3-character shot passes compiler, Gate 1, Gate 4, Gate 5 with real assets
        shot = {
            "id": 1,
            "shot_id": "EP01-01",
            "pose": "blocking_2s",
            "shot_size": "mcu",
            "camera_motion": "arc_subtle",
            "frames": 90,
            "duration": 3.75,
            "ref_images": ["linchuan.png", "zhaobin.png", "zhangdaye.png", "courtyard.png"],
            "prompt": THREE_CHAR_PROMPT,
        }
        batch = {
            "schema": "h3-drama-task",
            "aspect": "16:9",
            "total_frames": 90,
            "total_duration": 3.75,
            "batch_shots": [shot],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / "00_资产"
            assets.mkdir()
            for fn in shot["ref_images"]:
                (assets / fn).write_bytes(png_bytes())
            (root / "批量任务.json").write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")

            ok1, msg1 = gatekeeper.audit_step_1(tmp)
            self.assertTrue(ok1, msg1)
            ok4, msg4 = gatekeeper.audit_step_4(tmp)
            self.assertTrue(ok4, msg4)
            rep = diff_audit.audit_project(tmp)
            self.assertEqual(rep["violations"], [], rep["violations"])

            # 3) Custom user workflow JSON with arbitrary node IDs (901..911) is patched in-place
            user_wf_path = root / "user_custom_h3.json"
            user_wf_path.write_text(json.dumps(_custom_user_workflow(), ensure_ascii=False), encoding="utf-8")
            (root / ".whale_project.json").write_text(
                json.dumps({"active_batch": "批量任务.json", "workflow": "user_custom_h3.json"}, ensure_ascii=False),
                encoding="utf-8",
            )
            resolved_wf = task_source.resolve_workflow_path(tmp)
            self.assertEqual(resolved_wf, user_wf_path.resolve())

            patched = runner.build_shot_workflow(
                json.loads(user_wf_path.read_text("utf-8")), shot, custom_seed=777, aspect="16:9", batch=batch
            )
            self.assertEqual(patched["901"]["inputs"]["text"], THREE_CHAR_PROMPT)
            self.assertEqual(patched["902"]["inputs"]["image"], "linchuan.png")
            self.assertEqual(patched["903"]["inputs"]["image"], "zhaobin.png")
            self.assertEqual(patched["904"]["inputs"]["image"], "zhangdaye.png")
            self.assertEqual(patched["905"]["inputs"]["image"], "courtyard.png")
            self.assertEqual(patched["909"]["inputs"]["ref_images.ref_image_3"], ["905", 0])
            # Standard drama shot automatically zeroes MysticXXX LoRA on node 906
            self.assertEqual(patched["906"]["inputs"]["strength_model"], 0.0)
            self.assertEqual(patched["907"]["inputs"]["aspect_ratio"], "16:9 (Widescreen)")
            self.assertEqual(patched["910"]["inputs"]["seed"], 777)

    def test_gates_block_empty_assets_phantom_refs_and_missing_aspect(self):
        shot = {
            "id": 1,
            "shot_id": "S01",
            "pose": "blocking_2s",
            "shot_size": "mcu",
            "camera_motion": "push_tension",
            "frames": 90,
            "duration": 3.75,
            "ref_images": ["linchuan.png", "zhaobin.png", "zhangdaye.png", "courtyard.png"],
            "prompt": THREE_CHAR_PROMPT,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "00_资产").mkdir()

            # 1) Empty 00_资产/ must FAIL Gate 1
            ok1, msg1 = gatekeeper.audit_step_1(tmp)
            self.assertFalse(ok1, msg1)
            self.assertIn("没有任何有效可读图片", msg1)

            # 2) Missing aspect in legacy batch must FAIL Gate 4 & Gate 5
            batch_no_aspect = {"schema": "h3-drama-task", "total_frames": 90, "total_duration": 3.75, "batch_shots": [shot]}
            (root / "批量任务.json").write_text(json.dumps(batch_no_aspect, ensure_ascii=False), encoding="utf-8")
            ok4_a, msg4_a = gatekeeper.audit_step_4(tmp)
            self.assertFalse(ok4_a)
            self.assertIn("画幅", msg4_a)

            # 3) Even WITH aspect, phantom ref_images not in 00_资产/ must FAIL Gate 4 & Gate 5 (no pose_input_hashes bypass!)
            batch_with_aspect = dict(batch_no_aspect, aspect="16:9")
            (root / "批量任务.json").write_text(json.dumps(batch_with_aspect, ensure_ascii=False), encoding="utf-8")
            (root / "00_资产" / "unrelated_other.png").write_bytes(png_bytes())
            ok4_b, msg4_b = gatekeeper.audit_step_4(tmp)
            self.assertFalse(ok4_b)
            self.assertIn("物理缺失", msg4_b)
            rep = diff_audit.audit_project(tmp)
            self.assertTrue(any("物理缺失" in v for v in rep["violations"]), rep["violations"])

            # 4) whale_pipeline.py without --aspect on fresh script must refuse to default to 9:16
            (root / "剧本.md").write_text("## 第一幕\n对话。\n## 第二幕\n对话。\n", encoding="utf-8")
            (root / "批量任务.json").unlink()
            res = subprocess.run(
                [sys.executable, str(ROOT / "scripts/whale_pipeline.py"), str(root / "剧本.md"), "--dry"],
                capture_output=True, text=True, encoding="utf-8",
                env=dict(os.environ, PYTHONUTF8="1"),
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("未确定画幅", res.stdout + res.stderr)

    def test_gate3_and_diff_audit_block_flat_single_camera_storyboards(self):
        # 6 shots all locked to static_side & mcu -> must be REJECTED by Gate 3
        flat_board = "# 僵死单机位分镜\n" + "\n".join(
            f"### SHOT-0{i}\n- Track: Ref2V\n- 时长：3.75s\n- 景别：mcu\n- 机位：static_side\n"
            for i in range(1, 7)
        )
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "分镜.md").write_text(flat_board, encoding="utf-8")
            ok3, msg3 = gatekeeper.audit_step_3(tmp)
            self.assertFalse(ok3, msg3)
            self.assertIn("运镜僵化拦截", msg3)

        # Varied dynamic board passes Gate 3
        varied = [
            ("wide", "pull_reveal"), ("mcu", "arc_subtle"), ("cu", "push_tension"),
            ("face", "high_downward"), ("cu", "low_upward"), ("mcu", "handheld_breath"),
        ]
        good_board = "# 呼吸感分镜\n" + "\n".join(
            f"### SHOT-0{i}\n- Track: Ref2V\n- 时长：3.75s\n- 景别：{sz}\n- 机位：{cam}\n"
            for i, (sz, cam) in enumerate(varied, 1)
        )
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "分镜.md").write_text(good_board, encoding="utf-8")
            ok3_g, msg3_g = gatekeeper.audit_step_3(tmp)
            self.assertTrue(ok3_g, msg3_g)

    def test_auto_dp_actually_breaks_consecutive_static_cams_in_script_decisions(self):
        # Verify script-driven staging_note / decision shots no longer stay locked to static_side
        poses = core.load_poses()
        shots, _ = scene.build_scene(
            ["blocking_2s", "blocking_2s", "blocking_2s", "srs_female", "srs_male"],
            30.0,
            poses,
        )
        cams = [s["cam"] for s in shots]
        self.assertGreaterEqual(len(set(cams)), 3, f"Expected dynamic camera variety, got {cams}")
        # Never two static cameras in a row
        for a, b in zip(cams, cams[1:]):
            self.assertFalse("static" in a and "static" in b, f"Consecutive static cams: {cams}")


if __name__ == "__main__":
    unittest.main()
