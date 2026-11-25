#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WhaleDigest · 统一工业化门禁与闭环核验中心 (Pipeline Gatekeeper v5)
串联：
  1. sd_core/creator_markdown_check.py::validate_episode（1,740 行确定性 Markdown 闭环校验）
  2. sd_core/screenplay_index.py + duration_estimate.py（不含标点精确台词字数与 VO 占比统计）
  3. whale_pose_guard.py（成人剧 94 条体位真源锁 + 跨维度防穿模拦截 + 正剧零裸露隔离）
  4. whale_compiler.py + whale_h3_prompt.py（H3 六段式逐镜编译校验 + 全集音色防撞车）
"""
import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SD_CORE_DIR = BASE_DIR / "sd_core"
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from whale_pose_guard import validate_pose_entry, load_poses_matrix
from whale_compiler import lint_task_prompt
from whale_h3_prompt import load_project_voice_registry, validate_batch_voice_consistency


def load_sd_checker():
    chk_path = SD_CORE_DIR / "creator_markdown_check.py"
    spec = importlib.util.spec_from_file_location("creator_markdown_check", chk_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _resolve_project_mode(ws: Path, explicit_cli_mode: str = "") -> tuple[str, bool]:
    """返回 (effective_mode, is_locked_explicitly)。显式配置 standard_drama 绝不反转。"""
    for cfg in (ws / "short-drama.json", ws / "short-drama" / "state.json"):
        if cfg.is_file():
            try:
                pm = str(json.loads(cfg.read_text(encoding="utf-8")).get("project_mode") or "").strip().lower()
                if pm in {"standard_drama", "adult_drama", "erotic", "nsfw", "adult"}:
                    return ("standard_drama" if pm == "standard_drama" else "adult_drama"), True
            except Exception:
                pass
    if explicit_cli_mode:
        low = explicit_cli_mode.strip().lower()
        return ("standard_drama" if low == "standard_drama" else "adult_drama"), False
    return "standard_drama", False


def _estimate_episode_metrics(ep_dir: Path, ws: Path) -> dict:
    sp = ep_dir / "剧本.md"
    if not sp.is_file():
        return {}
    text = sp.read_text(encoding="utf-8", errors="ignore")
    speakers = sorted({
        m.group(1).strip()
        for m in re.finditer(r"^([^\s：:（）()\[\]#\n]{1,24})(?:（[^）\n]+）)?：", text, re.M)
        if not m.group(1).startswith("[")
    })
    with tempfile.TemporaryDirectory() as td:
        idx_path = Path(td) / "idx.jsonl"
        cmd_idx = [sys.executable, str(SD_CORE_DIR / "screenplay_index.py"), str(sp), "--output", str(idx_path)]
        for s in speakers:
            cmd_idx.extend(["--speaker", s])
        r1 = subprocess.run(cmd_idx, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if r1.returncode != 0 or not idx_path.is_file():
            return {}
        cmd_est = [sys.executable, str(SD_CORE_DIR / "duration_estimate.py"), str(sp), "--index", str(idx_path)]
        if (ws / "short-drama.json").is_file():
            cmd_est.extend(["--project", str(ws / "short-drama.json")])
        r2 = subprocess.run(cmd_est, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        try:
            return json.loads(r2.stdout)
        except Exception:
            return {}


def check_workspace(workspace_dir: str, project_mode: str = ""):
    ws = Path(workspace_dir).resolve()
    eff_mode, is_locked = _resolve_project_mode(ws, project_mode)
    report = {
        "workspace": str(ws),
        "project_mode": eff_mode,
        "episode_markdown_findings": {},
        "episode_duration_metrics": {},
        "pose_errors": [],
        "prompt_errors": [],
        "voice_errors": [],
        "ok": True,
    }

    # 1. 遍历 剧集/ 下每一集运行 drama-skills validate_episode + 精确台词估时
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
                est = _estimate_episode_metrics(ep_dir, ws)
                if est:
                    report["episode_duration_metrics"][ep_dir.name] = est

    # 2. 扫描 root 批量任务.json 与 03_生成任务/*/批量任务.json 与 剧集/*/批量任务.json
    batch_files = []
    seen = set()
    for bf in [ws / "批量任务.json", *sorted((ws / "03_生成任务").glob("*/批量任务.json")), *sorted((ws / "剧集").glob("*/批量任务.json"))]:
        if bf.is_file():
            rbf = str(bf.resolve())
            if rbf not in seen:
                seen.add(rbf)
                batch_files.append(bf)

    mx = load_poses_matrix()
    adult_ids = {k for k, v in mx.items() if isinstance(v, dict) and v.get("category") not in (None, "", "通用", "staging")}
    vreg = load_project_voice_registry(str(ws))

    for task_file in batch_files:
        try:
            batch = json.loads(task_file.read_text(encoding="utf-8"))
            pmode = str(batch.get("project_mode") or "").strip().lower() or eff_mode
            if is_locked and eff_mode == "standard_drama":
                pmode = "standard_drama"
            elif not is_locked and pmode == "standard_drama":
                has_nude_file = (ws / "00_资产").is_dir() and any(
                    "_nude" in f.name.lower() or "nude." in f.name.lower()
                    for f in (ws / "00_资产").iterdir() if f.is_file()
                )
                has_pose_plan = bool(list((ws / "剧集").glob("*/体位规划.json")))
                if has_nude_file or has_pose_plan:
                    pmode = "adult_drama"
            report["project_mode"] = pmode

            shots = batch.get("batch_shots") or batch.get("shots") or []
            for sh in shots:
                raw_pose = str(sh.get("pose") or "").strip()
                sid = sh.get("shot_id") or sh.get("id") or "?"
                if pmode == "standard_drama":
                    bad_refs = [r for r in (sh.get("ref_images") or []) if "_nude" in str(r).lower() or "nude." in str(r).lower()]
                    if bad_refs:
                        report["pose_errors"].append(f"[{sid}] 正剧模式 (standard_drama) 禁止绑定素身参考图 {bad_refs}")
                    if float(sh.get("lora_mystic_strength") or 0.0) > 0:
                        report["pose_errors"].append(f"[{sid}] 正剧模式 (standard_drama) 禁止非零 MysticXXX 成人权重")
                for sub_p in [p.strip() for p in raw_pose.split("->") if p.strip()]:
                    ok, errs, _ = validate_pose_entry(
                        sub_p, pmode,
                        tier=str(sh.get("tier") or ""),
                        camera_motion=str(sh.get("camera_motion") or sh.get("camera") or ""),
                    )
                    if not ok:
                        report["pose_errors"].extend([f"[{sid}] {e}" for e in errs])
                if isinstance(sh.get("prompt"), str) and sh.get("prompt").strip():
                    p_errs, _ = lint_task_prompt(sh, batch)
                    if p_errs:
                        report["prompt_errors"].extend([f"[{sid}] {e}" for e in p_errs])

            v_errs, _ = validate_batch_voice_consistency(batch, vreg)
            report["voice_errors"].extend(v_errs)
        except Exception as e:
            report["pose_errors"].append(f"{task_file.name} 解析异常: {e}")

    has_md_err = any(bool(vals) for vals in report["episode_markdown_findings"].values())
    if report["pose_errors"] or report["prompt_errors"] or report["voice_errors"] or has_md_err:
        report["ok"] = False
    return report


def main():
    parser = argparse.ArgumentParser(description="WhaleDigest 统一门禁与闭环核验")
    parser.add_argument("workspace", help="项目根目录")
    parser.add_argument("--mode", default="", help="可选：standard_drama / adult_drama")
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
