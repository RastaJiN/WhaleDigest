# -*- coding: utf-8 -*-
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
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



from whale_dashboard import auto_start_dashboard, ensure_project_registered


class TestAutoDashboard(unittest.TestCase):
    def test_auto_start_dashboard_skips_temp_or_env(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "剧本.md").write_text("# EP001\n", encoding="utf-8")
            # 临时目录或设置 WHALE_NO_AUTO_DASHBOARD=1 时安全跳过弹窗
            self.assertIsNone(auto_start_dashboard(str(ws), open_browser=False))

    def test_ensure_project_registered_creates_short_drama_json(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "demo_proj"
            ws.mkdir()
            (ws / "批量任务.json").write_text(
                json.dumps({"aspect": "16:9", "project_mode": "standard_drama"}, ensure_ascii=False),
                encoding="utf-8",
            )
            ensure_project_registered(ws)
            self.assertTrue((ws / "short-drama.json").exists())




    def test_creator_views_whale_compat_and_brand_guard(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts" / "sd_core"))
        import creator_views as cv
        # 1) 吞鲸 ### SHOT-01 格式 & 表格分镜均可 0 报错解析，且 start_frame 不报 KeyError
        whale_sb = """# 吞鲸分镜
### SHOT-01 [Track: Ref2V]
- 时长: 5.0s (0.0-5.0s) | H3帧数: 90帧
- 景别: mcu — 中近景
- 机位: eye_level
- 动作: 女主转身回望
- 台词: 别过来。
- 参考图: `00_资产/female.png`
"""
        ep = cv.read_episode("EP001", {
            "剧本.md": "# EP001 测试\n### 场景一：卧室（夜）\n女主：别过来。\n",
            "分镜.md": whale_sb,
            "视频提示词.md": "### SHOT-01 (5.0s)\n```text\nwoman turns around\n```\n",
        }, None)
        self.assertEqual(ep["problems"], [])
        self.assertEqual(len(ep["board"]["shots"]), 1)
        self.assertEqual(ep["board"]["shots"][0]["scale"], "中近景")
        self.assertIsNone(cv.start_frame(ep["board"]["shots"][0]))

        # 1b) 无 ## 井号 + 全角・ + 机位/终点与承接/发声 格式一样 0 警告解析并追踪场次
        ep_fw = cv.read_episode("EP001", {
            "剧本.md": "# EP001 试映集\n\nEP001-SC001・内・办公室・日\n林川坐在桌前。\n",
            "分镜.md": """EP001-SC001・内・办公室・日\nSHOT-EP001-001・文件摞得比键盘高\n66 帧 / 2.75 秒\n机位：全景 / 通道侧前斜。运镜：小横移。\n起点：打字。\n动作：看屏。\n终点与承接：抬手。\n发声：无对白。\n""",
        }, None)
        self.assertEqual(ep_fw["problems"], [])
        self.assertEqual(ep_fw["board"]["shots"][0]["scene"], "EP001-SC001")
        self.assertEqual(ep_fw["board"]["shots"][0]["scale"], "全景")
        self.assertAlmostEqual(ep_fw["board"]["shots"][0]["sec"], 2.75)

        # 2) app.js 中 mountWhaleInspectorExt 在 host.innerHTML 之后挂载且无内联 style
        app_js = (ROOT / "assets" / "dashboard" / "app.js").read_text(encoding="utf-8")
        idx_fn = app_js.index("async function mountWhaleInspectorExt")
        idx_end = app_js.index("window.__WHALE_EP_POSES", idx_fn)
        ext_block = app_js[idx_fn:idx_end]
        self.assertNotIn("style=", ext_block)
        self.assertNotIn("cssText", ext_block)
        idx_render = app_js.index("function renderInspector(")
        idx_r_end = app_js.index("function presence(", idx_render)
        ins_block = app_js[idx_render:idx_r_end]
        self.assertLess(ins_block.index("host.innerHTML ="), ins_block.index("mountWhaleInspectorExt("))


    def test_swap_game_fixes_regression(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        sys.path.insert(0, str(ROOT / "scripts" / "sd_core"))
        from whale_pose_guard import validate_pose_entry
        import whale_pipeline_check as wpc
        import creator_views as cv

        # 1) 单人镜禁配 ots_depth 与双人体位
        ok_ots, errs_ots, _ = validate_pose_entry("srs_male", "adult_drama", tier="B_solo_male", camera_motion="ots_depth")
        self.assertFalse(ok_ots)
        self.assertIn("过肩", errs_ots[0])
        ok_2b, errs_2b, _ = validate_pose_entry("mirror_ear_whisper", "adult_drama", tier="B_solo_male", camera_motion="static_front")
        self.assertFalse(ok_2b)
        self.assertIn("双人同框", errs_2b[0])

        # 2) app.js 不再写死 '竖屏 16:9'
        app_js = (ROOT / "assets" / "dashboard" / "app.js").read_text(encoding="utf-8")
        self.assertIn("横屏", app_js)
        self.assertNotIn("`竖屏 ${series.format.aspect_ratio}`", app_js)

        # 3) whale_pipeline_check 不再吞掉无 "ERROR"/"错" 字样的 validate_episode 失败，且支持 batch_shots
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            ep1 = ws / "剧集" / "EP001"
            ep1.mkdir(parents=True)
            (ep1 / "剧本.md").write_text("# EP001\n\n你好。\n", encoding="utf-8")
            (ws / "批量任务.json").write_text(json.dumps({
                "aspect": "16:9",
                "batch_shots": [{"shot_id": "SHOT-01", "pose": "standing_fuck", "tier": "B_two", "camera_motion": "static_side"}],
            }, ensure_ascii=False), encoding="utf-8")
            (ws / "00_资产").mkdir()
            (ws / "00_资产" / "female_nude.png").write_bytes(b"fake")
            rep = wpc.check_workspace(str(ws), "standard_drama")
            self.assertFalse(rep["ok"])
            self.assertEqual(rep["project_mode"], "adult_drama")
            self.assertTrue(rep["pose_errors"])

        # 4) creator_views 支持执行稿格式 + 标题括号参数 (4.458s | 107帧 | wide | static_side)
        ep = cv.read_episode("EP001", {
            "剧本.md": "# EP001 试映\n\n### SHOT-00\n女主：别碰我。\n",
            "分镜.md": "## 第一幕 · 走廊递卡\n\n### [SHOT-00] (4.458s | 107帧 | wide | static_side) — 双人建立镜\n- 动作：递出房卡\n",
        }, None)
        self.assertEqual(ep["problems"], [])
        self.assertEqual(ep["board"]["shots"][0]["scale"], "远景")
        self.assertAlmostEqual(ep["board"]["shots"][0]["sec"], 4.458)


    def test_standard_drama_never_leaks_nude_masters(self):
        import whale_scene as ws_mod
        import whale_gatekeeper as gk_mod
        import whale_runner as wr_mod
        from PIL import Image

        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / "short-drama.json").write_text(json.dumps({"project_mode": "standard_drama", "aspect": "16:9"}), encoding="utf-8")
            assets = proj / "00_资产"
            assets.mkdir()
            for fn in ("林川_正装.png", "场景_办公室_scene.png"):
                Image.new("RGB", (64, 64), (120, 140, 160)).save(assets / fn)
            (proj / "剧本.md").write_text("# EP001\n\n## 第一幕\n林川坐在办公桌前。\n\n<d>[Chinese]情况怎样？</d>\n", encoding="utf-8")

            shots, actual = ws_mod.build_scene(["env_establish", "srs_male"], 10.0, ws_mod.load_poses())
            _, _, bj_path = ws_mod.save_project_artifacts(
                str(proj), shots, actual, 10.0, scene="办公室", lines="情况怎样？", aspect="16:9",
                script_path=str(proj / "剧本.md"),
            )
            batch = json.loads(Path(bj_path).read_text(encoding="utf-8"))
            self.assertEqual(batch.get("project_mode"), "standard_drama")
            for sh in batch["batch_shots"]:
                self.assertEqual(sh["wardrobe_state"], "dressed")
                self.assertEqual(sh["lora_mystic_strength"], 0.0)
                for r in sh["ref_images"]:
                    self.assertNotIn("nude", r.lower())
            # 中文文件名应成功被选入参考图，不被 isascii 过滤掉
            all_refs = [r for sh in batch["batch_shots"] for r in sh["ref_images"]]
            self.assertTrue(any("林川_正装.png" in r or "场景_办公室_scene.png" in r for r in all_refs))

            # ensure_series_bible 正剧不写 female_nude/male_nude
            bible, _ = wr_mod.load_or_init_series_bible(str(proj))
            self.assertNotIn("nude_master", bible["characters"]["female_lead"])
            self.assertNotIn("nude_master", bible["characters"]["male_lead"])
            self.assertEqual(bible["locked_models"]["lora_mystic"]["action_strength"], 0.0)

            # Gate 4 若被人为塞入 female_nude.png，正剧锁必须拦截 FAIL
            batch["batch_shots"][0]["ref_images"] = ["female_nude.png", "场景_办公室_scene.png", "场景_办公室_scene.png"]
            Path(bj_path).write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
            (assets / "female_nude.png").write_bytes(b"fake")
            ok_g4, msg_g4 = gk_mod.audit_step_4(str(proj))
            self.assertFalse(ok_g4)
            self.assertIn("standard_drama", msg_g4)

        ui_txt = (ROOT / "references" / "whale_ui.json").read_text(encoding="utf-8")
        self.assertNotIn("-NUDE.png", ui_txt)


    def test_csp_clean_and_ep_post_isolation(self):
        app_txt = (ROOT / "assets" / "dashboard" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn('style="', app_txt)
        self.assertNotIn("endsWith(a.name)", app_txt)


if __name__ == "__main__":
    unittest.main()
