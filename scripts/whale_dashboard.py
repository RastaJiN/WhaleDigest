#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WhaleDigest · 本地可视化创作与审片工作台 (Studio Dashboard v3)
纯 Python 标准库实现，零外部依赖，仅绑定 127.0.0.1 回环地址。

交互架构（对标 drama-skills 专业多视图工作台 + 宝典硬核防错）：
  - 顶部导航栏：项目标题 / 搜索框 / 门禁状态灯 (ERROR/WARNING) / 16位点火令牌 / 刷新
  - 5 大主视图 Tab：
    1. 总览与门禁 (Overview & Gates)：底座硬锁、Gate 1–6 状态、ERROR/WARNING 阻断清单
    2. 分镜与选人/体位工作台 (Storyboard & Inspector)：左侧分镜列表 + 右侧实时详情检视器
       - 可视化人物/场景参考图勾选器（按点击顺序绑定 <Picture 1..9>）
       - 肉戏体位可视化选择器（94 条动作真源 + 实时显示 framingZh 机位景别锁）
       - 一键保存写回 批量任务.json 并自动重跑校验
    3. 00_资产库 (Assets)：缩略图墙 + ASCII 合规检查
    4. 音色账本 (Voice Bible)：全集角色音色/语气表
    5. 成片与五联板 (Media & Boards)：成片视频与五联质检板集中审片
"""
import argparse
import html
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from whale_task_source import (
    load_task_source,
    resolve_workflow_path,
    validate_batch_metadata,
    validate_project_assets,
)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv"}
ASCII_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def load_poses_catalog():
    poses_path = ROOT_DIR / "references" / "whale_poses_matrix.json"
    if not poses_path.exists():
        return []
    try:
        data = json.loads(poses_path.read_text(encoding="utf-8"))
        items = []
        for pid, info in data.items():
            items.append({
                "id": pid,
                "nameZh": info.get("nameZh") or pid,
                "nameEn": info.get("nameEn") or pid,
                "framingZh": info.get("framingZh") or "",
                "framingEn": info.get("framingEn") or "",
            })
        return items
    except Exception:
        return []


def collect_project_snapshot(project_dir):
    p = Path(project_dir).resolve()
    snap = {
        "project_dir": str(p),
        "project_name": p.name,
        "exists": p.exists(),
        "aspect": None,
        "project_mode": "standard_drama",
        "workflow_path": None,
        "workflow_ok": False,
        "voice_bible": {},
        "assets": [],
        "shots": [],
        "gates": {},
        "confirm_token": None,
        "errors": [],
        "warnings": [],
        "poses": load_poses_catalog(),
        "episodes": {},
        "media_outputs": [],
    }
    if not p.exists():
        snap["errors"].append(f"项目目录不存在: {p}")
        # 7. 扫描 剧集/ 下的五文档 (剧本.md / 视觉设定.md / 分镜.md / 图片提示词.md / 视频提示词.md)
    ep_root = p / "剧集"
    if ep_root.exists():
        for ep_dir in sorted(ep_root.iterdir()):
            if ep_dir.is_dir():
                docs = {}
                for dname in ["剧本.md", "视觉设定.md", "分镜.md", "图片提示词.md", "视频提示词.md", "剪辑单.md"]:
                    df = ep_dir / dname
                    if df.is_file():
                        docs[dname] = df.read_text(encoding="utf-8", errors="replace")
                if docs:
                    snap["episodes"][ep_dir.name] = docs

    # 8. 扫描 制作成果/ 媒体输出
    res_dir = p / "制作成果"
    if res_dir.exists():
        for mf in sorted(res_dir.rglob("*")):
            if mf.is_file() and mf.suffix.lower() in (IMAGE_EXTS | VIDEO_EXTS):
                rel = str(mf.resolve().relative_to(p)).replace("\\", "/")
                snap["media_outputs"].append({
                    "name": mf.name,
                    "rel": rel,
                    "kind": "video" if mf.suffix.lower() in VIDEO_EXTS else "image",
                })

    return snap

    assets_dir = p / "00_资产"
    if assets_dir.exists():
        for f in sorted(assets_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                is_ascii = bool(ASCII_NAME_RE.match(f.name))
                snap["assets"].append({
                    "name": f.name,
                    "rel": f"00_资产/{f.name}",
                    "size_kb": round(f.stat().st_size / 1024, 1),
                    "is_ascii": is_ascii,
                })
                if not is_ascii:
                    snap["errors"].append(f"资产文件名含非 ASCII 字符: 00_资产/{f.name}")
    else:
        snap["warnings"].append("缺少 00_资产/ 目录")

    vb_path = p / "voice_bible.json"
    if vb_path.exists():
        try:
            snap["voice_bible"] = json.loads(vb_path.read_text(encoding="utf-8"))
        except Exception as e:
            snap["errors"].append(f"voice_bible.json 解析失败: {e}")

    task_path = p / "批量任务.json"
    if not task_path.exists():
        snap["warnings"].append("未找到 批量任务.json（尚未编译分镜批次）")
        return snap

    try:
        batch = load_task_source(str(p))
    except Exception as e:
        snap["errors"].append(f"批量任务.json 读取失败: {e}")
        return snap

    snap["aspect"] = batch.get("aspect")
    snap["project_mode"] = batch.get("project_mode") or "standard_drama"
    wf = resolve_workflow_path(batch, str(p))
    snap["workflow_path"] = wf
    snap["workflow_ok"] = bool(wf and Path(wf).exists())

    snap["errors"].extend(validate_batch_metadata(batch, str(p)))
    snap["errors"].extend(validate_project_assets(batch, str(p)))

    status_path = p / ".whale_status.json"
    if status_path.exists():
        try:
            st = json.loads(status_path.read_text(encoding="utf-8"))
            snap["gates"] = st.get("gates") or {}
            snap["confirm_token"] = st.get("confirm_token")
        except Exception as e:
            snap["warnings"].append(f".whale_status.json 解析失败: {e}")

    boards_dir = p / "03_五联质检板"
    out_dir = p / "02_成片输出"
    board_files = {f.stem: f.name for f in boards_dir.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS} if boards_dir.exists() else {}
    video_files = [f.name for f in out_dir.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXTS] if out_dir.exists() else []

    for idx, shot in enumerate(batch.get("shots") or []):
        sid = shot.get("shot_id") or f"shot_{idx+1:02d}"
        refs = shot.get("ref_images") or []
        ref_items = []
        for r_idx, r in enumerate(refs, 1):
            r_path = Path(r) if Path(r).is_absolute() else (p / r)
            rel_url = None
            if r_path.exists():
                try:
                    rel_url = str(r_path.resolve().relative_to(p)).replace("\\", "/")
                except Exception:
                    rel_url = None
            ref_items.append({
                "slot": r_idx,
                "raw": str(r),
                "name": Path(str(r)).name,
                "exists": r_path.exists(),
                "rel": rel_url,
            })

        matched_board = next((f"03_五联质检板/{bname}" for bstem, bname in board_files.items() if sid in bstem), None)
        matched_video = next((f"02_成片输出/{vname}" for vname in video_files if sid in vname), None)

        snap["shots"].append({
            "index": idx,
            "shot_id": sid,
            "frames": shot.get("frames"),
            "duration_sec": round((shot.get("frames") or 0) / 24.0, 2) if shot.get("frames") else None,
            "pose": shot.get("pose") or "",
            "shot_size": shot.get("shot_size") or "",
            "camera_move": shot.get("camera_move") or "",
            "shot_type": shot.get("shot_type") or "",
            "lora": shot.get("lora") if shot.get("lora") is not None else 0.0,
            "dialogue": shot.get("dialogue") or "",
            "speaker": shot.get("speaker") or "",
            "speech_mode": shot.get("speech_mode") or "",
            "prompt": shot.get("prompt") or "",
            "ref_items": ref_items,
            "board": matched_board,
            "video": matched_video,
        })

    return snap


def render_dashboard_html(snap):
    snap_json = json.dumps(snap, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>WhaleDigest Studio · {html.escape(snap["project_name"])}</title>
<style>
  :root {{
    --bg: #0b0e14; --panel: #131722; --panel-2: #191f2e; --border: #262f42;
    --text: #e6ebf5; --muted: #8b97b0; --accent: #3b82f6; --ok: #22c55e; --warn: #f59e0b; --err: #ef4444;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif; background:var(--bg); color:var(--text); height:100vh; display:flex; flex-direction:column; overflow:hidden; }}
  .topbar {{ display:flex; align-items:center; justify-content:space-between; padding:10px 18px; background:var(--panel); border-bottom:1px solid var(--border); gap:14px; flex-shrink:0; }}
  .brand {{ display:flex; align-items:center; gap:10px; font-weight:700; font-size:15px; }}
  .brand small {{ color:var(--muted); font-weight:400; font-size:12px; }}
  .nav-tabs {{ display:flex; gap:6px; }}
  .tab-btn {{ background:transparent; border:1px solid transparent; color:var(--muted); padding:6px 12px; border-radius:6px; cursor:pointer; font-size:13px; font-weight:500; }}
  .tab-btn:hover {{ color:var(--text); background:var(--panel-2); }}
  .tab-btn.active {{ color:#fff; background:var(--accent); }}
  .top-right {{ display:flex; align-items:center; gap:10px; }}
  .search-input {{ background:var(--bg); border:1px solid var(--border); color:var(--text); padding:6px 10px; border-radius:6px; font-size:13px; width:200px; }}
  .pill {{ font-size:12px; padding:3px 8px; border-radius:999px; font-weight:600; }}
  .pill.ok {{ background:#143322; color:#4ade80; border:1px solid #22c55e44; }}
  .pill.err {{ background:#3b161b; color:#f87171; border:1px solid #ef444444; }}
  .pill.warn {{ background:#3b290b; color:#fbbf24; border:1px solid #f59e0b44; }}
  .btn {{ background:var(--panel-2); color:var(--text); border:1px solid var(--border); padding:6px 12px; border-radius:6px; cursor:pointer; font-size:13px; }}
  .btn:hover {{ border-color:var(--accent); }}
  .btn.primary {{ background:var(--accent); border-color:var(--accent); color:#fff; font-weight:600; }}
  .main {{ flex:1; overflow:hidden; display:flex; flex-direction:column; }}
  .view {{ display:none; flex:1; overflow:auto; padding:18px; }}
  .view.active {{ display:block; }}
  #view-board.active {{ display:grid; grid-template-columns: 380px 1fr; padding:0; overflow:hidden; }}
  .board-list {{ border-right:1px solid var(--border); overflow-y:auto; background:var(--panel); padding:10px; }}
  .board-item {{ padding:10px 12px; border-radius:8px; border:1px solid transparent; cursor:pointer; margin-bottom:6px; background:var(--panel-2); }}
  .board-item:hover {{ border-color:#3b82f666; }}
  .board-item.selected {{ border-color:var(--accent); background:#1d283d; }}
  .board-item-top {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; }}
  .board-item-id {{ font-weight:700; color:#60a5fa; font-size:14px; }}
  .board-item-meta {{ font-size:12px; color:var(--muted); }}
  .board-item-line {{ font-size:12px; color:#cbd5e1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:4px; }}
  .inspector {{ overflow-y:auto; padding:18px 22px; }}
  .card {{ background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:16px; margin-bottom:16px; }}
  .grid-2 {{ display:grid; grid-template-columns: 1fr 1fr; gap:16px; }}
  .kv {{ display:grid; grid-template-columns: 140px 1fr; gap:8px; font-size:13px; }}
  .slots-row {{ display:flex; gap:10px; flex-wrap:wrap; margin:10px 0; }}
  .slot-card {{ width:124px; background:var(--bg); border:1px solid var(--border); border-radius:6px; padding:6px; text-align:center; font-size:12px; }}
  .slot-card.err {{ border-color:var(--err); }}
  .slot-card img {{ width:100%; height:74px; object-fit:cover; border-radius:4px; }}
  .picker-grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(155px, 1fr)); gap:8px; max-height:230px; overflow-y:auto; margin-top:8px; }}
  .pick-item {{ display:flex; align-items:center; gap:8px; background:var(--bg); border:1px solid var(--border); padding:6px; border-radius:6px; cursor:pointer; font-size:12px; }}
  .pick-item:hover {{ border-color:var(--accent); }}
  .pick-item img {{ width:34px; height:34px; object-fit:cover; border-radius:4px; flex-shrink:0; }}
  .pick-item span {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  select {{ width:100%; background:var(--bg); color:var(--text); border:1px solid var(--border); padding:8px; border-radius:6px; font-size:13px; }}
  .pose-lock-box {{ margin-top:8px; padding:8px 10px; background:#111c2d; border:1px solid #2563eb55; border-radius:6px; font-size:12px; color:#93c5fd; }}
  pre {{ background:var(--bg); border:1px solid var(--border); padding:12px; border-radius:8px; white-space:pre-wrap; font-size:12px; color:#cbd5e1; }}
  .asset-grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap:12px; }}
  .asset-card {{ background:var(--panel); border:1px solid var(--border); border-radius:8px; overflow:hidden; }}
  .asset-card img {{ width:100%; height:115px; object-fit:cover; display:block; }}
  .asset-meta {{ padding:8px; font-size:12px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--border); }}
  .media-grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap:14px; }}
  .media-grid img, .media-grid video {{ width:100%; border-radius:8px; border:1px solid var(--border); }}
</style>
</head>
<body>
  <div class="topbar">
    <div class="brand">
      <span>🐳 WhaleDigest Studio</span>
      <small id="proj-name"></small>
    </div>
    <div class="nav-tabs">
      <button class="tab-btn active" onclick="switchTab('overview', this)">总览与门禁</button>
      <button class="tab-btn" onclick="switchTab('board', this)">分镜与选人/体位工作台</button>
      <button class="tab-btn" onclick="switchTab('assets', this)">00_资产库</button>
      <button class="tab-btn" onclick="switchTab('docs', this)">剧集文档 (在线编辑)</button>
      <button class="tab-btn" onclick="switchTab('voice', this)">音色账本</button>
      <button class="tab-btn" onclick="switchTab('media', this)">成片与五联板</button>
    </div>
    <div class="top-right">
      <input class="search-input" id="search-box" placeholder="搜索镜号 / 台词 / 体位..." oninput="renderBoardList()"/>
      <span id="status-pill" class="pill"></span>
      <button class="btn" onclick="reloadData()">🔄 刷新</button>
    </div>
  </div>

  <div class="main">
    <div id="view-overview" class="view active"></div>
    <div id="view-board" class="view">
      <div class="board-list" id="board-list"></div>
      <div class="inspector" id="inspector"></div>
    </div>
    <div id="view-assets" class="view"></div>
    <div id="view-docs" class="view"></div>
    <div id="view-voice" class="view"></div>
    <div id="view-media" class="view"></div>
  </div>

<script>
let SNAP = {snap_json};
let SELECTED_IDX = 0;

function esc(s) {{
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

function switchTab(name, btn) {{
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById('view-' + name).classList.add('active');
}}

async function reloadData() {{
  const res = await fetch('/api/overview');
  SNAP = await res.json();
  renderAll();
}}

function renderAll() {{
  document.getElementById('proj-name').textContent = SNAP.project_name + ' · ' + (SNAP.aspect || '未锁画幅');
  const pill = document.getElementById('status-pill');
  if (SNAP.errors.length > 0) {{
    pill.className = 'pill err';
    pill.textContent = `❌ ${{SNAP.errors.length}} 阻断错误`;
  }} else if (SNAP.warnings.length > 0) {{
    pill.className = 'pill warn';
    pill.textContent = `⚠️ ${{SNAP.warnings.length}} 警告`;
  }} else {{
    pill.className = 'pill ok';
    pill.textContent = '✅ 门禁全绿';
  }}
  renderOverview();
  renderBoardList();
  renderInspector();
  renderAssets();
  renderDocs();
  renderVoice();
  renderMedia();
}}

function renderOverview() {{
  const gates = Object.entries(SNAP.gates || {{}}).map(([k,v]) => {{
    const ok = (v && typeof v === 'object') ? v.passed : !!v;
    return `<span class="pill ${{ok ? 'ok' : 'err'}}" style="margin-right:6px;">${{esc(k)}}: ${{ok ? 'PASS' : 'FAIL'}}</span>`;
  }}).join('') || '<span style="color:var(--muted)">尚未运行门禁</span>';

  const errs = SNAP.errors.map(e => `<div style="color:var(--err);margin:4px 0;">❌ ${{esc(e)}}</div>`).join('') || '<div style="color:var(--ok);">✅ 0 阻断性错误 (ERROR)</div>';
  const warns = SNAP.warnings.map(w => `<div style="color:var(--warn);margin:4px 0;">⚠️ ${{esc(w)}}</div>`).join('') || '<div style="color:var(--ok);">✅ 0 警告 (WARNING)</div>';

  document.getElementById('view-overview').innerHTML = `
    <div class="grid-2">
      <div class="card">
        <h3>1. 底座硬锁与门禁状态</h3>
        <div class="kv">
          <div style="color:var(--muted)">项目目录</div><div>${{esc(SNAP.project_dir)}}</div>
          <div style="color:var(--muted)">画幅 (aspect)</div><div><b>${{esc(SNAP.aspect || '未锁定')}}</b></div>
          <div style="color:var(--muted)">项目模式</div><div><b>${{esc(SNAP.project_mode)}}</b></div>
          <div style="color:var(--muted)">绑定工作流</div><div>${{esc(SNAP.workflow_path || '未绑定')}} ${{SNAP.workflow_ok ? '✅' : '❌'}}</div>
          <div style="color:var(--muted)">Gate 1–6</div><div>${{gates}}</div>
          <div style="color:var(--muted)">16位点火令牌</div><div><code>${{esc(SNAP.confirm_token || '尚未签发（需先过 Gate 1–6）')}}</code></div>
        </div>
      </div>
      <div class="card">
        <h3>2. ERROR / WARNING 分级清单</h3>
        ${{errs}}
        <hr style="border-color:var(--border);margin:10px 0;"/>
        ${{warns}}
      </div>
    </div>`;
}}

function renderBoardList() {{
  const q = (document.getElementById('search-box').value || '').trim().toLowerCase();
  const list = document.getElementById('board-list');
  const filtered = SNAP.shots.filter(s => !q || s.shot_id.toLowerCase().includes(q) || s.dialogue.toLowerCase().includes(q) || s.pose.toLowerCase().includes(q));
  if (filtered.length === 0) {{
    list.innerHTML = '<div style="color:var(--muted);padding:12px;">暂无匹配镜头</div>';
    return;
  }}
  list.innerHTML = filtered.map(s => `
    <div class="board-item ${{s.index === SELECTED_IDX ? 'selected' : ''}}" onclick="selectShot(${{s.index}})">
      <div class="board-item-top">
        <span class="board-item-id">${{esc(s.shot_id)}}</span>
        <span class="board-item-meta">${{s.frames || '-'}}f · ${{esc(s.shot_size || '-')}} / ${{esc(s.camera_move || '-')}}</span>
      </div>
      <div class="board-item-meta">体位: ${{esc(s.pose || '文戏/未设')}} · 槽位: ${{s.ref_items.length}} 张 · LoRA: ${{s.lora}}</div>
      <div class="board-item-line">🗣️ ${{esc(s.dialogue || '（无台词/空镜）')}}</div>
    </div>`).join('');
}}

function selectShot(idx) {{
  SELECTED_IDX = idx;
  renderBoardList();
  renderInspector();
}}

function updatePoseHint() {{
  const sel = document.getElementById('pose-sel');
  const box = document.getElementById('pose-lock-box');
  if (!sel || !box) return;
  const p = SNAP.poses.find(x => x.id === sel.value);
  box.textContent = p ? `🔒 机位景别锁：${{p.framingZh || p.framingEn}}` : '文戏/未锁定肉戏体位';
}}

function renderInspector() {{
  const ins = document.getElementById('inspector');
  const s = SNAP.shots.find(x => x.index === SELECTED_IDX) || SNAP.shots[0];
  if (!s) {{
    ins.innerHTML = '<div class="card" style="color:var(--muted)">当前项目暂无 批量任务.json 镜头数据</div>';
    return;
  }}
  const selectedRels = s.ref_items.map(r => r.rel).filter(Boolean);
  const slotsHtml = s.ref_items.map(r => `
    <div class="slot-card ${{r.exists ? '' : 'err'}}">
      <div style="color:#93c5fd;font-weight:600;margin-bottom:4px;">&lt;Picture ${{r.slot}}&gt;</div>
      ${{r.rel ? `<img src="/file/${{encodeURIComponent(r.rel)}}"/>` : '<div style="height:74px;line-height:74px;color:var(--err);">缺失</div>'}}
      <div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:4px;" title="${{esc(r.raw)}}">${{esc(r.name)}}</div>
    </div>`).join('') || '<div style="color:var(--muted)">未挂载参考图</div>';

  const pickerHtml = SNAP.assets.map(a => `
    <label class="pick-item">
      <input type="checkbox" class="ref-chk" value="${{esc(a.rel)}}" ${{selectedRels.includes(a.rel) ? 'checked' : ''}}/>
      <img src="/file/${{encodeURIComponent(a.rel)}}" loading="lazy"/>
      <span title="${{esc(a.name)}}">${{esc(a.name)}}</span>
    </label>`).join('') || '<div style="color:var(--muted)">00_资产/ 暂无图片</div>';

  const poseOpts = ['<option value="">-- 不指定 / 纯文戏 --</option>'].concat(
    SNAP.poses.map(p => `<option value="${{esc(p.id)}}" ${{p.id === s.pose ? 'selected' : ''}}>${{esc(p.nameZh)}} (${{esc(p.id)}})</option>`)
  ).join('');

  ins.innerHTML = `
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
        <h2 style="margin:0;color:#60a5fa;">${{esc(s.shot_id)}}</h2>
        <div>
          <span class="pill ok">${{s.frames || '-'}}f (${{s.duration_sec || '-'}}s)</span>
          <span class="pill">${{esc(s.shot_size || '-')}} / ${{esc(s.camera_move || '-')}}</span>
          <span class="pill">LoRA: ${{s.lora}}</span>
        </div>
      </div>
      <div style="margin-bottom:10px;">🗣️ <b>${{esc(s.speaker || '未指定')}}</b> (${{esc(s.speech_mode || 'on_screen')}}): ${{esc(s.dialogue || '（无台词/空镜）')}}</div>
      <div class="slots-row">${{slotsHtml}}</div>
    </div>

    <div class="card">
      <h3>🎛️ 可视化选人 / 选体位防错（写回 批量任务.json）</h3>
      <div style="margin-bottom:12px;">
        <label style="display:block;margin-bottom:6px;color:var(--muted);">肉戏体位真源（94 条动作库）：</label>
        <select id="pose-sel" onchange="updatePoseHint()">${{poseOpts}}</select>
        <div id="pose-lock-box" class="pose-lock-box"></div>
      </div>
      <div style="margin-bottom:12px;">
        <div style="color:var(--muted);">勾选本镜挂载的人物/场景/道具参考图（按勾选顺序绑定 &lt;Picture 1..9&gt;）：</div>
        <div class="picker-grid">${{pickerHtml}}</div>
      </div>
      <div style="display:flex;align-items:center;gap:12px;">
        <button class="btn primary" onclick="saveCurrentShot(${{s.index}}, '${{esc(s.shot_id)}}')">💾 保存写回并实时重跑门禁校验</button>
        <span id="save-status" style="font-size:13px;color:var(--muted);"></span>
      </div>
    </div>

    <div class="card">
      <h3>📝 完整 H3 六段提示词</h3>
      <pre>${{esc(s.prompt)}}</pre>
    </div>`;
  updatePoseHint();
}}

async function saveCurrentShot(idx, shotId) {{
  const pose = document.getElementById('pose-sel').value;
  const refs = Array.from(document.querySelectorAll('.ref-chk:checked')).map(c => c.value);
  const st = document.getElementById('save-status');
  st.textContent = '正在写回并重跑校验...';
  const res = await fetch('/api/shot/update', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{ index: idx, shot_id: shotId, pose: pose, ref_images: refs }})
  }});
  const data = await res.json();
  if (data.ok) {{
    st.textContent = '✅ 已保存！正在刷新门禁状态...';
    await reloadData();
  }} else {{
    st.textContent = '❌ ' + (data.error || '保存失败');
  }}
}}

function renderAssets() {{
  const cards = SNAP.assets.map(a => `
    <div class="asset-card">
      <img src="/file/${{encodeURIComponent(a.rel)}}" loading="lazy"/>
      <div class="asset-meta">
        <div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${{esc(a.name)}}">${{esc(a.name)}}</div>
        <div style="margin-top:4px;"><span class="pill ${{a.is_ascii ? 'ok' : 'err'}}">${{a.is_ascii ? 'ASCII' : '非ASCII'}}</span> ${{a.size_kb}} KB</div>
      </div>
    </div>`).join('') || '<div style="color:var(--muted)">00_资产/ 暂无图片</div>';
  document.getElementById('view-assets').innerHTML = `<div class="card"><h3>00_资产/ 缩略图墙 (${{SNAP.assets.length}} 张)</h3><div class="asset-grid">${{cards}}</div></div>`;
}}

function renderVoice() {{
  const rows = Object.entries(SNAP.voice_bible || {{}}).map(([k, v]) => {{
    if (v && typeof v === 'object') {{
      return `<tr><td>${{esc(k)}}</td><td>${{esc(v.voice_id || v.timbre || '')}}</td><td>${{esc(v.style || '')}}</td></tr>`;
    }}
    return `<tr><td>${{esc(k)}}</td><td colspan="2">${{esc(v)}}</td></tr>`;
  }}).join('') || '<tr><td colspan="3" style="color:var(--muted)">暂无 voice_bible.json</td></tr>';
  document.getElementById('view-voice').innerHTML = `<div class="card"><h3>全集音色账本 (voice_bible.json)</h3><table><thead><tr><th>角色</th><th>音色/VoiceID</th><th>语气风格</th></tr></thead><tbody>${{rows}}</tbody></table></div>`;
}}

let CUR_EP = null;
let CUR_DOC = null;

function renderDocs() {{
  const eps = Object.keys(SNAP.episodes || {{}});
  if (eps.length === 0) {{
    document.getElementById('view-docs').innerHTML = '<div class="card" style="color:var(--muted)">当前项目 剧集/ 下暂无文档</div>';
    return;
  }}
  if (!CUR_EP || !SNAP.episodes[CUR_EP]) CUR_EP = eps[0];
  const docs = Object.keys(SNAP.episodes[CUR_EP] || {{}});
  if (!CUR_DOC || !SNAP.episodes[CUR_EP][CUR_DOC]) CUR_DOC = docs[0] || null;

  const epBtns = eps.map(e => `<button class="btn ${{e === CUR_EP ? 'primary' : ''}}" onclick="CUR_EP='${{esc(e)}}';CUR_DOC=null;renderDocs();">${{esc(e)}}</button>`).join(' ');
  const docBtns = docs.map(d => `<button class="btn ${{d === CUR_DOC ? 'primary' : ''}}" onclick="CUR_DOC='${{esc(d)}}';renderDocs();">${{esc(d)}}</button>`).join(' ');
  const content = CUR_DOC ? SNAP.episodes[CUR_EP][CUR_DOC] : '';

  document.getElementById('view-docs').innerHTML = `
    <div class="card">
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;align-items:center;">
        <span style="color:var(--muted);font-size:13px;">选择集数：</span>${{epBtns}}
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:center;">
        <span style="color:var(--muted);font-size:13px;">选择文档：</span>${{docBtns}}
      </div>
      <textarea id="doc-editor" style="width:100%;height:58vh;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:12px;font-family:Consolas,monospace;font-size:13px;line-height:1.5;">${{esc(content)}}</textarea>
      <div style="margin-top:10px;display:flex;gap:12px;align-items:center;">
        <button class="btn primary" onclick="saveDoc()">💾 保存 ${{esc(CUR_EP)}}/${{esc(CUR_DOC)}}</button>
        <span id="doc-save-msg" style="font-size:13px;color:var(--muted);"></span>
      </div>
    </div>`;
}}

async function saveDoc() {{
  const msg = document.getElementById('doc-save-msg');
  msg.textContent = '保存中...';
  const content = document.getElementById('doc-editor').value;
  const res = await fetch('/api/doc/save', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{ episode: CUR_EP, doc: CUR_DOC, content: content }})
  }});
  const data = await res.json();
  if (data.ok) {{
    SNAP.episodes[CUR_EP][CUR_DOC] = content;
    msg.textContent = '✅ 已保存落盘';
  }} else {{
    msg.textContent = '❌ ' + (data.error || '保存失败');
  }}
}}

function renderMedia() {{
  const items = SNAP.shots.filter(s => s.board || s.video).map(s => `
    <div class="card">
      <h4>${{esc(s.shot_id)}}</h4>
      ${{s.board ? `<img src="/file/${{encodeURIComponent(s.board)}}" loading="lazy" style="margin-bottom:8px;"/>` : ''}}
      ${{s.video ? `<video controls preload="metadata" src="/file/${{encodeURIComponent(s.video)}}"></video>` : ''}}
    </div>`).join('') || '<div class="card" style="color:var(--muted)">暂无五联质检板或成片输出</div>';
  document.getElementById('view-media').innerHTML = `<div class="media-grid">${{items}}</div>`;
}}

renderAll();
</script>
</body>
</html>"""


def make_handler(project_dir):
    p = Path(project_dir).resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def _send(self, code, content_type, body):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/":
                snap = collect_project_snapshot(p)
                self._send(HTTPStatus.OK, "text/html; charset=utf-8", render_dashboard_html(snap))
                return
            if parsed.path == "/api/overview":
                snap = collect_project_snapshot(p)
                self._send(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps(snap, ensure_ascii=False))
                return
            if parsed.path.startswith("/file/"):
                rel = urllib.parse.unquote(parsed.path[len("/file/"):]).lstrip("/")
                target = (p / rel).resolve()
                try:
                    target.relative_to(p)
                except ValueError:
                    self._send(HTTPStatus.FORBIDDEN, "text/plain; charset=utf-8", "Forbidden")
                    return
                if not target.is_file():
                    self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", "Not Found")
                    return
                ctype, _ = mimetypes.guess_type(str(target))
                self._send(HTTPStatus.OK, ctype or "application/octet-stream", target.read_bytes())
                return
            self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", "Not Found")

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/shot/update":
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8")
                try:
                    payload = json.loads(raw)
                    idx = int(payload["index"])
                    task_path = p / "批量任务.json"
                    batch = json.loads(task_path.read_text(encoding="utf-8"))
                    shots = batch.get("shots") or []
                    if idx < 0 or idx >= len(shots):
                        raise IndexError("shot index out of range")
                    if "pose" in payload:
                        shots[idx]["pose"] = payload["pose"]
                    if "ref_images" in payload and isinstance(payload["ref_images"], list):
                        shots[idx]["ref_images"] = payload["ref_images"]
                    task_path.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
                    self._send(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps({"ok": True}))
                except Exception as e:
                    self._send(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                return
            if parsed.path == "/api/doc/save":
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8")
                try:
                    payload = json.loads(raw)
                    ep = payload["episode"]
                    doc = payload["doc"]
                    content = payload["content"]
                    target = (p / "剧集" / ep / doc).resolve()
                    target.relative_to((p / "剧集").resolve())
                    target.write_text(content, encoding="utf-8")
                    self._send(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps({"ok": True}))
                except Exception as e:
                    self._send(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                return
            self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", "Not Found")

    return Handler


def session_file(project_dir):
    return Path(project_dir).resolve() / ".whale_dashboard.json"


def main():
    parser = argparse.ArgumentParser(description="WhaleDigest 本地可视化创作与审片工作台")
    parser.add_argument("project_dir", help="剧集/项目根目录")
    parser.add_argument("--port", type=int, default=0, help="监听端口，0 表示自动分配空闲端口（默认 0）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--open", action="store_true", help="自动打开浏览器")
    parser.add_argument("--detach", action="store_true", help="后台运行")
    parser.add_argument("--status", action="store_true", help="查看当前工作台状态")
    parser.add_argument("--stop", action="store_true", help="停止后台工作台")
    args = parser.parse_args()

    p = Path(args.project_dir).resolve()
    sf = session_file(p)

    if args.status:
        print(sf.read_text(encoding="utf-8") if sf.exists() else "未运行")
        return

    if args.stop:
        if sf.exists():
            info = json.loads(sf.read_text(encoding="utf-8"))
            pid = info.get("pid")
            if pid:
                try:
                    os.kill(pid, 15)
                except Exception:
                    pass
            sf.unlink(missing_ok=True)
            print(f"已停止 PID={pid}")
        else:
            print("未运行")
        return

    if args.detach and os.environ.get("WHALE_DASHBOARD_CHILD") != "1":
        env = dict(os.environ)
        env["WHALE_DASHBOARD_CHILD"] = "1"
        cmd = [sys.executable, str(Path(__file__).resolve()), str(p), "--port", str(args.port)]
        if args.no_browser or not args.open:
            cmd.append("--no-browser")
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
        )
        for _ in range(30):
            if sf.exists():
                info = json.loads(sf.read_text(encoding="utf-8"))
                url = info.get("url")
                print(f"Dashboard: {url}")
                print(f"Serving in the background as pid {info.get('pid')}")
                if args.open and not args.no_browser:
                    webbrowser.open(url)
                return
            time.sleep(0.1)
        print(f"后台进程已启动 (pid={proc.pid})，请稍后用 --status 查看地址")
        return

    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(p))
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/"
    sf.write_text(json.dumps({"pid": os.getpid(), "port": actual_port, "url": url}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"🐳 WhaleDigest 本地工作台已启动: {url}")
    if not args.no_browser and os.environ.get("WHALE_DASHBOARD_CHILD") != "1":
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n工作台已停止。")
    finally:
        sf.unlink(missing_ok=True)
        server.server_close()


if __name__ == "__main__":
    main()
