#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WhaleDigest · 吞鲸宝典工作台统一启动入口 (Unified Studio Launcher)
彻底收口工作台入口：不再使用旧版简陋单页 HTML，统一拉起 1:1 复刻高级多视图工作台 (`sd_core/dashboard_server.py`)。

特性：
  1. 兼容位置参数 `whale_dashboard.py <项目目录>` 与 `--workspace <项目目录>`；
  2. 自动建档兜底：若目标漫剧目录缺少 `short-drama.json` 或 `short-drama/state.json`，
     自动读取 `批量任务.json`（标题/画幅/集数/project_mode）无感调用 `sd_core/project_tool.py init` 建档，
     彻底解决“新漫剧项目启动后提示未发现可打开项目”的问题；
  3. 透传 `--port` / `--detach` / `--open` / `--status` / `--stop` 至 `sd_core/dashboard_server.py`。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SD_CORE_DIR = BASE_DIR / "sd_core"
DASHBOARD_SERVER = SD_CORE_DIR / "dashboard_server.py"
PROJECT_TOOL = SD_CORE_DIR / "project_tool.py"


def _resolve_project_root(workspace: Path) -> Path:
    """若传入剧集子目录（如 .../剧集/EP001），向上锚定到项目根目录，避免嵌套建档与多开工作台。"""
    ws = workspace.resolve()
    if ws.parent.name == "剧集" and ws.parent.parent.exists():
        parent_root = ws.parent.parent
        if (parent_root / "short-drama.json").exists() or (parent_root / "剧集").is_dir():
            return parent_root
    return ws


def ensure_project_registered(workspace: Path) -> None:
    """确保工作区具备 short-drama.json 与 short-drama/state.json，避免打开报空项目。"""
    ws = _resolve_project_root(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    sd_json = ws / "short-drama.json"
    st_json = ws / "short-drama" / "state.json"
    if sd_json.exists() and st_json.exists():
        return

    title = ws.name or "未命名漫剧"
    aspect = "9:16"
    ep_count = 1
    pmode = "standard_drama"

    task_file = ws / "批量任务.json"
    if task_file.exists():
        try:
            batch = json.loads(task_file.read_text(encoding="utf-8"))
            aspect = batch.get("aspect") or aspect
            pmode = batch.get("project_mode") or pmode
            if batch.get("title"):
                title = str(batch["title"])
        except Exception:
            pass

    ep_dir = ws / "剧集"
    if ep_dir.exists():
        eps = [d for d in ep_dir.iterdir() if d.is_dir()]
        if eps:
            ep_count = len(eps)

    if aspect not in {"16:9", "9:16", "1:1"}:
        aspect = "9:16"

    if not sd_json.exists():
        subprocess.run(
            [
                sys.executable,
                str(PROJECT_TOOL),
                "init",
                str(ws),
                "--title",
                title,
                "--language",
                "zh-CN",
                "--aspect-ratio",
                aspect,
                "--episode-count",
                str(max(1, ep_count)),
                "--target-seconds",
                "120",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )

    if sd_json.exists() and pmode != "standard_drama":
        try:
            cfg = json.loads(sd_json.read_text(encoding="utf-8"))
            if not cfg.get("project_mode"):
                cfg["project_mode"] = pmode
                sd_json.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass




def _is_temp_test_dir(ws: Path) -> bool:
    import tempfile
    resolved = ws.resolve()
    skill_root = Path(__file__).resolve().parent.parent
    try:
        resolved.relative_to(skill_root)
        return True
    except ValueError:
        pass
    if resolved.name.startswith("-"):
        return True
    parts = [p.lower() for p in resolved.parts]
    tmp_root = Path(tempfile.gettempdir()).resolve()
    try:
        ws.resolve().relative_to(tmp_root)
        return True
    except ValueError:
        pass
    return any(x in parts for x in ("temp", "tmp", "__pycache__"))


def auto_start_dashboard(project_dir, open_browser: bool = True):
    """
    当检测到项目已存在 `剧本.md` 或 `剧集/*/剧本.md` 时自动拉起本地工作台。
    - 跳过条件：环境变量 WHALE_NO_AUTO_DASHBOARD=1 或位于系统临时目录的单元测试项目
    - 返回启动后的 URL（如已运行则返回复用 URL；未触发返回 None）
    """
    import os
    if os.environ.get("WHALE_NO_AUTO_DASHBOARD") == "1":
        return None
    ws = _resolve_project_root(Path(project_dir).expanduser())
    if not ws.exists() or _is_temp_test_dir(ws):
        return None

    has_script = (ws / "剧本.md").is_file() or any((ws / "剧集").glob("*/剧本.md"))
    if not has_script:
        return None

    ensure_project_registered(ws)

    # 先查询当前工作台是否已在运行；已在线则静默复用（依赖 2.5s 热同步刷新），不再反复弹窗
    st = subprocess.run(
        [sys.executable, str(DASHBOARD_SERVER), "--workspace", str(ws), "--status"],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )
    if st.returncode == 0 and '"running": true' in st.stdout:
        try:
            info = json.loads(st.stdout)
            url = info.get("url")
            if url and info.get("brand") == "tunjing-baodian" and not info.get("stale"):
                print(f"[工作台] 检测到剧本已就绪，复用在线工作台（已开启自动热同步，不再重复弹窗）: {url}")
                return url
            if info.get("stale"):
                print("[工作台] 检测到后台运行着旧版本工作台，自动重启为最新版...")
        except Exception:
            pass

    cmd = [sys.executable, str(DASHBOARD_SERVER), "--workspace", str(ws), "--port", "0", "--detach", "--restart"]
    if open_browser:
        cmd.append("--open")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=15)
    for line in r.stdout.splitlines():
        if line.startswith("Dashboard:"):
            url = line.split("Dashboard:", 1)[1].strip()
            print(f"[工作台] 检测到剧本已就绪，已自动启动本地工作台: {url}")
            return url
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="WhaleDigest 吞鲸宝典工作台统一启动入口")
    parser.add_argument("project_dir_pos", nargs="?", help="剧集/项目根目录")
    parser.add_argument("--workspace", dest="workspace_opt", help="剧集/项目根目录")
    parser.add_argument("--port", type=int, default=0, help="监听端口，0 表示自动分配空闲端口（默认 0）")
    parser.add_argument("--open", action="store_true", help="自动打开浏览器")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--detach", action="store_true", help="后台运行")
    parser.add_argument("--status", action="store_true", help="查看当前工作台状态")
    parser.add_argument("--stop", action="store_true", help="停止后台工作台")
    parser.add_argument("--restart", action="store_true", help="强制重启后台工作台")
    args = parser.parse_args()

    target = args.workspace_opt or args.project_dir_pos
    if not target:
        parser.error("必须提供项目目录：<project_dir> 或 --workspace <project_dir>")

    ws = _resolve_project_root(Path(target).expanduser())
    if not args.status and not args.stop:
        ensure_project_registered(ws)

    cmd = [sys.executable, str(DASHBOARD_SERVER), "--workspace", str(ws)]
    if args.status:
        cmd.append("--status")
    elif args.stop:
        cmd.append("--stop")
    else:
        cmd.extend(["--port", str(args.port)])
        if args.detach:
            cmd.append("--detach")
        if args.restart:
            cmd.append("--restart")
        if args.open and not args.no_browser:
            cmd.append("--open")

    res = subprocess.run(cmd)
    return res.returncode


if __name__ == "__main__":
    raise SystemExit(main())
