#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
吞鲸宝典 v4.0 · ComfyUI 全自动后台批跑与微创重摇点火器 (Tunjing v4.0 Auto-Runner & Surgical Re-roller)

核心能力：
1. 断点续跑 (Checkpoint Resume)：崩溃或中断后重启自动跳过已落盘合格镜头，绝不重头白跑。
2. 点名微创重摇 (`--reroll 7,19 --candidates 2`)：只针对指定镜号更换随机 Seed 重跑 N 个候选版本 (`shot_07_v2.mp4`)，其余合格镜头物理锁死不动。
3. 自动五联抽帧质检板 (5-Frame Contact Sheet)：每镜落盘后自动用 FFmpeg 抽取 2%/25%/50%/75%/94% 五张关键帧拼成单张横条质检图 (`03_五联质检板/shot_XX_qc.jpg`)，一眼看穿有无多手/鬼影/字幕。
4. 跨集资产与声线锁死账本 (`series_bible.json`)：自动读取或初始化全剧统一的角色母版、空间图池、固定干声 WAV 与黄金 LoRA 配方，跨集拍 EP02~EP20 绝不失忆变脸。
5. 真实目录动态同步 + 文戏/肉戏 LoRA 权重动态切换 (`0.0` vs `0.45`) + 优先提取 `-audio.mp4` + 每镜 `/free` 冷却 10 秒。
"""

import os
import re
import sys
import json
import time
import random
import shutil
import subprocess
import argparse
import hashlib
import math
import urllib.request
import urllib.error
from tunjing_task_source import load_task_source, require_source_audit, source_record, validate_batch_metadata, validate_image_references
from tunjing_media import probe_media
from tunjing_audio_contract import resolve_audio_contract, validate_workflow_audio
from tunjing_compiler import lint_task_prompt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_WF = os.path.join(BASE_DIR, "..", "references", "workflows", "tunjing_v4_master_api.json")

# ── 画幅解析（横屏项目必备）：ResolutionSelector 只认带括号的原生枚举值 ──────
# 取值必须与 ComfyUI ResolutionSelector 的 COMBO 枚举逐字一致，否则整条 prompt 校验失败、静默零产出
ASPECT_ALIASES = {
    "16:9": "16:9 (Widescreen)",
    "landscape": "16:9 (Widescreen)",
    "横屏": "16:9 (Widescreen)",
    "横向": "16:9 (Widescreen)",
    "9:16": "9:16 (Portrait Widescreen)",
    "portrait": "9:16 (Portrait Widescreen)",
    "竖屏": "9:16 (Portrait Widescreen)",
    "竖向": "9:16 (Portrait Widescreen)",
    "1:1": "1:1 (Square)",
    "square": "1:1 (Square)",
    "4:3": "4:3 (Standard)",
    "3:4": "3:4 (Portrait Standard)",
    "3:2": "3:2 (Photo)",
    "2:3": "2:3 (Portrait Photo)",
    "21:9": "21:9 (Ultrawide)",
}


def resolve_aspect(value):
    """Return a supported native enum, rejecting an explicit unknown aspect."""
    if value is None or value == "":
        return None
    s = str(value).strip().lower()
    if s in ASPECT_ALIASES:
        return ASPECT_ALIASES[s]
    for enum in ASPECT_ALIASES.values():
        if enum.lower() == s:
            return enum
    raise ValueError("Unsupported aspect: " + str(value))
COMFY_URL = "http://127.0.0.1:8188"

def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def shot_reuse_metadata(target_mp4, task_sha, sid, shot, batch, sources=None):
    """Return the exact source fingerprint required before reusing an MP4."""
    prompt = shot.get("prompt") if isinstance(shot.get("prompt"), str) else ""
    raw_aspect = shot.get("aspect") or batch.get("aspect") or ""
    return {
        "schema": "tunjing-shot-output-v2",
        "task_sha256": task_sha,
        "shot_id": str(sid),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "aspect": str(raw_aspect),
        "frames": int(shot.get("frames")),
        "project_sources": sources,
        "workflow_sha256": file_sha256(DEFAULT_WF),
        "runner_sha256": file_sha256(__file__),
    }


def is_reusable_shot(target_mp4, expected):
    try:
        probe_media(target_mp4)
        with open(target_mp4 + ".meta.json", encoding="utf-8") as fh:
            recorded = json.load(fh)
        if not isinstance(recorded, dict):
            return False
        output_sha = recorded.pop("output_sha256", None)
        return recorded == expected and output_sha == file_sha256(target_mp4)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def write_shot_metadata(target_mp4, metadata):
    path = target_mp4 + ".meta.json"
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8", newline=chr(10)) as fh:
        json.dump(dict(metadata, output_sha256=file_sha256(target_mp4)), fh, ensure_ascii=False, indent=2)
        fh.write(chr(10))
    os.replace(temp, path)



def http_json(url, method="GET", payload=None, timeout=15):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else {}


def load_or_init_series_bible(project_dir):
    """
    跨集资产与声线锁死账本 (series_bible.json)：
    优先查找父目录（剧集总目录）或当前项目目录下的 series_bible.json；若不存在则自动生成标准模板并锁死。
    """
    parent_bible = os.path.join(os.path.dirname(os.path.abspath(project_dir)), "series_bible.json")
    local_bible = os.path.join(project_dir, "series_bible.json")
    bible_path = parent_bible if os.path.exists(parent_bible) else local_bible

    if os.path.exists(bible_path):
        with open(bible_path, "r", encoding="utf-8") as f:
            return json.load(f), bible_path

    default_bible = {
        "schema": "tunjing-series-bible-v4",
        "audio_mode": "H3_native_audio",
        "audio_reference_required": False,
        "ref_audios": [],
        "locked_models": {
            "unet": "minimax_h3_hybrid_fl2va_ref2va_b25-49-int8.safetensors",
            "clip": "qwen3vl_32b_minimax_h3_ultra_uncensored_heretic_int8_convrot.safetensors",
            "lora_dmad": {"name": "minimax_h3_dmad_full_dareties_v4_step600_comfy_fro.safetensors", "strength": 0.80},
            "lora_mystic": {"name": "MysticXXX_MMH3-V5-ref2va.safetensors", "drama_strength": 0.0, "action_strength": 0.45},
            "lora_style": {"name": "H3_RuMengSiHuan_1536-e8.safetensors", "strength": 0.80}
        },
        "characters": {
            "female_lead": {
                "dressed_master": "female_dressed.png",
                "nude_master": "female_nude.png"
            },
            "male_lead": {
                "dressed_master": "male_dressed.png",
                "nude_master": "male_nude.png"
            }
        },
        "spatial_pool": {
            "wide_main": "scene_main.png",
            "wall_elevation": "scene_wall.png",
            "close_surface": "scene_close.png"
        },
        "approved_seeds": {}
    }
    with open(local_bible, "w", encoding="utf-8") as f:
        json.dump(default_bible, f, ensure_ascii=False, indent=2)
    return default_bible, local_bible


def generate_5frame_contact_sheet(video_path, out_jpg_path):
    """Extract five actual frames and atomically publish a new contact sheet."""
    import tempfile
    try:
        media = probe_media(video_path)
        duration = float(media["format"]["duration"])
        parent = os.path.dirname(os.path.abspath(out_jpg_path))
        os.makedirs(parent, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            frames = []
            for index, fraction in enumerate((0.02, 0.25, 0.50, 0.75, 0.94)):
                frame = os.path.join(temporary, f"frame{index}.jpg")
                subprocess.run(["ffmpeg", "-y", "-ss", str(duration * fraction), "-i", video_path,
                                "-frames:v", "1", "-q:v", "3", frame], capture_output=True, timeout=15, check=True)
                if not os.path.isfile(frame):
                    return False
                frames.append(frame)
            output = os.path.join(temporary, "contact.jpg")
            command = ["ffmpeg", "-y"]
            for frame in frames:
                command += ["-i", frame]
            command += ["-filter_complex", "hstack=inputs=5", "-frames:v", "1", "-q:v", "2", output]
            subprocess.run(command, capture_output=True, timeout=20, check=True)
            if not os.path.isfile(output):
                return False
            os.replace(output, out_jpg_path)
        return True
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return False


def sync_assets_to_comfy(project_dir, comfy_input_dir):
    asset_dir = os.path.join(project_dir, "00_资产")
    if not os.path.isdir(asset_dir) or not comfy_input_dir or not os.path.isdir(comfy_input_dir):
        return 0
    copied = 0
    for fn in os.listdir(asset_dir):
        src = os.path.join(asset_dir, fn)
        if os.path.isfile(src) and all(ord(c) < 128 for c in fn):
            dst = os.path.join(comfy_input_dir, fn)
            shutil.copy2(src, dst)
            copied += 1
    return copied


def build_shot_workflow(base_wf, shot, custom_seed=None, prefix_override=None, aspect=None, batch=None):
    import copy
    errors, _ = lint_task_prompt(shot, batch)
    if errors:
        raise ValueError(f"{shot.get('shot_id', shot.get('id'))}: " + "; ".join(errors))
    contract = resolve_audio_contract(shot, batch)
    validate_workflow_audio(base_wf, contract)
    wf = copy.deepcopy(base_wf)
    validate_image_references(shot.get("ref_images"))
    ref_imgs = list(shot["ref_images"])
    # This engine ships one fixed Ref2VA graph. Never validate shot['prompt'] but
    # leave the model reading a stale literal/another Text node from the template.
    text_node = wf.get('263', {})
    model = wf.get('265', {})
    ports = model.get('inputs', {})
    if (text_node.get('class_type') != 'Text' or 'text' not in text_node.get('inputs', {})
            or model.get('class_type') != 'MiniMaxH3ReferenceToVideo'
            or ports.get('prompt') != ['263', 0]):
        raise ValueError('H3 正文接线错误：265.prompt 必须读取 Text 节点 263 的输出 0')
    for slot, node in enumerate(('51', '49', '50')):
        if (wf.get(node, {}).get('class_type') != 'LoadImage' or
                ports.get(f'ref_images.ref_image_{slot}') != [node, 0]):
            raise ValueError(f'H3 参考图接线错误：Picture {slot + 1} 必须读取节点 {node}')

    if "51" in wf:
        wf["51"]["inputs"]["image"] = ref_imgs[0]
    if "49" in wf:
        wf["49"]["inputs"]["image"] = ref_imgs[1]
    if "50" in wf:
        wf["50"]["inputs"]["image"] = ref_imgs[2]
    # 动态挂载第 4~9 扩展参考图槽位 (<Picture 4>~<Picture 9> -> Nodes 43, 19, 23, 199, 200, 201)
    # 有道具/扩展图时自动连上 Node 265，无道具镜自动断开 ref_image_3..8（绝不拔掉 Node 50 场景槽顶替！）
    extra_slot_nodes = [(3, "43"), (4, "19"), (5, "23"), (6, "199"), (7, "200"), (8, "201")]
    for slot_idx, node_id in extra_slot_nodes:
        port_key = f"ref_images.ref_image_{slot_idx}"
        if len(ref_imgs) > slot_idx and ref_imgs[slot_idx]:
            if wf.get(node_id, {}).get("class_type") != "LoadImage":
                raise ValueError(f"Missing extra LoadImage node {node_id}")
            if node_id in wf:
                wf[node_id]["inputs"]["image"] = ref_imgs[slot_idx]
            if "265" in wf:
                wf["265"]["inputs"][port_key] = [node_id, 0]
        elif "265" in wf and port_key in wf["265"]["inputs"]:
            del wf["265"]["inputs"][port_key]

    if "400" in wf:
        wf["400"]["inputs"]["lora_name"] = shot.get("lora_mystic_name", "MysticXXX_MMH3-V5-ref2va.safetensors")
        wf["400"]["inputs"]["strength_model"] = float(shot.get("lora_mystic_strength", 0.45))

    if "397" in wf and custom_seed is not None:
        wf["397"]["inputs"]["seed"] = int(custom_seed)

    # 画幅（横屏/竖屏）：优先级 shot.aspect > 批次 aspect > 工作流现值。
    # 宝典母版工作流默认 9:16，横屏项目若不带画幅会被静默出成竖屏。
    resolved_aspect = resolve_aspect(shot.get("aspect")) or resolve_aspect(aspect)
    if "252" in wf:
        if resolved_aspect:
            wf["252"]["inputs"]["aspect_ratio"] = resolved_aspect
        if shot.get("megapixels"):
            wf["252"]["inputs"]["megapixels"] = float(shot["megapixels"])
        print(f"[画幅] {shot.get('shot_id')} -> {wf['252']['inputs']['aspect_ratio']} "
              f"@ {wf['252']['inputs'].get('megapixels')}MP")

    if "259" in wf:
        wf["259"]["inputs"]["value"] = float(shot.get("duration", 5.0))
    if "263" in wf:
        wf["263"]["inputs"]["text"] = shot.get("prompt", "")
    if "265" in wf:
        wf["265"]["inputs"]["ref_image_size"] = "match"
        if "frames" in shot:
            wf["265"]["inputs"]["length"] = shot["frames"]
    if "364" in wf:
        num_m = re.search(r"(\d+)", str(shot.get("shot_id") or shot.get("id") or "1"))
        s_num = int(num_m.group(1)) if num_m else 1
        default_pfx = shot.get("filename_prefix") or f"EP001_SHOT_{s_num:03d}"
        wf["364"]["inputs"]["filename_prefix"] = prefix_override or default_pfx

    return wf


def canonical_shot_id(value):
    text = str(value).strip().casefold()
    text = re.sub(r"^(?:ep\d+[_-])?shot[_-]?", "", text)
    numeric = re.fullmatch(r"0*(\d+)([a-z]*)", text)
    return str(int(numeric.group(1))) + numeric.group(2) if numeric else text


def shot_output_stem(shot, batch, project_dir):
    """Use the literal shot identity; episode digits are not shot digits."""
    explicit = shot.get("filename_prefix")
    if explicit is not None:
        if not isinstance(explicit, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", explicit):
            raise ValueError("filename_prefix 必须是单一 ASCII 文件名，不可包含目录")
        return explicit
    ep_match = re.search(r"EP(\d+)", str(batch.get("project", "")) + " " + os.path.basename(os.path.abspath(project_dir)), re.I)
    ep_tag = f"EP{int(ep_match.group(1)):03d}" if ep_match else "EP001"
    key = canonical_shot_id(shot.get("shot_id", shot.get("id")))
    numeric = re.fullmatch(r"(\d+)([a-z]*)", key)
    token = f"{int(numeric.group(1)):03d}{numeric.group(2).upper()}" if numeric else key
    return f"{ep_tag}_SHOT_{token}"


def parse_reroll_targets(reroll_str):
    if reroll_str is None:
        return set()
    targets = set()
    for part in reroll_str.split(","):
        part = part.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", part):
            raise ValueError("重跑镜号不能为空或含无效字符")
        targets.add(canonical_shot_id(part))
    return targets


def main():
    ap = argparse.ArgumentParser(description="吞鲸 v4.0 ComfyUI 全自动后台批跑与微创重摇点火器")
    ap.add_argument("project_dir", help="项目目录（内含 批量任务.json）")
    ap.add_argument("--dry-build", action="store_true", help="仅在本地生成逐镜就绪的 API JSON 包与跨集账本")
    selection = ap.add_mutually_exclusive_group()
    selection.add_argument("--only-first", action="store_true", help="仅渲染第 1 镜用于首镜五联切片抽检")
    selection.add_argument("--reroll", default=None, help="按实际 shot_id 重跑（逗号分隔，如 7,19 或 04B）")
    ap.add_argument("--candidates", type=int, default=1, help="每个重摇镜头生成的候选版本数（默认1，可设2~3挑片）")
    ap.add_argument("--render-timeout", type=float, default=3600, help="每个渲染任务最长等待秒数")
    ap.add_argument("--force", action="store_true", help="忽略断点续跑缓存，强制重跑全部目标镜头")
    ap.add_argument("--confirm-token", default="", help="审阅后使用当前状态对应的 16 位完整性令牌（未提供严禁连接 ComfyUI 渲染！）")
    args = ap.parse_args()
    if not math.isfinite(args.render_timeout) or args.render_timeout <= 0:
        ap.error("--render-timeout 必须为有限正数")
    if args.candidates < 1:
        ap.error("--candidates 必须至少为 1")

    try:
        bj_path, batch, task_sha = load_task_source(args.project_dir)
        initial_source = source_record(args.project_dir)
        if initial_source["task_path"] != str(bj_path) or initial_source["task_sha256"] != task_sha:
            raise ValueError("任务在读取期间发生变化，请重新核验")
        validate_batch_metadata(batch)
        for shot in batch["batch_shots"]:
            resolve_audio_contract(shot, batch)
        if not args.dry_build:
            with open(os.path.join(args.project_dir, ".tunjing_status.json"), encoding="utf-8") as fh:
                require_source_audit(args.project_dir, json.load(fh))
    except (ValueError, OSError) as exc:
        print(f"[X] 任务或门禁无效: {exc}")
        sys.exit(1)
    bible, bible_path = load_or_init_series_bible(args.project_dir)
    print(f"任务源: {bj_path}; SHA256={task_sha}")
    with open(DEFAULT_WF, "r", encoding="utf-8") as f:
        base_wf = json.load(f)

    all_shots = batch.get("batch_shots", [])
    try:
        stems = [shot_output_stem(shot, batch, args.project_dir).casefold() for shot in all_shots]
        if len(stems) != len(set(stems)):
            raise ValueError("多个镜头指向同一个输出文件名，拒绝覆盖")
        ids = [str(shot.get("shot_id", shot.get("id"))).casefold() for shot in all_shots]
        if len(ids) != len(set(ids)):
            raise ValueError("镜号大小写冲突，拒绝覆盖 API 负载")
        reroll_set = parse_reroll_targets(args.reroll)
        if reroll_set:
            by_id = {}
            for shot in all_shots:
                key = canonical_shot_id(shot.get("shot_id", shot.get("id")))
                if key in by_id:
                    raise ValueError("镜号归一化后重复: " + key)
                by_id[key] = shot
            missing = reroll_set - by_id.keys()
            if missing:
                raise ValueError("未找到重跑镜号: " + ", ".join(sorted(missing)))
            candidate_stems = [
                shot_output_stem(shot, batch, args.project_dir).casefold() + f"_v{number}"
                for shot in all_shots
                if canonical_shot_id(shot.get("shot_id", shot.get("id"))) in reroll_set
                for number in range(1, args.candidates + 1)
            ]
            if set(candidate_stems) & set(stems) or len(candidate_stems) != len(set(candidate_stems)):
                raise ValueError("重跑候选输出名与现有镜头输出名冲突，拒绝覆盖")
    except ValueError as exc:
        ap.error(str(exc))

    if reroll_set:
        shots = [s for s in all_shots if canonical_shot_id(s.get("shot_id", s.get("id"))) in reroll_set]
        print(f"[🎯 微创重摇模式] 仅针对点名镜号 {sorted(reroll_set)} 重摇 {args.candidates} 个候选版本，其余镜头物理保护锁死！")
    elif args.only_first and all_shots:
        shots = all_shots[:1]
    else:
        shots = all_shots

    payload_dir = os.path.join(args.project_dir, "01_ComfyUI就绪负载")
    out_video_dir = os.path.join(args.project_dir, "02_成片输出")
    qc_sheet_dir = os.path.join(args.project_dir, "03_五联质检板")
    os.makedirs(payload_dir, exist_ok=True)
    os.makedirs(out_video_dir, exist_ok=True)
    os.makedirs(qc_sheet_dir, exist_ok=True)

    for s in shots:
        try:
            wf = build_shot_workflow(base_wf, s, aspect=batch.get("aspect"), batch=batch)
        except ValueError as exc:
            print(f"[X 提示词或接线无效] {exc}")
            sys.exit(1)
        shot_identifier = s.get("shot_id", s.get("id"))
        out_p = os.path.join(payload_dir, f"{shot_identifier}_api.json")
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(wf, f, ensure_ascii=False, indent=2)

    print(f"[✓] 已在 {payload_dir} 生成 {len(shots)} 份吞鲸 v4.0 逐镜 API 负载（已完成 LoRA 文肉分级与空间图池绑定）。")
    if args.dry_build:
        return

    # ── 物理防擅自开跑死锁 (Anti-Autostart Ignition Lock) ──
    # 1) 必须已通过 Gate 1 ~ Gate 5
    import hashlib
    status_file = os.path.join(args.project_dir, ".tunjing_status.json")
    if not os.path.exists(status_file):
        print("[X 越权拦截] 未找到 .tunjing_status.json！严禁跳过 Gate 1~5 擅自启动 ComfyUI 渲染！")
        sys.exit(1)
    st_data = json.load(open(status_file, "r", encoding="utf-8"))
    if not {1, 2, 3, 4, 5}.issubset(set(st_data.get("passed_steps", []))):
        print(f"[X 越权拦截] Gate 1~5 尚未全部通过 (当前仅通过: {st_data.get('passed_steps')})！严禁擅自提交渲染！")
        sys.exit(1)

    # 2) Match the current integrity token; a bundled key is not an authentication boundary.
    try:
        from tunjing_core import sign_project
        expected_token = sign_project(args.project_dir)
    except Exception as exc:
        print(f"[X] 无法计算当前任务签名，拒绝降级放行: {exc}")
        sys.exit(1)
    if args.confirm_token.strip() != expected_token:
        receipt_path = os.path.join(args.project_dir, "监制五维核对签字单.md")
        print("=" * 75)
        print("🛑 【吞鲸防擅自开跑物理死锁 (Ignition Lock) 触发】")
        print("原因：Agent 严禁在未经监制明确批准的情况下擅自向 ComfyUI 提交渲染任务！")
        print(f"请先向监制呈报对账表：{receipt_path}")
        print(f"待监制确认「参考图对齐、体位正确、交合特写齐备、台词无误」并下令渲染后，")
        print(f"方可使用当前任务包唯一授权码点火：--confirm-token {expected_token}")
        print("=" * 75)
        sys.exit(1)

    if source_record(args.project_dir) != initial_source:
        print("[X] 任务在准备期间发生变化，请重新核验")
        sys.exit(1)
    try:
        stats = http_json(f"{COMFY_URL}/system_stats")
    except Exception as e:
        print(f"[X] ComfyUI ({COMFY_URL}) 不可连接 ({e})；仅保存了就绪负载，渲染未执行: {payload_dir}")
        sys.exit(1)

    argv = stats.get("system", {}).get("argv", [])
    input_dir = ""
    output_dir = ""
    for i, a in enumerate(argv):
        if a == "--input-directory" and i + 1 < len(argv):
            input_dir = argv[i + 1]
        if a == "--output-directory" and i + 1 < len(argv):
            output_dir = argv[i + 1]
    # ComfyUI default directories are relative to its main.py location.
    main_path = next((str(a) for a in argv if str(a).lower().endswith("main.py")), "")
    comfy_root = os.path.dirname(os.path.abspath(main_path)) if main_path else ""
    input_dir = input_dir or (os.path.join(comfy_root, "input") if comfy_root else "")
    output_dir = output_dir or (os.path.join(comfy_root, "output") if comfy_root else "")
    if not input_dir or not os.path.isdir(input_dir):
        raise ValueError("无法确认 ComfyUI Input 目录，请在服务端配置 --input-directory")
    n_sync = sync_assets_to_comfy(args.project_dir, input_dir)
    print(f"[✓] ComfyUI 在线 | 已同步 {n_sync} 个 ASCII 资产至真实 Input 目录: {input_dir}")

    for idx, s in enumerate(shots, 1):
        sid = shot_output_stem(s, batch, args.project_dir)
        target_mp4 = os.path.join(out_video_dir, f"{sid}.mp4")

        # 断点续跑保护：必须同时匹配当前任务、提示词、画幅和帧数指纹
        if source_record(args.project_dir) != initial_source:
            raise ValueError("Task changed before output reuse; run audit again")
        expected_meta = shot_reuse_metadata(target_mp4, task_sha, sid, s, batch, sources=initial_source)
        reusable = False
        if not reroll_set and not args.force and os.path.exists(target_mp4):
            reusable = is_reusable_shot(target_mp4, expected_meta)
            if not reusable:
                print(f"[↻ 断点续跑重算] {sid}.mp4 存在但任务指纹不匹配，拒绝复用。")
        if reusable:
            print(f"[⏭ 断点续跑跳过] {sid}.mp4 已存在且完整，直接保护跳过。")
            continue

        n_cand = max(1, args.candidates) if reroll_set else 1
        for c_idx in range(1, n_cand + 1):
            seed_val = random.randint(10**13, 9 * 10**14)
            ver_suffix = f"_v{c_idx}" if n_cand > 1 or reroll_set else ""
            prefix = f"{sid}{ver_suffix}"
            wf = build_shot_workflow(base_wf, s, custom_seed=seed_val, prefix_override=prefix, aspect=batch.get("aspect"), batch=batch)

            # 反作弊锁 4A：提交前核验本镜 3 张参考图在 ComfyUI 真实 input 目录中物理存在（彻底杜绝空占位符 0.0s 秒退）
            if input_dir and os.path.isdir(input_dir):
                missing_refs = [r for r in s.get("ref_images", []) if not os.path.exists(os.path.join(input_dir, r))]
                if missing_refs:
                    print(f"[X 致命阻断] {sid} 绑定的参考图 {missing_refs} 在 ComfyUI Input 目录 ({input_dir}) 中不存在！拒绝提交空跑！")
                    sys.exit(1)

            t_start = time.monotonic()
            print(f"\n[▶] ({idx}/{len(shots)}) 提交 {sid}{ver_suffix} | Seed={seed_val} | 姿势={s.get('pose')} | 时长={s.get('duration')}s ({s.get('frames')}f) | LoRA={s.get('lora_mystic_strength')}")
            if source_record(args.project_dir) != initial_source:
                raise ValueError("Task changed after audit; dispatch refused")
            with open(status_file, encoding="utf-8") as fh:
                require_source_audit(args.project_dir, json.load(fh))
            if sign_project(args.project_dir) != expected_token:
                raise ValueError("Project evidence changed after approval; dispatch refused")
            resp = http_json(f"{COMFY_URL}/prompt", method="POST", payload={"prompt": wf})
            pid = resp.get("prompt_id")
            if not pid:
                print(f"[X] {sid} 提交失败: {resp}")
                sys.exit(1)

            while True:
                if time.monotonic() - t_start > args.render_timeout:
                    raise TimeoutError(f"渲染等待超时: {sid} / {pid}")
                time.sleep(5)
                hist = http_json(f"{COMFY_URL}/history/{pid}")
                if pid in hist:
                    elapsed = round(time.monotonic() - t_start, 1)
                    st_info = hist[pid].get("status", {})
                    outputs = hist[pid].get("outputs", {})
                    gifs = outputs.get("364", {}).get("gifs", [])
                    # 反作弊锁 4B：拦截 0.0s 秒退或无 MP4 产物的假完成！
                    if st_info.get("status_str") == "error" or not gifs or not st_info.get("completed", True):
                        print(f"[X 渲染异常中断] {sid} 耗时仅 {elapsed}s 且未产出有效视频！底层状态: {st_info}")
                        sys.exit(1)
                    picked = None
                    for g in gifs:
                        fn = g.get("filename", "")
                        if fn.endswith("-audio.mp4"):
                            picked = g
                            break
                    if not picked and gifs:
                        picked = gifs[0]
                    if picked:
                        fn = picked.get("filename")
                        sub = picked.get("subfolder", "")
                        src_vid = os.path.join(output_dir, sub, fn) if output_dir else ""
                        if not src_vid or not os.path.exists(src_vid):
                            from urllib.parse import urlencode
                            view_url = f"{COMFY_URL}/view?" + urlencode({"filename": fn, "subfolder": sub, "type": picked.get("type", "output")})
                            src_vid = os.path.join(out_video_dir, f".{sid}{ver_suffix}.download.mp4")
                            with urllib.request.urlopen(view_url, timeout=60) as response, open(src_vid, "wb") as handle:
                                shutil.copyfileobj(response, handle)
                        dst_vid = os.path.join(out_video_dir, f"{sid}{ver_suffix}.mp4")
                        if os.path.exists(src_vid):
                            probe_media(src_vid)
                            shutil.copy2(src_vid, dst_vid)
                            qc_jpg = os.path.join(qc_sheet_dir, f"{sid}{ver_suffix}_qc5.jpg")
                            if not generate_5frame_contact_sheet(dst_vid, qc_jpg):
                                raise RuntimeError(f"五联质检板生成失败: {sid}")
                            write_shot_metadata(dst_vid, expected_meta)
                            print(f"[✓] {sid}{ver_suffix} 真实渲染入库 ({elapsed}s) -> {dst_vid} | 五联质检板 -> {qc_jpg}")
                        else:
                            print(f"[X] {sid}{ver_suffix} 产物文件缺失或损坏: {src_vid}")
                            sys.exit(1)
                    break

            try:
                urllib.request.urlopen(urllib.request.Request(f"{COMFY_URL}/free", data=json.dumps({"unload_models": False, "free_memory": True}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST"), timeout=10).read()
            except Exception:
                pass
            time.sleep(10)


    # ── 全集渲染收官后：全自动串联【母带响度精修 + 自动打包打入剪映本地草稿箱】──
    if not reroll_set and not args.only_first:
        print("\n" + "=" * 70)
        print("🎬 全集镜头渲染完毕！正在自动启动【母带精修 (-16 LUFS) ➔ 自动导入剪映草稿箱】流水线...")
        print("=" * 70)
        master_script = os.path.join(BASE_DIR, "tunjing_mastering.py")
        jy_script = os.path.join(BASE_DIR, "export_jianying_draft.py")
        subprocess.run([sys.executable, master_script, args.project_dir], check=True)
        subprocess.run([sys.executable, jy_script, args.project_dir], check=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    main()
