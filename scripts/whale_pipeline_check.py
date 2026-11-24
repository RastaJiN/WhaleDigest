#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WhaleDigest · 统一工业化门禁与闭环核验中心 (Pipeline Gatekeeper v5)
串联：
  1. sd_core/creator_markdown_check.py::validate_episode（1,740 行确定性 Markdown 闭环校验：场景来源、台词逐字核对、连续性锁、跨镜边界）
  2. whale_pose_guard.py（成人剧 94 条体位真源锁 + 高危体位转换拦截）
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from whale_pose_guard import validate_pose_entry


def load_sd_checker():
    chk_path = BASE_DIR / "sd_core" / "creator_markdown_check.py"
    spec = importlib.util.spec_from_file_location("creator_markdown_check", chk_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_workspace(workspace_dir: str, project_mode: str = "standard_drama"):
    ws = Path(workspace_dir).resolve()
    report = {
        "workspace": str(ws),
        "project_mode": project_mode,
        "episode_markdown_findings": {},
        "pose_errors": [],
        "ok": True,
    }

    # 1. 遍历 剧集/ 下每一集运行 drama-skills validate_episode
    checker = load_sd_checker()
    ep_root = ws / "剧集"
    if ep_root.exists():
        for ep_dir in sorted(ep_root.iterdir()):
            if ep_dir.is_dir():
                try:
                    findings = checker.validate_episode(ep_dir, ws)
                    report["episode_markdown_findings"][ep_dir.name] = findings
                except Exception as e:
                    report["episode_markdown_findings"][ep_dir.name] = [f"ERROR: {e}"]

    # 2. 如果存在 批量任务.json，按 project_mode 核验体位真源与翻车转换
    task_file = ws / "批量任务.json"
    if task_file.exists():
        try:
            batch = json.loads(task_file.read_text(encoding="utf-8"))
            pmode = batch.get("project_mode") or project_mode
            report["project_mode"] = pmode
            for sh in batch.get("shots") or []:
                ok, errs, _ = validate_pose_entry(sh.get("pose") or "", pmode)
                if not ok:
                    sid = sh.get("shot_id") or "?"
                    report["pose_errors"].extend([f"[{sid}] {e}" for e in errs])
        except Exception as e:
            report["pose_errors"].append(f"批量任务.json 解析异常: {e}")

    has_md_err = any(
        any("ERROR" in str(x) or "错" in str(x) for x in vals)
        for vals in report["episode_markdown_findings"].values()
    )
    if report["pose_errors"] or has_md_err:
        report["ok"] = False
    return report


def main():
    parser = argparse.ArgumentParser(description="WhaleDigest 统一门禁与闭环核验")
    parser.add_argument("workspace", help="项目根目录")
    parser.add_argument("--mode", default="standard_drama", help="standard_drama / adult_drama")
    args = parser.parse_args()
    rep = check_workspace(args.workspace, args.mode)
    try:
        from whale_dashboard import auto_start_dashboard
        url = auto_start_dashboard(args.workspace, open_browser=True)
        if url:
            rep["dashboard_url"] = url
    except Exception:
        pass
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    sys.exit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()
