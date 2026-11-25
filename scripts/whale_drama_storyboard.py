#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
吞鲸宝典 · 正剧分镜与排时确定性生成器 (WhaleDrama Storyboard & Timing Engine)

解决正剧 (standard_drama) 缺少确定性拆镜与算时工具的问题：
- 严格按 `剧本.md` 原文逐场、逐句拆镜，绝不抄旧包假分镜、绝不按比例硬压台词时长；
- 每句台词按语速 (默认 4.1 字/秒，保底 2.0s) 计算刚性时长；
- 单句台词超过 H3 单镜上限 (默认 10.0s) 时，按标点自然拆分为「说话主镜 + 听者反应/细节镜」；
- 超出目标集长时，仅适度压缩纯动作镜/停顿余量，如实报告实际总时长，绝不把 24s 台词压成 0.21s。
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

DEFAULT_CHARS_PER_SEC = 4.1
DEFAULT_ACTION_SEC = 3.0
DEFAULT_MIN_SHOT_SEC = 2.0
DEFAULT_MAX_H3_SHOT_SEC = 10.0

_SCENE_RE = re.compile(r"^#{2,3}\s+(.+?)\s*$")
_DIALOGUE_TAG_RE = re.compile(r"<d>(?:\[[^\]]+\])?(.*?)</d>")
_SPEAKER_COLON_RE = re.compile(
    r"^\*{0,2}([\u4e00-\u9fffA-Za-z0-9_·]{1,16}(?:\s*(?:OS|VO|旁白|画外音))?)\*{0,2}\s*[：:]\s*(.+)$"
)
_QUOTE_RE = re.compile(r"[“\"「『]([^”\"」』]+)[”\"」』]")
_NON_SPEAKER = {
    "场景", "地点", "时间", "人物", "角色", "道具", "服装", "备注", "注", "提示",
    "女上位", "男上位", "后入", "侧入", "单人动作", "双人动作", "体位", "机位", "运镜",
}


def _clean_dialogue_text(raw: str) -> str:
    m = _DIALOGUE_TAG_RE.search(raw)
    if m:
        return m.group(1).strip()
    return re.sub(r"<[^>]+>", "", raw).strip()


def _han_char_count(text: str) -> int:
    # 统计有效发音字符（汉字+字母数字，忽略标点空白）
    cleaned = re.sub(r"[\s，。！？、；：“”‘’\"'（）()【】\[\]…—\-·,.!?;:]", "", text)
    return max(1, len(cleaned))


def _split_long_dialogue(text: str, max_chars: int) -> List[str]:
    """按标点将超长台词拆分为多段，每段不超过 max_chars。"""
    if len(text) <= max_chars:
        return [text]
    parts = re.split(r"([。！？；…]+)", text)
    sentences: List[str] = []
    buf = ""
    for p in parts:
        if not p:
            continue
        buf += p
        if re.match(r"^[。！？；…]+$", p):
            sentences.append(buf.strip())
            buf = ""
    if buf.strip():
        sentences.append(buf.strip())

    chunks: List[str] = []
    cur = ""
    for s in sentences:
        if not cur:
            cur = s
        elif len(cur) + len(s) <= max_chars:
            cur += s
        else:
            chunks.append(cur)
            cur = s
    if cur:
        chunks.append(cur)

    # 若单句仍超长，按逗号再拆
    final: List[str] = []
    for c in chunks:
        if len(c) <= max_chars:
            final.append(c)
        else:
            sub_parts = re.split(r"([，、]+)", c)
            sub_cur = ""
            for sp in sub_parts:
                if not sub_cur:
                    sub_cur = sp
                elif len(sub_cur) + len(sp) <= max_chars:
                    sub_cur += sp
                else:
                    final.append(sub_cur)
                    sub_cur = sp
            if sub_cur:
                final.append(sub_cur)
    return [x for x in final if x.strip()]


def parse_drama_script(script_text: str) -> List[Dict[str, Any]]:
    """解析正剧剧本为场次与事件流 (dialogue / action)。"""
    scenes: List[Dict[str, Any]] = []
    cur_scene: Dict[str, Any] = {"title": "主场景", "events": []}

    for raw_line in script_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("---") or line.startswith(">"):
            continue
        if line.startswith("# ") and not line.startswith("## "):
            continue

        m_scene = _SCENE_RE.match(line)
        if m_scene:
            title = m_scene.group(1).strip()
            if cur_scene["events"]:
                scenes.append(cur_scene)
            cur_scene = {"title": title, "events": []}
            continue

        m_spk = _SPEAKER_COLON_RE.match(line)
        if m_spk:
            spk = m_spk.group(1).strip()
            if spk not in _NON_SPEAKER:
                dlg = _clean_dialogue_text(m_spk.group(2))
                if dlg:
                    cur_scene["events"].append({
                        "kind": "dialogue",
                        "speaker": spk,
                        "text": dlg,
                    })
                    continue

        # 动作/叙述行（若含引号短对白也保留为动作+对白提示，不丢行）
        clean_act = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", line)
        cur_scene["events"].append({
            "kind": "action",
            "speaker": "",
            "text": clean_act,
        })

    if cur_scene["events"]:
        scenes.append(cur_scene)
    return scenes


def build_shots(
    scenes: List[Dict[str, Any]],
    episode_id: str = "EP001",
    chars_per_sec: float = DEFAULT_CHARS_PER_SEC,
    action_sec: float = DEFAULT_ACTION_SEC,
    min_shot_sec: float = DEFAULT_MIN_SHOT_SEC,
    max_shot_sec: float = DEFAULT_MAX_H3_SHOT_SEC,
    target_sec: float = 150.0,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    shots: List[Dict[str, Any]] = []
    max_chars_per_shot = max(12, int(math.floor(max_shot_sec * chars_per_sec)))

    shot_idx = 1
    for s_idx, scene in enumerate(scenes, 1):
        scene_title = scene["title"]
        for ev in scene["events"]:
            if ev["kind"] == "dialogue":
                chunks = _split_long_dialogue(ev["text"], max_chars_per_shot)
                for c_idx, chunk in enumerate(chunks):
                    n_chars = _han_char_count(chunk)
                    dur = round(max(min_shot_sec, n_chars / chars_per_sec), 2)
                    dur = min(max_shot_sec, dur)
                    framing = "中近景" if c_idx % 2 == 0 else "特写/反应切镜"
                    shots.append({
                        "shot_id": f"{episode_id}-{shot_idx:02d}",
                        "scene_idx": s_idx,
                        "scene_title": scene_title,
                        "kind": "dialogue",
                        "speaker": ev["speaker"],
                        "framing": framing,
                        "duration": dur,
                        "min_duration": dur,  # 台词刚性保底，绝不按比例压碎
                        "visual": f"{ev['speaker']}说话，情绪与口型同步" if c_idx == 0 else f"切镜：{ev['speaker']}继续陈述/对手反应",
                        "audio": f"{ev['speaker']}：{chunk}",
                    })
                    shot_idx += 1
            else:
                dur = round(max(min_shot_sec, action_sec), 2)
                shots.append({
                    "shot_id": f"{episode_id}-{shot_idx:02d}",
                    "scene_idx": s_idx,
                    "scene_title": scene_title,
                    "kind": "action",
                    "speaker": "",
                    "framing": "中景",
                    "duration": dur,
                    "min_duration": min_shot_sec,
                    "visual": ev["text"],
                    "audio": "环境音",
                })
                shot_idx += 1

    # 仅在超出 target_sec 时适度压缩纯动作镜（不碰台词刚性时长）
    total = round(sum(s["duration"] for s in shots), 2)
    if total > target_sec:
        excess = total - target_sec
        action_shots = [s for s in shots if s["kind"] == "action" and s["duration"] > s["min_duration"]]
        reducible = sum(s["duration"] - s["min_duration"] for s in action_shots)
        if reducible > 0:
            ratio = min(1.0, excess / reducible)
            for s in action_shots:
                cut = (s["duration"] - s["min_duration"]) * ratio
                s["duration"] = round(max(s["min_duration"], s["duration"] - cut), 2)
            total = round(sum(s["duration"] for s in shots), 2)

    # 计算累计时间轴
    t = 0.0
    for s in shots:
        s["start"] = round(t, 2)
        t = round(t + s["duration"], 2)
        s["end"] = t

    summary = {
        "episode_id": episode_id,
        "shot_count": len(shots),
        "total_sec": round(t, 2),
        "target_sec": target_sec,
        "over_target_sec": round(max(0.0, t - target_sec), 2),
        "dialogue_shots": sum(1 for s in shots if s["kind"] == "dialogue"),
        "action_shots": sum(1 for s in shots if s["kind"] == "action"),
    }
    return shots, summary


def render_storyboard_md(shots: List[Dict[str, Any]], summary: Dict[str, Any]) -> str:
    ep = summary["episode_id"]
    lines = [
        f"# {ep} 分镜脚本（正剧确定性排时版）",
        "",
        f"> 总镜数：**{summary['shot_count']} 镜**（对白 {summary['dialogue_shots']} / 动作 {summary['action_shots']}）｜"
        f"实际总时长：**{summary['total_sec']:.2f} 秒**｜目标参考：**{summary['target_sec']:.0f} 秒**",
        "",
    ]
    if summary["over_target_sec"] > 0:
        lines.append(
            f"> ⚠️ 提示：本集台词自然语速总时长超出目标 **{summary['over_target_sec']:.2f} 秒**。"
            f"已保留全部台词刚性时长（未做失真压缩），如需严格卡死 {summary['target_sec']:.0f} 秒请精简台词或拆分集数。"
        )
        lines.append("")

    cur_scene = None
    for s in shots:
        if s["scene_title"] != cur_scene:
            cur_scene = s["scene_title"]
            lines.append(f"## 场次 {s['scene_idx']}：{cur_scene}")
            lines.append("")
            lines.append("| 镜号 | 景别 | 时长 | 起止时间 | 画面内容 | 台词/音效 | 冻结边界 |")
            lines.append("|---|---|---|---|---|---|---|")
        lines.append(
            f"| {s['shot_id']} | {s['framing']} | {s['duration']:.2f}秒 | "
            f"{s['start']:.2f}s-{s['end']:.2f}s | {s['visual'].replace('|', '｜')} | "
            f"{s['audio'].replace('|', '｜')} | 首帧锁定 |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="吞鲸宝典 · 正剧分镜与排时确定性生成器")
    parser.add_argument("--script", required=True, help="剧本.md 路径")
    parser.add_argument("--output", help="输出分镜.md 路径（默认同目录下 分镜.md）")
    parser.add_argument("--episode", default="", help="集数编号，如 EP001（默认从路径推断）")
    parser.add_argument("--target-sec", type=float, default=150.0, help="目标集长（秒），默认 150")
    parser.add_argument("--cps", type=float, default=DEFAULT_CHARS_PER_SEC, help="语速（字/秒），默认 4.1")
    args = parser.parse_args()

    script_path = Path(args.script).resolve()
    if not script_path.is_file():
        print(f"[ERROR] 剧本文件不存在: {script_path}", file=sys.stderr)
        return 1

    ep = args.episode.strip()
    if not ep:
        m = re.search(r"(EP\d+)", str(script_path), re.IGNORECASE)
        ep = m.group(1).upper() if m else "EP001"

    out_path = Path(args.output).resolve() if args.output else script_path.parent / "分镜.md"
    text = script_path.read_text(encoding="utf-8")
    scenes = parse_drama_script(text)
    shots, summary = build_shots(
        scenes,
        episode_id=ep,
        chars_per_sec=args.cps,
        target_sec=args.target_sec,
    )
    md = render_storyboard_md(shots, summary)
    out_path.write_text(md, encoding="utf-8")
    print(
        f"[OK] {ep}: {summary['shot_count']} shots, {summary['total_sec']:.2f}s "
        f"(target {summary['target_sec']:.0f}s) -> {out_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
