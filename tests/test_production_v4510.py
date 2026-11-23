"""Regression tests for v4.5.10 fixes derived from Guardian Diary production logs:
1. Support 1..9 ordered ref_images across compiler, task source, exporter, and runner
   (disconnecting unused ref_image_1..8 ports on Node 265 without requiring <Picture 3>).
2. Accept episode/revision-qualified shot headers in Gate 3 (e.g. SHOT-EP001-01R, R01-01).
"""
import json
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

compiler = import_module("whale_compiler")
task_source = import_module("whale_task_source")
exporter = import_module("export_comfy_payload")
gatekeeper = import_module("whale_gatekeeper")
runner = import_module("whale_runner")


PROMPT_TWO_REFS = """subject_definitions:
<Subject 1> is the ranger from <Picture 1>.
<Subject 2> is the sunlit smoking corner from <Picture 2>.
summary: The ranger inspects the wooden shed corner alone.
retention_analysis:
<Subject 1>: fully_preserved for identity from <Picture 1>.
<Subject 2>: weak_reference for framing from <Picture 2>.
detailed_description:
Camera: Static medium close-up, matte velvet skin finish.
[Shot 1] Inside <Subject 2>, the camera holds steady; <Subject 1> tilts his chin and checks the latch.
SPEECH: From 0.50s to 2.20s, only <Subject 1> (S1) says: <d>[Chinese]这里还没凉透。</d>.
overall_soundscape: Quiet wind through pine leaves and faint wooden creaks.
non_diegetic_music: N/A"""

PROMPT_ONE_REF = """subject_definitions:
<Subject 1> is the mascot character from <Picture 1>.
summary: The mascot hops onto the log and waves.
retention_analysis:
<Subject 1>: fully_preserved for identity from <Picture 1>.
detailed_description:
Camera: Static medium shot, matte velvet skin finish.
[Shot 1] Against clean morning daylight, the camera holds steady; <Subject 1> raises one paw and smiles.
overall_soundscape: Soft birdsong and morning breeze.
non_diegetic_music: N/A"""


class ProductionV4510Test(unittest.TestCase):
    def _make_batch(self, shots):
        total = sum(s["frames"] for s in shots)
        return {
            "schema": "h3-drama-task",
            "project": "EP001_TEST",
            "aspect": "16:9",
            "total_frames": total,
            "total_duration": round(total / 24.0, 2),
            "batch_shots": shots,
        }

    def test_one_and_two_ref_images_pass_full_validation_and_disconnect_unused_slots(self):
        shots = [
            {
                "shot_id": "R01-01",
                "frames": 90,
                "duration": 3.75,
                "ref_images": ["ranger_v1.png", "corner_v1.png"],
                "lora_mystic_strength": 0.0,
                "prompt": PROMPT_TWO_REFS,
            },
            {
                "shot_id": "R01-02",
                "frames": 73,
                "duration": 3.04,
                "ref_images": ["mascot_v1.png"],
                "lora_mystic_strength": 0.0,
                "prompt": PROMPT_ONE_REF,
            },
        ]
        batch = self._make_batch(shots)

        # 1) Compiler & task_source accept 1-ref and 2-ref prompts without <Picture 3>
        for s in shots:
            errs, _ = compiler.lint_task_prompt(s, batch)
            self.assertEqual([], errs, f"{s['shot_id']} lint failed: {errs}")
        task_source.validate_batch_metadata(batch)

        # 2) Gate 4 & export_comfy_payload verify cleanly (with real assets in 00_资产/)
        from dryrun_test import png_bytes
        with tempfile.TemporaryDirectory() as folder:
            assets = Path(folder) / "00_资产"
            assets.mkdir()
            for fn in ("ranger_v1.png", "corner_v1.png", "mascot_v1.png"):
                (assets / fn).write_bytes(png_bytes())
            (Path(folder) / "批量任务.json").write_text(
                json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            ok_g4, msg_g4 = gatekeeper.audit_step_4(folder)
            self.assertTrue(ok_g4, msg_g4)
            ok_ex, msg_ex = exporter.verify_batch_json(folder)
            self.assertTrue(ok_ex, msg_ex)

        # 3) Runner builds real ComfyUI graph and disconnects unused ref_image ports
        template = json.loads(Path(runner.DEFAULT_WF).read_text(encoding="utf-8"))

        wf_two = runner.build_shot_workflow(template, shots[0], aspect="16:9", batch=batch)
        p265_two = wf_two["265"]["inputs"]
        self.assertEqual(wf_two["51"]["inputs"]["image"], "ranger_v1.png")
        self.assertEqual(wf_two["49"]["inputs"]["image"], "corner_v1.png")
        self.assertEqual(p265_two.get("ref_images.ref_image_0"), ["51", 0])
        self.assertEqual(p265_two.get("ref_images.ref_image_1"), ["49", 0])
        self.assertNotIn("ref_images.ref_image_2", p265_two)
        self.assertNotIn("ref_images.ref_image_3", p265_two)

        wf_one = runner.build_shot_workflow(template, shots[1], aspect="16:9", batch=batch)
        p265_one = wf_one["265"]["inputs"]
        self.assertEqual(wf_one["51"]["inputs"]["image"], "mascot_v1.png")
        self.assertEqual(p265_one.get("ref_images.ref_image_0"), ["51", 0])
        self.assertNotIn("ref_images.ref_image_1", p265_one)
        self.assertNotIn("ref_images.ref_image_2", p265_one)

    def test_zero_ref_images_and_out_of_range_picture_still_rejected(self):
        with self.assertRaises(task_source.TaskSourceError):
            task_source.validate_image_references([])

        bad_shot = {
            "shot_id": "R01-03",
            "frames": 90,
            "duration": 3.75,
            "ref_images": ["ranger_v1.png"],
            "prompt": PROMPT_TWO_REFS,  # references <Picture 2> when only 1 ref_image is bound
        }
        errs, _ = compiler.lint_task_prompt(bad_shot, self._make_batch([bad_shot]))
        self.assertTrue(any("<Picture 2>" in e for e in errs), errs)

        no_pic_prompt = PROMPT_ONE_REF.replace("from <Picture 1>", "in morning light")
        errs2, _ = compiler.lint_whale_prompt(no_pic_prompt)
        self.assertTrue(any("空间锚点错误" in e for e in errs2), errs2)

    def test_gate3_accepts_episode_and_revision_shot_headers(self):
        board = """# EP001 分镜
### SHOT-EP001-01R
- Track: Ref2V
- 时长：3.75s
- 景别：中近景
- 机位：固定
- 台词：<d>[Chinese]这里还没凉透。</d>

### R01-02
- Track: Ref2V
- 时长：3.04s
- 景别：中景
- 机位：slow_push
"""
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "分镜.md").write_text(board, encoding="utf-8")
            ok, msg = gatekeeper.audit_step_3(folder)
            self.assertTrue(ok, msg)
            self.assertIn("2 镜", msg)


if __name__ == "__main__":
    unittest.main()
