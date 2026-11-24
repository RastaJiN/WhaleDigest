"""Regression tests for v4.6.0 official MiniMax H3 prompt-writing integration:
1. Official H3 reference bundle (SKILL.md, ref-en.txt, base-en.txt, COMMIT_SHA.txt) shipped in references/h3-official/.
2. All 6 audiovisual prompt modes compile cleanly and pass whale_compiler:
   - empty_shot (no character/mouth/dialogue)
   - on_screen (multi-character with explicit non-speaker closed-lips lock + unique voice timbre)
   - off_screen_vo (official `says in an off-screen voiceover` + on-screen closed lips)
   - inner_monologue (same character Sx + internal thoughts + closed lips throughout)
   - narrator (dedicated global speaker ID S9, independent timbre, closed lips on visible cast)
   - silent (characters visible, no dialogue, clean ambient soundscape + non_diegetic_music: N/A)
3. Episode VoiceRegistry blocks duplicate speaker IDs and identical/colliding voice timbres across characters.
4. Gate 4 & Gate 5 enforce voice_bible.json distinctness, cross-shot speaker ID stability, and closed-lips lock on voiceover.
"""
import json
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

h3 = import_module("whale_h3_prompt")
compiler = import_module("whale_compiler")
gatekeeper = import_module("whale_gatekeeper")
diff_audit = import_module("whale_diff_audit")
png_bytes = import_module("dryrun_test").png_bytes


class OfficialH3PromptV460Test(unittest.TestCase):
    def _voice_registry(self):
        return h3.VoiceRegistry([
            {"character": "林川", "speaker_id": "S1", "preset": "young_male_earnest"},
            {"character": "赵斌", "speaker_id": "S2", "preset": "mature_male_deep"},
            {"character": "张大爷", "speaker_id": "S3", "preset": "elder_male_raspy"},
            {"character": "苏晚", "speaker_id": "S4", "preset": "young_female_soft"},
            {"character": "旁白", "speaker_id": "S9", "preset": "narrator_calm"},
        ])

    def test_official_h3_bundle_present(self):
        bundle = ROOT / "references" / "h3-official"
        for name in ("SKILL.md", "ref-en.txt", "base-en.txt", "COMMIT_SHA.txt"):
            p = bundle / name
            self.assertTrue(p.is_file() and p.stat().st_size > 20, f"Missing official file: {p}")
        self.assertTrue((ROOT / "references" / "h3-prompt-master-guide.md").is_file())

    def test_all_six_prompt_modes_compile_and_pass_lint(self):
        vreg = self._voice_registry()
        self.assertEqual([], vreg.validate_distinctness())

        # 1. Empty shot (no characters, no speech)
        p_empty = h3.compile_h3_ref2va_prompt({
            "shot_mode": "empty_shot",
            "style": "Realistic 35mm live-action cinema at dawn",
            "slots": [{"picture": 1, "kind": "scene", "desc": "the misty cedar path at dawn", "retention": "weak_reference"}],
            "framing": "wide architectural establishing shot",
            "camera": "push_tension",
            "summary": "A quiet establishing view of <Subject 1> as mist drifts across the path.",
            "action": "Morning mist drifts slowly across <Subject 1> while cedar branches sway in the faint breeze",
            "soundscape": "Soft morning wind through cedar needles and distant birdsong.",
        }, voice_registry=vreg)
        self.assertEqual([], compiler.lint_whale_prompt(p_empty)[0])
        self.assertNotIn("SPEECH:", p_empty)
        self.assertNotIn("<d>", p_empty)

        # Empty shot must reject binding a character or on_screen dialogue
        with self.assertRaises(ValueError):
            h3.compile_h3_ref2va_prompt({
                "shot_mode": "empty_shot",
                "slots": [{"picture": 1, "kind": "character", "desc": "the ranger"}],
                "summary": "Invalid empty shot with character.",
                "action": "Mist drifts.",
            })

        # 2. On-screen 3-character dialogue with closed-lips lock on both silent co-stars
        p_on = h3.compile_h3_ref2va_prompt({
            "style": "Pixar-style 3D animated cinema with crisp morning light",
            "slots": [
                {"picture": 1, "kind": "character", "name": "林川", "desc": "the young ranger in navy uniform"},
                {"picture": 2, "kind": "character", "name": "赵斌", "desc": "the senior colleague in grey jacket"},
                {"picture": 3, "kind": "character", "name": "张大爷", "desc": "the elderly resident in quilted coat"},
                {"picture": 4, "kind": "scene", "desc": "the sunlit courtyard smoking corner", "retention": "weak_reference"},
            ],
            "framing": "medium three-shot",
            "camera": "arc_subtle",
            "summary": "Three characters face each other beside the smoking barrel in <Subject 4>.",
            "action": "Inside <Subject 4>, <Subject 1> and <Subject 2> listen while <Subject 3> turns around holding a pine branch",
            "speech": {
                "mode": "on_screen",
                "speaker_subject": 3,
                "character": "张大爷",
                "verb": "asks",
                "delivery": "with lively impatience",
                "text": "熏一串腊肉怎么啦？",
            },
            "soundscape": "Crackling wood embers and light courtyard breeze.",
            "apply_de_oil": False,
        }, voice_registry=vreg)
        self.assertEqual([], compiler.lint_whale_prompt(p_on)[0])
        self.assertIn("<Subject 3> (S3)", p_on)
        self.assertIn("gruff, raspy elderly male voice", p_on)
        self.assertIn("<Subject 1> and <Subject 2> stays silent; lips remain completely closed.", p_on)

        # 3. Off-screen voiceover (speaker off-camera, visible listener lips closed)
        p_vo = h3.compile_h3_ref2va_prompt({
            "slots": [
                {"picture": 1, "kind": "character", "name": "苏晚", "desc": "the young woman by the window"},
                {"picture": 2, "kind": "scene", "desc": "the quiet study room", "retention": "weak_reference"},
            ],
            "framing": "medium close-up",
            "camera": "high_downward",
            "summary": "<Subject 1> pauses by the desk in <Subject 2> while hearing an off-screen voice.",
            "action": "Inside <Subject 2>, <Subject 1> pauses with her fingers resting on the keycard",
            "speech": {
                "mode": "off_screen_vo",
                "character": "赵斌",
                "verb": "says",
                "delivery": "with quiet warning",
                "text": "把门关上，别让人看见。",
            },
            "soundscape": "Quiet room tone and faint clock ticks.",
        }, voice_registry=vreg)
        self.assertEqual([], compiler.lint_whale_prompt(p_vo)[0])
        self.assertIn("says in an off-screen voiceover", p_vo)
        self.assertIn("deep, resonant mature male baritone", p_vo)
        self.assertIn("lips remain completely closed", p_vo)

        # 4. Inner monologue (on-screen character hears own thoughts, lips completely closed)
        p_mono = h3.compile_h3_ref2va_prompt({
            "slots": [
                {"picture": 1, "kind": "character", "name": "苏晚", "desc": "the young woman staring out the window"},
                {"picture": 2, "kind": "scene", "desc": "the dim hotel window bay", "retention": "weak_reference"},
            ],
            "framing": "tight facial close-up",
            "camera": "push_tension",
            "summary": "<Subject 1> gazes silently through the rain-streaked glass in <Subject 2>.",
            "action": "Inside <Subject 2>, <Subject 1> holds her gaze steady on the windowpane as a single breath rises",
            "speech": {
                "mode": "inner_monologue",
                "speaker_subject": 1,
                "character": "苏晚",
                "verb": "murmurs",
                "delivery": "in a hushed reflective cadence",
                "text": "这把钥匙，他根本没打算还给我。",
            },
            "soundscape": "Soft rain against glass and low indoor room tone.",
        }, voice_registry=vreg)
        self.assertEqual([], compiler.lint_whale_prompt(p_mono)[0])
        self.assertIn("<Subject 1> (S4)", p_mono)
        self.assertIn("internal thoughts", p_mono)
        self.assertIn("off-screen voiceover", p_mono)
        self.assertIn("lips remain completely closed throughout the internal monologue", p_mono)

        # 5. Independent narrator over scene + character (uses S9, never collides with cast S1..S4)
        p_nar = h3.compile_h3_ref2va_prompt({
            "slots": [
                {"picture": 1, "kind": "character", "name": "林川", "desc": "the young ranger looking up at the sky"},
                {"picture": 2, "kind": "scene", "desc": "the residential courtyard under hazy sky", "retention": "weak_reference"},
            ],
            "framing": "medium shot",
            "camera": "tilt_up_desire",
            "summary": "An off-screen narrator explains the basin inversion as <Subject 1> looks skyward in <Subject 2>.",
            "action": "Inside <Subject 2>, <Subject 1> tilts his head upward toward the hazy grey sky",
            "speech": {
                "mode": "narrator",
                "character": "旁白",
                "verb": "states",
                "delivery": "calmly",
                "text": "冬季盆地逆温像一只大锅盖，把浓烟压在小区上空。",
            },
            "soundscape": "Low urban hum and soft courtyard wind.",
        }, voice_registry=vreg)
        self.assertEqual([], compiler.lint_whale_prompt(p_nar)[0])
        self.assertIn("the narrator (S9)", p_nar)
        self.assertIn("off-screen voiceover", p_nar)
        self.assertIn("lips remain completely closed", p_nar)

        # 6. Silent character shot (no dialogue, no <d>)
        p_silent = h3.compile_h3_ref2va_prompt({
            "slots": [
                {"picture": 1, "kind": "character", "name": "苏晚", "desc": "the young woman by the desk"},
                {"picture": 2, "kind": "scene", "desc": "the warm hotel room", "retention": "weak_reference"},
            ],
            "framing": "close-up",
            "camera": "pull_reveal",
            "summary": "<Subject 1> sets down the glass silently inside <Subject 2>.",
            "action": "Inside <Subject 2>, <Subject 1> sets the glass onto the wooden desk and exhales slowly",
            "soundscape": "Soft glass clink on wood and quiet room tone.",
        }, voice_registry=vreg)
        self.assertEqual([], compiler.lint_whale_prompt(p_silent)[0])
        self.assertNotIn("SPEECH:", p_silent)
        self.assertIn("non_diegetic_music: N/A", p_silent)

    def test_voice_registry_and_gates_reject_colliding_timbres_and_missing_closed_lips(self):
        # 1) Identical timbre across two characters must be rejected
        dup_timbre = h3.VoiceRegistry([
            {"character": "角色甲", "speaker_id": "S1", "timbre": "a deep calm male baritone voice"},
            {"character": "角色乙", "speaker_id": "S2", "timbre": "a deep calm male baritone voice"},
        ])
        errs = dup_timbre.validate_distinctness()
        self.assertTrue(any("音色撞车拦截" in e for e in errs), errs)

        # 2) Duplicate speaker ID must be rejected
        dup_sid = h3.VoiceRegistry([
            {"character": "角色甲", "speaker_id": "S1", "timbre": "a crisp high young male voice"},
            {"character": "角色乙", "speaker_id": "S1", "timbre": "a gruff raspy elderly male voice"},
        ])
        errs2 = dup_sid.validate_distinctness()
        self.assertTrue(any("共用了同一个声源编号" in e for e in errs2), errs2)

        # 3) Gate 4 & Gate 5 reject voiceover shot missing closed-lips lock when a person is on-screen
        bad_vo_prompt = (
            "subject_definitions:\n"
            "<Subject 1> is the young woman from <Picture 1>.\n"
            "<Subject 2> is the study room from <Picture 2>.\n"
            "summary: [reference generation] Voiceover plays over <Subject 1>.\n"
            "retention_analysis:\n"
            "<Subject 1>: fully_preserved - identity locked to <Picture 1>.\n"
            "<Subject 2>: weak_reference - room layout from <Picture 2>.\n"
            "detailed_description:\n"
            "Camera: medium close-up, slow dolly push-in.\n"
            "[Shot 1] Inside <Subject 2>, <Subject 1> stares at the desk.\n"
            "SPEECH: From 0.50s to 2.00s, the narrator (S9) says in an off-screen voiceover: <d>[Chinese]她没有回头。</d>.\n"
            "overall_soundscape: Quiet room tone.\n"
            "non_diegetic_music: N/A"
        )
        batch = {
            "schema": "h3-drama-task",
            "aspect": "16:9",
            "total_frames": 90,
            "total_duration": 3.75,
            "batch_shots": [{
                "id": 1,
                "shot_id": "S01",
                "pose": "srs_female",
                "shot_size": "cu",
                "camera_motion": "push_tension",
                "frames": 90,
                "duration": 3.75,
                "ref_images": ["woman.png", "room.png"],
                "prompt": bad_vo_prompt,
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / "00_资产"
            assets.mkdir()
            for fn in ("woman.png", "room.png"):
                (assets / fn).write_bytes(png_bytes())
            (root / "批量任务.json").write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")

            ok4, msg4 = gatekeeper.audit_step_4(tmp)
            self.assertFalse(ok4, msg4)
            self.assertIn("闭嘴锁", msg4)

            rep = diff_audit.audit_project(tmp)
            self.assertTrue(any("闭嘴锁" in v for v in rep["violations"]), rep["violations"])

    def test_014b_non_bed_scene_blocks_mattress_soundscape_leak(self):
        # 014B scene-material rule: industrial/desk/table scenes must not leak mattress/bedsheet/pillow cues
        leaked_prompt = (
            "subject_definitions:\n"
            "<Subject 1> is the woman from <Picture 1>.\n"
            "<Subject 2> is the industrial steel desk from <Picture 2>.\n"
            "summary: [reference generation] <Subject 1> leans on <Subject 2>.\n"
            "retention_analysis:\n"
            "<Subject 1>: fully_preserved - identity from <Picture 1>.\n"
            "<Subject 2>: weak_reference - cold scratched steel desk from <Picture 2>.\n"
            "detailed_description:\n"
            "Camera: medium close-up, 90-degree side profile.\n"
            "[Shot 1] Inside the control room, <Subject 1> leans over the rigid steel desk.\n"
            "overall_soundscape: Rhythmic mattress vibration and soft bedsheet rustling.\n"
            "non_diegetic_music: N/A"
        )
        batch = {
            "schema": "h3-drama-task",
            "aspect": "16:9",
            "total_frames": 90,
            "total_duration": 3.75,
            "batch_shots": [{
                "id": 1,
                "shot_id": "S014B",
                "pose": "table_doggy",
                "shot_size": "mcu",
                "camera_motion": "static_side",
                "frames": 90,
                "duration": 3.75,
                "ref_images": ["woman.png", "steel_desk.png"],
                "prompt": leaked_prompt,
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / "00_资产"
            assets.mkdir()
            for fn in ("woman.png", "steel_desk.png"):
                (assets / fn).write_bytes(png_bytes())
            (root / "批量任务.json").write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
            rep = diff_audit.audit_project(tmp)
            self.assertTrue(any("非床场景床垫词污染(014B)" in v for v in rep["violations"]), rep["violations"])


if __name__ == "__main__":
    unittest.main()
