import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "sd_core"))

import whale_core as core
import whale_scene as scene
import whale_compiler as compiler
import whale_h3_prompt as h3
import whale_script_intake as intake
import whale_pipeline_check as pcheck
import creator_views


class FullRefactorV5Test(unittest.TestCase):
    def test_sd_core_ports_and_form_cards_ready(self):
        sd_scripts = ROOT / "scripts" / "sd_core"
        for fn in (
            "episode_intake.py", "screenplay_index.py", "duration_estimate.py",
            "storyboard_check.py", "container_check.py", "motion_timing_check.py",
            "asset_check.py", "image_prompt_check.py", "review_check.py",
        ):
            self.assertTrue((sd_scripts / fn).is_file(), f"missing {fn}")
        fc_dir = ROOT / "references" / "sd_core" / "form-cards"
        for card in ("实拍.md", "二维动态漫.md", "风格化三维.md", "国漫二次元.md", "水墨笔触.md", "Q版表达.md"):
            self.assertTrue((fc_dir / card).is_file(), f"missing form-card {card}")

    def test_poses_matrix_is_100_percent_purified(self):
        mx = json.loads((ROOT / "references" / "whale_poses_matrix.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(mx), 94)
        neg_re = re.compile(r"\b(no|not|never|without|zero|avoid|forbid|prohibit|don't|do not|cannot|can't)\b", re.I)
        ab_re = re.compile(r"\b(?:Woman|Man)\s+[AB]\b", re.I)
        cjk_re = re.compile(r"[\u4e00-\u9fff]")
        for pid, info in mx.items():
            self.assertTrue((info.get("category") or "").strip(), f"{pid} empty category")
            en_all = " ".join(info.get("beatsEn") or []) + " " + (info.get("framingEn") or "")
            self.assertFalse(ab_re.search(en_all), f"{pid} leaked Woman A/Man A")
            self.assertFalse(neg_re.search(en_all), f"{pid} leaked negative token")
            self.assertFalse(cjk_re.search(en_all), f"{pid} leaked CJK in English")

    def test_unified_compiler_eliminates_frankenstein_bugs_and_supports_3sec_and_container(self):
        mx = core.load_poses()
        vreg = h3.ensure_default_voice_registry()
        s = {"pose": "cowgirl", "pose_zh": "女上位骑乘", "size": "mcu", "cam": "arc_subtle", "text_en": mx["cowgirl"]["beatsEn"][0], "dur": 5.0}
        p = core.single_shot_prompt(
            s, 0, 1, 5.0, "medium close-up", "moves in an arc shot with small amplitude at slow speed",
            lines="轻点，别停。", speaker="女子A", scene="hotel suite", tier="A_two_shot", aspect="16:9", nudity=True,
            voice_timbre=vreg.get("女子A")["timbre"],
        )
        # 1) No doubled camera sentence, no Woman A/Man A, no standing foot shift, no broken `.;`, DE_OIL present, voice timbre present
        self.assertEqual(p.count("0.00s to 1.00s holds steady"), 1)
        self.assertNotIn("Woman A", p)
        self.assertNotIn("Man A", p)
        self.assertNotIn("between the feet", p)
        self.assertNotIn(".;", p)
        self.assertIn("authentic matte velvet skin finish", p)
        self.assertIn("young female voice", p)
        errs, warns = compiler.lint_whale_prompt(p)
        self.assertEqual(errs, [], errs)
        self.assertEqual(warns, [], warns)

        # 2) Base 3-section prompt (Base/I2VA/FL2VA)
        base_p = h3.compile_h3_base_prompt({
            "mode": "first_frame",
            "framing": "medium close-up",
            "camera": "push_tension",
            "action": "Lin Chuan looks down at the dossier and turns the page slowly",
            "speech": {"mode": "on_screen", "speaker_id": "S1", "text": "证据在这里。"},
        }, voice_registry=vreg)
        self.assertIn("integrated_multimodal_description:", base_p)
        self.assertIn("overall_soundscape:", base_p)
        self.assertIn("non_diegetic_music: N/A", base_p)
        self.assertIn("<d>[Chinese]证据在这里。</d>", base_p)

        # 3) Multi-cut container prompt (4-15s)
        cont_p = h3.compile_h3_container_prompt([
            {"duration": 3.0, "keyframe_desc": "wide office doorway at dusk", "framing": "wide shot", "camera": "static_shot", "action": "door opens slowly"},
            {"duration": 3.5, "keyframe_desc": "tight shot of the ledger on the desk", "framing": "close-up", "camera": "push_tension", "action": "hand turns the ledger open", "speech": {"mode": "on_screen", "speaker_id": "S1", "text": "找到了。"}},
        ], voice_registry=vreg)
        self.assertIn("<Picture 1> aligns with the 0.00-second mark", cont_p)
        self.assertIn("<Picture 2> aligns with the 3.00-second mark", cont_p)
        self.assertIn("[Shot 2] At 00:03.000", cont_p)

    def test_script_intake_and_pipeline_check_integration(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "messy_script.txt"
            proj = root / "proj"
            (proj / "00_资产").mkdir(parents=True)
            Image.new("RGB", (64, 64), (80, 90, 100)).save(proj / "00_资产" / "林川.png")
            (proj / "short-drama.json").write_text(json.dumps({
                "title": "测试正剧",
                "project_mode": "standard_drama",
                "production_form": "风格化三维",
                "format": {"aspect_ratio": "16:9"},
            }, ensure_ascii=False), encoding="utf-8")

            raw.write_text(
                "第一集：暗室线索\n"
                "1-1 内 办公室 夜\n"
                "△ 林川翻开桌上文件。\n"
                "**林川**（冷静）：「情况比预想复杂。」\n"
                "林川（OS）：绝对不能泄露。\n\n"
                "第二集 雨夜对峙\n"
                "### 场景一：走廊（外/夜）\n"
                "【旁白】暴雨没有停。\n",
                encoding="utf-8",
            )
            # Dry-run does not write 剧集
            dry = intake.run_intake(raw, proj, apply=False)
            self.assertEqual(len(dry["episodes"]), 2)
            self.assertFalse((proj / "剧集/EP001/剧本.md").exists())

            # Apply archives original and writes normalized markdown
            res = intake.run_intake(raw, proj, apply=True)
            self.assertTrue((proj / res["backup_file"]).is_file())
            ep1_md = (proj / "剧集/EP001/剧本.md").read_text(encoding="utf-8")
            self.assertIn("## EP001-SC001 内 · 办公室 · 夜", ep1_md)
            self.assertIn("林川（冷静）：情况比预想复杂。", ep1_md)
            self.assertIn("[OS] 林川：绝对不能泄露。", ep1_md)

            parsed = creator_views.parse_screenplay(ep1_md)
            self.assertEqual(parsed["scenes"][0]["id"], "EP001-SC001")

            # Verify whale_scene respects 风格化三维 (no 35mm DE_OIL, no nude)
            shots, actual = scene.build_scene(["env_establish", "srs_male"], 10.0, core.load_poses())
            _, _, bj = scene.save_project_artifacts(str(proj), shots, actual, 10.0, scene="办公室", lines="2:男子A:情况比预想复杂。", aspect="16:9", script_path=str(proj / "剧集/EP001/剧本.md"))
            batch = json.loads(Path(bj).read_text(encoding="utf-8"))
            self.assertEqual(batch.get("production_form"), "风格化三维")
            self.assertEqual(batch.get("project_mode"), "standard_drama")
            self.assertIn("Stylized 3D animated cinema", batch["batch_shots"][0]["prompt"])
            self.assertNotIn("35mm cinema film grain", batch["batch_shots"][0]["prompt"])

            # Verify whale_pipeline_check returns duration_metrics and sees clean staging
            rep = pcheck.check_workspace(str(proj))
            self.assertIn("EP001", rep["episode_duration_metrics"])
            self.assertEqual(rep["pose_errors"], [])


    def test_real_world_compact_script_and_board_formats(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "series_compact.txt"
            proj = root / "proj2"
            raw.write_text(
                "人物小传：\n男主陈默：24岁基层队员。\n\n剧本正文：\n"
                "第1集\n"
                "1-1日内 指挥中心\n"
                "△陈默敲击键盘。\n"
                "【字幕：智能助手】\n"
                "陈默（VO）：今天是第一天巡查。\n"
                "家属（语音）：记得吃早饭。\n\n"
                "第2集：\n"
                "2-1 夜外 街角\n"
                "（接上集）\n"
                "（参考资料注释说明，非正文台词）\n"
                "△队员拍下照片。陈默：下不为例。路人：好的。\n",
                encoding="utf-8",
            )
            res = intake.run_intake(raw, proj, apply=True)
            self.assertTrue(res["has_preamble"])
            self.assertTrue((proj / "输入/人物小传-前言.md").is_file())
            self.assertEqual(len(res["episodes"]), 2)
            ep1 = (proj / "剧集/EP001/剧本.md").read_text(encoding="utf-8")
            ep2 = (proj / "剧集/EP002/剧本.md").read_text(encoding="utf-8")
            self.assertIn("## EP001-SC001 内 · 指挥中心 · 日", ep1)
            self.assertIn("[画面文字] 智能助手", ep1)
            self.assertIn("[VO] 陈默：今天是第一天巡查。", ep1)
            self.assertIn("[OS] 家属：记得吃早饭。", ep1)
            self.assertIn("## EP002-SC001 外 · 街角 · 夜", ep2)
            self.assertIn("[连续性] 接上集", ep2)
            self.assertIn("<!-- 参考资料注释说明，非正文台词 -->", ep2)
            self.assertIn("陈默：下不为例。", ep2)
            self.assertIn("路人：好的。", ep2)
            for ep in res["episodes"]:
                inc = ep["estimate"].get("incomplete")
                self.assertIsNone(inc, f"expected clean screenplay index for {ep['episode_id']}")

        board_md = (
            "## 第一幕 · 镜前\n\n"
            "### SHOT-01 ｜ 141f ｜ 5.875s\n"
            "- **景别/机位**：`mcu` / `static_side`\n"
            "- **体位**：`env_establish` 空间建立\n"
            "- **画面**：主角站在房间中央。\n"
            "- **OS**：主角 `<d>[Chinese]这里不对劲。</d>`\n"
            "- **结束状态**：保持面向门口。\n"
        )
        sb = creator_views.parse_storyboard(board_md)
        self.assertEqual(sb["shots"][0]["scene"], "SC001")
        self.assertEqual(sb["shots"][0]["scale"], "中近景")
        self.assertEqual(sb["shots"][0]["move"], "static_side")
        self.assertIn("这里不对劲", sb["shots"][0]["sound"])
        self.assertIn("保持面向门口", sb["shots"][0]["end"])


    def test_misrouted_storyboard_rejected_and_chinese_refs_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            board_as_script = root / "fake_script.md"
            board_as_script.write_text(
                "# EP001 执行稿\n\n### SHOT-01 ｜ 158f ｜ 6.583s\n"
                "- **景别/机位**：`wide` / `static_side`\n"
                "### SHOT-02 ｜ 141f ｜ 5.875s\n"
                "- **景别/机位**：`mcu` / `push_tension`\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                intake.run_intake(board_as_script, root / "proj", apply=False)
            with self.assertRaises(ValueError):
                creator_views.parse_screenplay(board_as_script.read_text(encoding="utf-8"))

            import whale_gatekeeper as gk
            gk_proj = root / "gk_proj"
            (gk_proj / "00_资产").mkdir(parents=True)
            Image.new("RGB", (64, 64), (50, 60, 70)).save(gk_proj / "00_资产" / "林川.png")
            (gk_proj / "剧本.md").write_text(board_as_script.read_text(encoding="utf-8"), encoding="utf-8")
            ok, msg = gk.audit_step_2(str(gk_proj))
            self.assertFalse(ok)
            self.assertIn("storyboard", msg)

            p2 = root / "ep_cn"
            (p2 / "00_资产").mkdir(parents=True)
            Image.new("RGB", (64, 64), (90, 90, 90)).save(p2 / "00_资产" / "林川.png")
            (p2 / "short-drama.json").write_text(json.dumps({"title": "中文参考", "project_mode": "standard_drama", "format": {"aspect_ratio": "16:9"}}))
            sc_md = p2 / "剧本.md"
            sc_md.write_text("# EP001\n\n## EP001-SC001 内 · 办公室 · 日\n\n林川：开始了。\n", encoding="utf-8")
            shots, actual = scene.build_scene(["env_establish", "srs_male"], 10.0, core.load_poses())
            sb_p, _, _ = scene.save_project_artifacts(str(p2), shots, actual, 10.0, scene="办公室", lines="2:男子A:开始了。", aspect="16:9", script_path=str(sc_md))
            pb = creator_views.parse_storyboard(Path(sb_p).read_text(encoding="utf-8"))
            shot2_ref_names = [r["name"] for r in pb["shots"][1]["refs"]]
            self.assertIn("林川.png", shot2_ref_names)


    def test_merged_bold_dtag_intake_and_live_signature(self):
        import dashboard_server as ds
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "merged_dramas.md"
            raw.write_text(
                "# 《双城测试》EP001—EP002 合并剧本\n\n"
                "## 人物与关系\n\n- **沈默**：男主。\n\n---\n\n"
                "# EP001《走廊》\n\n> 两幕结构。\n\n"
                "## 第一幕 · 递卡：平静下的刀锋\n\n"
                "### 阶段一 · 走廊对峙\n\n"
                "**沈默：** `<d>[Chinese]这是今晚的门卡。</d>`\n\n"
                "**林清：** `<d>[Chinese]你确定？</d>`\n\n"
                "林清面部近景：下颌绷紧，眼神明显不悦。\n\n"
                "# EP002《书房》\n\n## 第一幕 · 深夜书房\n\n"
                "**林清 OS：** `<d>[Chinese]我应该立刻离开。</d>`\n",
                encoding="utf-8",
            )
            proj = root / "proj_live"
            subprocess.run([sys.executable, str(ROOT / "scripts/sd_core/project_tool.py"), "init", str(proj), "--title", "实时同步剧", "--aspect-ratio", "16:9", "--episode-count", "2", "--target-seconds", "120"], check=True, capture_output=True)
            res = intake.run_intake(raw, proj, apply=True, auto_dashboard=False)
            self.assertEqual([e["episode_id"] for e in res["episodes"]], ["EP001", "EP002"])
            self.assertTrue(res["has_preamble"])
            for ep in res["episodes"]:
                inc = ep["estimate"].get("incomplete")
                self.assertIsNone(inc, f"{ep['episode_id']} should have clean index: {inc}")

            ep1_ps = creator_views.parse_screenplay((proj / "剧集/EP001/剧本.md").read_text(encoding="utf-8"))
            spks = {b["who"] for sc in ep1_ps["scenes"] for b in sc["blocks"] if b["k"] == "line"}
            self.assertEqual(spks, {"沈默", "林清"})
            self.assertNotIn("<d>", json.dumps(ep1_ps, ensure_ascii=False))

            ep2_ps = creator_views.parse_screenplay((proj / "剧集/EP002/剧本.md").read_text(encoding="utf-8"))
            os_lines = [b for sc in ep2_ps["scenes"] for b in sc["blocks"] if b["k"] == "line" and b["tag"] == "OS"]
            self.assertEqual(len(os_lines), 1)
            self.assertEqual(os_lines[0]["who"], "林清")

            # Live signature changes automatically when a new file appears on disk
            store = ds.ProjectStore(proj, ds.load_project_tool(ROOT))
            try:
                projs, _ = store.discover()
                pid = projs[0]["id"]
                sig1 = store.live_signature(pid)
                (proj / "剧集/EP001/视觉设定.md").write_text("# 设定\n\n## 人物 · 沈默\n- 造型：西装。\n", encoding="utf-8")
                sig2 = store.live_signature(pid)
                self.assertNotEqual(sig1["project_sig"], sig2["project_sig"])
                self.assertTrue(sig2["code_fingerprint"])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
