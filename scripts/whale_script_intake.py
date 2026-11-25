#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
吞鲸宝典 · 非破坏性剧本导入与结构规范化引擎 (WhaleScript Intake & Structural Normalizer)

遵循 `references/sd_core/screenplay-format.md` 第 7 节「现有文本的规范化入口」铁律：
1. 原件字节级备份留档到 `<project>/输入/`（附来源 SHA256 与编码记录），绝不丢失原文；
2. 「规范化不改台词」：只统一结构外壳（集号 `# EP001`、场次 `## EP001-SC001 内/外 · 地点 · 时间`、
   对白 `角色（表演）：台词`、生产标签 `[VO]`/`[OS]`/`[SFX]`/`[画面文字]`/`[连续性]`/`[转场]`），
   严禁润色、增删或篡改作者台词与剧情顺序；
3. 支持多集整稿自动分集切片（基于 `sd_core/episode_intake.py`），以及单集散稿/老工作区存量剧本规范化；
4. 默认预览 (`--dry-run`) 只输出结构对照与统计；传入 `--apply` 才落盘 `剧集/<EP>/剧本.md`，
   并自动调用 `sd_core/screenplay_index.py` + `sd_core/duration_estimate.py` 汇报台词字数、VO 占比与估时。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SD_CORE_DIR = SCRIPT_DIR / "sd_core"
for _p in (str(SCRIPT_DIR), str(SD_CORE_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import episode_intake as ep_intake

CHINESE_DIGITS = ep_intake.CHINESE_DIGITS
EP_SPLIT_RE = re.compile(
    r"^[ \t\u3000]*(?:#{1,3}[ \t]+)?(?:第\s*([0-9]+|[零一二三四五六七八九十百千两]+)\s*集|EP\s*([0-9]{1,4})|Episode\s+([0-9]{1,4}))(?=[ \t\u3000·:：—《「【(（]|$)(?:[ \t\u3000·:：—-]+([^\r\n]*)|([《「【(（][^\r\n]*))?$",
    re.IGNORECASE | re.MULTILINE,
)
STD_SCENE_RE = re.compile(
    r"^##\s+(EP\d{3,}-SC\d{3,})\s+(内外|内|外)\s*·\s*(.+?)\s*·\s*(.+?)\s*$"
)
ALT_SCENE_PATTERNS = [
    # 1-1 内 客厅 日 / 1-2 日/外 街道
    re.compile(r"^(?:#{1,4}\s*)?(?:第?\d+\s*[-—.]\s*\d+|\d+-\d+|SC\d{1,3}|S\d+C\d+)(?:\s+|(?=[日夜晨昏内外]))(.+)$", re.I),
    # ### 场景一：办公室（夜） / ## 场次 1：酒店走廊（内·夜）
    re.compile(r"^(?:#{1,4}\s*)?(?:场景|场次|序幕|尾声|终章)[一二三四五六七八九十百零0-9]*[：:·\s]+(.+)$"),
    # ## 第一幕 办公室 / ## 第2场 街角
    re.compile(r"^(?:#{1,4}\s*)?第\s*[0-9零一二三四五六七八九十百]+\s*[幕场](?:[：:·\s]+(.+))?$"),
    # 【场景】办公室 内 夜
    re.compile(r"^【\s*(?:场景|场次)\s*】\s*(.+)$"),
]
VOICE_TAG_INLINE_RE = re.compile(
    r"^(?:\*\*)?(?P<speaker>[^：:*（）()\[\]#\s]{1,24})(?:\s*[（(]?|\s+)(?P<tag>VO|OS|旁白|画外音|画外|内心|混响|心声|语音|电话|录音|V\.O\.|O\.S\.)[）)]?\s*(?:[：:]\s*\*\*|\*\*\s*[：:]|[：:])\s*(?P<text>.+)$",
    re.I,
)
BRACKET_SPEAKER_RE = re.compile(
    r"^【\s*(?P<speaker>[^】]{1,32}?)\s*】\s*(?:[（(](?P<cue>[^）)]+)[）)])?\s*[：:]?\s*(?P<text>.+)$"
)
BOLD_SPEAKER_RE = re.compile(
    r"^\*\*(?P<speaker>[^*：:\r\n（）()]{1,24}?)(?:[（(](?P<cue>[^）)]+)[）)])?(?:[：:]\*\*|\*\*\s*[（(](?P<cue2>[^）)]+)[）)]\s*[：:]|\*\*\s*[：:])\s*(?P<text>.+)$"
)
PLAIN_SPEAKER_RE = re.compile(
    r"^(?P<speaker>[^\s：:（）()\[\]#*，。！？；、.!?,]{1,14})(?:[（(](?P<cue>[^）)\r\n]{1,30})[）)])?\s*[：:]\s*(?P<text>.+)$"
)
PROD_BRACKET_RE = re.compile(
    r"^(?:\[|【)\s*(VO|OS|SFX|音效|画面文字|字幕|连续性|转场)(?:\s*(?:\]|】)\s*[：:]?\s*|\s*[：:]\s*([^\]】]+)\s*(?:\]|】)\s*$)(.*)$",
    re.I,
)
SFX_PREFIX_RE = re.compile(r"^(?:音效|声效|SFX|画面文字|字幕|转场|连续性)\s*[：:]\s*(.+)$", re.I)




def detect_document_role(text: str) -> str:
    """判定输入文本属于 screenplay / storyboard / video_prompt，防无脑错位加载。"""
    t = text or ""
    if (
        ("subject_definitions:" in t and "detailed_description:" in t)
        or ("integrated_multimodal_description:" in t and "overall_soundscape:" in t)
    ):
        return "video_prompt"
    shot_heads = len(re.findall(r"^#{1,4}\s+\[?(?:SHOT|MOTION|R\d+)-", t, re.M))
    inline_shots = len(re.findall(r"^SHOT-\d+\b", t, re.M))
    has_board_meta = bool(re.search(r"(?:景别|机位|槽位分级|Track:\s*Ref2V|H3帧数|\|\s*\d+f\s*｜)", t))
    if shot_heads >= 2 or (inline_shots >= 2 and has_board_meta) or (shot_heads >= 1 and has_board_meta):
        return "storyboard"
    if re.search(r"^#\s+EP\d+\s*(?:执行稿|分镜定稿)", t, re.M) and (shot_heads >= 1 or inline_shots >= 1):
        return "storyboard"
    return "screenplay"


def read_source_text(path: Path) -> tuple[bytes, str, str]:
    raw_bytes = path.read_bytes()
    if path.suffix.lower() == ".docx":
        with zipfile.ZipFile(path) as zf:
            xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paras = []
        for p in root.findall(".//w:p", ns):
            texts = [t.text for t in p.findall(".//w:t", ns) if t.text]
            paras.append("".join(texts))
        return raw_bytes, "\n".join(paras), "docx-utf8"
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return raw_bytes, raw_bytes.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw_bytes, raw_bytes.decode("utf-8", errors="replace"), "utf-8-replace"


def _strip_outer_quotes(text: str) -> str:
    s = text.strip()
    if len(s) >= 2 and s[0] == "`" and s[-1] == "`":
        s = s[1:-1].strip()
    m_d = re.fullmatch(r"<d>\s*(?:\[[A-Za-z_ -]+\]\s*)?([\s\S]*?)\s*</d>", s, re.I)
    if m_d:
        s = m_d.group(1).strip()
    if len(s) >= 2 and ((s[0] == "「" and s[-1] == "」") or (s[0] == "“" and s[-1] == "”") or (s[0] == '"' and s[-1] == '"')):
        return s[1:-1].strip()
    return s


def _parse_scene_meta(raw: str, fallback_idx: int) -> tuple[str, str, str]:
    cleaned = re.sub(r"^#{1,4}\s*", "", raw).strip()
    cleaned = re.sub(r"^(?:EP\d+-)?SC\d+\s*[·・:：\s]*", "", cleaned, flags=re.I).strip()
    # Extract trailing (夜) / （内/夜） / （日）
    time_val = "日"
    space_val = "内"
    m_trail = re.search(r"[（(]([^）)]+)[）)]\s*$", cleaned)
    if m_trail:
        inside = m_trail.group(1).strip()
        cleaned = cleaned[:m_trail.start()].strip()
        for tok in re.split(r"[/·・,\s]+", inside):
            if tok in ("内", "外", "内外"):
                space_val = tok
            elif any(k in tok for k in ("日", "夜", "晨", "昏", "傍晚", "凌晨", "黄昏", "午后", "雨")):
                time_val = tok
    # Split by middle dot or whitespace tokens like "内 · 客厅 · 夜" or "客厅 内 夜"
    # Split compact prefix like "日内 环保局" or "夜外 巷子口"
    m_comp = re.match(r"^(日|夜|晨|昏|午)(内外|内|外)(?:\s+|$)(.*)$", cleaned)
    if m_comp:
        time_val = m_comp.group(1)
        space_val = m_comp.group(2)
        cleaned = m_comp.group(3).strip()
    parts = [p.strip() for p in re.split(r"\s*[·・|]\s*", cleaned) if p.strip()]
    loc_parts = []
    for part in parts:
        sub_tokens = part.split()
        if part in ("内", "外", "内外"):
            space_val = part
        elif part in ("日", "夜", "晨", "昏", "黄昏", "傍晚", "凌晨", "午", "阴", "雨夜"):
            time_val = part
        elif len(sub_tokens) >= 2 and any(
            re.fullmatch(r"(?:[日夜晨昏午]?(?:内外|内|外)|日|夜|晨|昏|黄昏|傍晚|凌晨)", t)
            for t in sub_tokens
        ):
            kept = []
            for t in sub_tokens:
                mc = re.fullmatch(r"(日|夜|晨|昏|午)(内外|内|外)", t)
                if mc:
                    time_val, space_val = mc.group(1), mc.group(2)
                elif t in ("内", "外", "内外"):
                    space_val = t
                elif t in ("日", "夜", "晨", "昏", "黄昏", "傍晚", "凌晨"):
                    time_val = t
                else:
                    kept.append(t)
            if kept:
                loc_parts.append(" ".join(kept))
        else:
            loc_parts.append(part)
    location = " · ".join(loc_parts).strip(" ：:·-") or f"场景{fallback_idx}"
    return space_val, location, time_val


def _is_non_dialogue_label(label: str) -> bool:
    s = re.sub(r"^\*+|\*+$", "", label.strip())
    low = s.lower()
    if low in {
        "时间", "地点", "人物", "角色", "场景", "时长", "景别", "机位", "运镜", "备注", "提示",
        "画面", "动作", "出场资产", "核心人物", "剧情梗概", "目标", "阻碍", "冲突", "状态",
        "人物表", "分集", "集名", "标题", "副标题", "关系底线", "结局", "结尾",
        "面部近景", "近景", "特写", "全景", "中景",
    }:
        return True
    if re.fullmatch(r"ep\d+结尾|第.+[幕场集]结束", low):
        return True
    if any(s.endswith(sfx) for sfx in ("近景", "特写", "远景", "全景", "中景", "结尾", "几步", "底线", "场面", "瞬间", "如下", "反应")):
        return True
    if len(s) > 6 and any(w in s for w in ("的", "了", "着", "在", "把", "被", "从", "向", "分成")):
        return True
    return False


def normalize_episode_markdown(ep_id: str, title: str, raw_text: str) -> dict[str, Any]:
    """将单集非标准剧本文本按「最小结构规范化、不改台词」原则转为标准 Markdown。"""
    ep_num_m = re.search(r"(\d+)", ep_id)
    ep_norm = f"EP{int(ep_num_m.group(1)):03d}" if ep_num_m else "EP001"
    ep_title = (title or "").strip()

    raw_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = raw_text.splitlines()
    out_lines: list[str] = []
    scenes_converted = 0
    dialogues_converted = 0
    tags_converted = 0
    actions_converted = 0
    preserved_markdown = 0
    unmapped_lines: list[dict[str, Any]] = []

    current_sc = 0
    in_comment = False
    first_h1_seen = False

    for lineno, raw_line in enumerate(lines, 1):
        stripped = raw_line.strip()
        if in_comment:
            out_lines.append(raw_line)
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("<!--"):
            out_lines.append(raw_line)
            in_comment = "-->" not in stripped
            continue
        if not stripped:
            if out_lines and out_lines[-1] != "":
                out_lines.append("")
            continue
        if stripped == "---":
            continue

        # Already-standard H1 (# EP001 ...)
        if stripped.startswith("# ") and not first_h1_seen:
            first_h1_seen = True
            h1_body = re.sub(r"^#\s+(?:EP\s*\d+|第\s*[0-9零一二三四五六七八九十百]+\s*集)?[·・:\s-]*", "", stripped, flags=re.I).strip()
            if h1_body and not ep_title:
                ep_title = h1_body
            continue

        # Already-standard Scene heading (## EP001-SC001 内 · 地点 · 时间)
        if STD_SCENE_RE.fullmatch(stripped):
            if current_sc == 0:
                pass
            current_sc += 1
            scenes_converted += 1
            if out_lines and out_lines[-1] != "":
                out_lines.append("")
            out_lines.append(stripped)
            out_lines.append("")
            continue

        # Alternative Scene heading
        matched_scene_body = None
        if not re.match(r"^(?:[^\s：:]{1,20})[：:]", stripped) or stripped.startswith(("#", "【")) or re.match(r"^\d+[-—.]\d+", stripped):
            for pat in ALT_SCENE_PATTERNS:
                m = pat.match(stripped)
                if m:
                    matched_scene_body = (m.group(1) if m.lastindex and m.group(1) else stripped).strip()
                    break
        if matched_scene_body is not None:
            current_sc += 1
            scenes_converted += 1
            sp, loc, tm = _parse_scene_meta(matched_scene_body, current_sc)
            if out_lines and out_lines[-1] != "":
                out_lines.append("")
            out_lines.append(f"## {ep_norm}-SC{current_sc:03d} {sp} · {loc} · {tm}")
            out_lines.append("")
            continue

        # Leading blockquote summary under `# EP001` stored as clean comment so screenplay_index sees 0 out-of-scene blocks
        if current_sc == 0 and stripped.startswith(">"):
            note_body = stripped.lstrip("> ").strip()
            out_lines.append(f"<!-- 集摘要: {note_body} -->")
            out_lines.append("")
            preserved_markdown += 1
            continue

        # Ensure at least one scene exists before body blocks
        if current_sc == 0:
            current_sc = 1
            scenes_converted += 1
            out_lines.append(f"## {ep_norm}-SC001 内 · 正片场次 · 日")
            out_lines.append("")

        # Sub-beats inside a scene (### 阶段一 · ... / ### 节拍二 · ...) -> clean [连续性] tag
        if stripped.startswith("#"):
            beat_txt = re.sub(r"^#{2,4}\s*", "", stripped).strip()
            if re.match(r"^(?:阶段|节拍|Part|Beat|Stage)[一二三四五六七八九十百0-9\s·:：-]", beat_txt, re.I):
                out_lines.append(f"[连续性] {beat_txt}")
                out_lines.append("")
                tags_converted += 1
                continue
            preserved_markdown += 1
            unmapped_lines.append({"line": lineno, "text": stripped[:80], "reason": "非场景子标题已注释保留"})
            out_lines.append(f"<!-- {stripped} -->")
            continue

        # Standalone parenthetical continuity/author note: （接上集） / （3-4集案例参考了...）
        m_paren_only = re.fullmatch(r"[（(]([^）)]+)[）)]", stripped)
        if m_paren_only:
            inner = m_paren_only.group(1).strip()
            if any(k in inner for k in ("接上", "承接", "闪回", "接第", "同场景")):
                out_lines.append(f"[连续性] {inner}")
                out_lines.append("")
                tags_converted += 1
            else:
                out_lines.append(f"<!-- {inner} -->")
                out_lines.append("")
                preserved_markdown += 1
            continue

        # Production bracket tags [VO]/[OS]/[SFX]/[画面文字]/[连续性]/[转场] or 【字幕：内容】
        m_prod = PROD_BRACKET_RE.match(stripped)
        if m_prod:
            raw_tag = m_prod.group(1).upper()
            body = (m_prod.group(2) or m_prod.group(3) or "").strip()
            tag_map = {"音效": "SFX", "画面文字": "画面文字", "字幕": "画面文字", "连续性": "连续性", "转场": "转场"}
            std_tag = tag_map.get(m_prod.group(1), raw_tag)
            if std_tag in ("VO", "OS"):
                body = _strip_outer_quotes(body)
            out_lines.append(f"[{std_tag}] {body}")
            out_lines.append("")
            tags_converted += 1
            continue

        m_sfx = SFX_PREFIX_RE.match(stripped)
        if m_sfx:
            pfx = stripped.split("：", 1)[0].split(":", 1)[0].strip()
            tag_map = {"音效": "SFX", "声效": "SFX", "SFX": "SFX", "画面文字": "画面文字", "字幕": "画面文字", "转场": "转场", "连续性": "连续性"}
            std_tag = tag_map.get(pfx.upper(), tag_map.get(pfx, "SFX"))
            out_lines.append(f"[{std_tag}] {m_sfx.group(1).strip()}")
            out_lines.append("")
            tags_converted += 1
            continue

        # Strip stage direction prefix △ / ▲ / *动作*, splitting trailing inline dialogues like "△动作。林川：台词。王某：台词"
        if stripped.startswith(("△", "▲", "▶")) and re.search(r"[。！？.!]\s*[\u4e00-\u9fffA-Za-z0-9]{1,8}(?:（[^）\n]{1,12}）)?[：:]", stripped):
            chunks = re.split(r"(?<=[。！？.!])\s*(?=[\u4e00-\u9fffA-Za-z0-9]{1,8}(?:（[^）\n]{1,12}）)?[：:])", re.sub(r"^[△▲▶•]\s*", "", stripped).strip())
            if len(chunks) > 1:
                out_lines.append(chunks[0].strip())
                out_lines.append("")
                actions_converted += 1
                for ch in chunks[1:]:
                    ch = ch.strip()
                    m_sub = PLAIN_SPEAKER_RE.match(ch)
                    if m_sub and not _is_non_dialogue_label(m_sub.group("speaker")):
                        spk = m_sub.group("speaker").strip()
                        cue = (m_sub.group("cue") or "").strip()
                        txt = _strip_outer_quotes(m_sub.group("text"))
                        out_lines.append(f"{spk}（{cue}）：{txt}" if cue else f"{spk}：{txt}")
                        out_lines.append("")
                        dialogues_converted += 1
                    elif ch:
                        out_lines.append(ch)
                        out_lines.append("")
                        actions_converted += 1
                continue
        clean_line = re.sub(r"^[△▲▶•]\s*", "", stripped).strip()

        # Inline voice tag: 角色（OS）：台词 / 角色（旁白）：台词
        m_vtag = VOICE_TAG_INLINE_RE.match(clean_line)
        if m_vtag:
            spk = m_vtag.group("speaker").strip()
            t_raw = m_vtag.group("tag").upper()
            std_tag = "VO" if t_raw in ("VO", "旁白") else "OS"
            txt = _strip_outer_quotes(m_vtag.group("text"))
            out_lines.append(f"[{std_tag}] {spk}：{txt}")
            out_lines.append("")
            tags_converted += 1
            dialogues_converted += 1
            continue

        # Bracket speaker: 【林川】(冷笑)：台词
        m_brk = BRACKET_SPEAKER_RE.match(clean_line)
        if m_brk and not _is_non_dialogue_label(m_brk.group("speaker")):
            spk = m_brk.group("speaker").strip()
            cue = (m_brk.group("cue") or "").strip()
            txt = _strip_outer_quotes(m_brk.group("text"))
            if spk == "旁白":
                out_lines.append(f"[VO] 旁白：{txt}")
                tags_converted += 1
            elif cue:
                out_lines.append(f"{spk}（{cue}）：{txt}")
            else:
                out_lines.append(f"{spk}：{txt}")
            out_lines.append("")
            dialogues_converted += 1
            continue

        # Bold speaker: **林川**：台词 or **林川：** 台词
        m_bold = BOLD_SPEAKER_RE.match(clean_line)
        if m_bold and not _is_non_dialogue_label(m_bold.group("speaker")):
            spk = m_bold.group("speaker").strip()
            cue = (m_bold.group("cue") or m_bold.group("cue2") or "").strip()
            txt = _strip_outer_quotes(m_bold.group("text"))
            if spk == "旁白":
                out_lines.append(f"[VO] 旁白：{txt}")
                tags_converted += 1
            elif cue:
                out_lines.append(f"{spk}（{cue}）：{txt}")
            else:
                out_lines.append(f"{spk}：{txt}")
            out_lines.append("")
            dialogues_converted += 1
            continue

        # Plain speaker: 角色（表演）：台词 (avoid turning long action narrative with colon into fake dialogue)
        m_pln = PLAIN_SPEAKER_RE.match(clean_line)
        if m_pln and not _is_non_dialogue_label(m_pln.group("speaker")) and not stripped.startswith(("△", "▲")):
            spk = m_pln.group("speaker").strip()
            cue = (m_pln.group("cue") or "").strip()
            txt = _strip_outer_quotes(m_pln.group("text"))
            if spk == "旁白":
                out_lines.append(f"[VO] 旁白：{txt}")
                tags_converted += 1
            elif cue:
                out_lines.append(f"{spk}（{cue}）：{txt}")
            else:
                out_lines.append(f"{spk}：{txt}")
            out_lines.append("")
            dialogues_converted += 1
            continue

        # Plain action / narrative paragraph (turn descriptive colon into em-dash so index never misreads narrative as speaker)
        safe_action = re.sub(r"^(\*\*[^*\r\n]{1,24}\*\*)\s*[：:]\s*", lambda m: m.group(1).strip("*") + "——", clean_line)
        if re.match(r"^[^：:\r\n]{1,40}[：:]", safe_action):
            safe_action = safe_action.replace("：", "——", 1)
        out_lines.append(safe_action)
        out_lines.append("")
        actions_converted += 1

    header = f"# {ep_norm} {ep_title}".strip()
    md = header + "\n\n" + "\n".join(out_lines).strip() + "\n"
    md = re.sub(r"\n{3,}", "\n\n", md)
    return {
        "episode_id": ep_norm,
        "title": ep_title,
        "markdown": md,
        "stats": {
            "scenes": scenes_converted,
            "dialogues": dialogues_converted,
            "tags": tags_converted,
            "actions": actions_converted,
            "preserved_comments": preserved_markdown,
            "unmapped": unmapped_lines,
        },
    }


def extract_preamble_and_episodes(text: str, default_ep: str = "EP001") -> tuple[str, list[tuple[str, str, str]]]:
    """提取第一集之前的前言/人物小传，并切分多集文本为 [(ep_id, ep_title, body_text), ...]。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    matches = list(EP_SPLIT_RE.finditer(text))
    if not matches:
        m_h1 = re.match(r"^\s*#\s+(.+)$", text, re.M)
        title = m_h1.group(1).strip() if m_h1 else ""
        return "", [(default_ep, title, text)]

    preamble = text[:matches[0].start()].strip()
    episodes: list[tuple[str, str, str]] = []
    for idx, m in enumerate(matches):
        num_str = m.group(1) or m.group(2) or m.group(3)
        if num_str.isdigit():
            ep_num = int(num_str)
        else:
            ep_num = ep_intake.chinese_to_int(num_str) or (idx + 1)
        ep_id = f"EP{ep_num:03d}"
        ep_title = (m.group(4) or m.group(5) or "").strip()
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        episodes.append((ep_id, ep_title, body))
    return preamble, episodes


def split_episodes_from_text(text: str, default_ep: str = "EP001") -> list[tuple[str, str, str]]:
    """切分多集文本为 [(ep_id, ep_title, body_text), ...]，单集整稿自动归为 default_ep。"""
    _, episodes = extract_preamble_and_episodes(text, default_ep=default_ep)
    return episodes


def run_intake(
    source_path: Path,
    project_dir: Path,
    *,
    apply: bool = False,
    default_ep: str = "EP001",
    auto_dashboard: bool = True,
) -> dict[str, Any]:
    raw_bytes, text, encoding = read_source_text(source_path)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    role = detect_document_role(text)
    if role != "screenplay":
        raise ValueError(f"拒绝导入：检测到源文件属于【{role}】（分镜/视频提示词），不是剧本！禁止写入 剧本.md。")
    preamble, raw_episodes = extract_preamble_and_episodes(text, default_ep=default_ep)
    normalized = [normalize_episode_markdown(ep_id, ep_title, body) for ep_id, ep_title, body in raw_episodes]

    # Run deterministic duration/index estimate in temp workspace so preview is accurate even in --dry-run
    estimates: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as td:
        for item in normalized:
            ep_id = item["episode_id"]
            tmp_script = Path(td) / f"{ep_id}.md"
            tmp_idx = Path(td) / f"{ep_id}.idx.jsonl"
            tmp_script.write_text(item["markdown"], encoding="utf-8")
            speakers = sorted({
                m.group(1).strip()
                for m in re.finditer(r"^(?:\[(?:VO|OS)\]\s+)?([^\s：:（）()\[\]#\n]{1,24})(?:（[^）\n]+）)?：", item["markdown"], re.M)
                if not m.group(1).startswith("[")
            })
            cmd_idx = [sys.executable, str(SD_CORE_DIR / "screenplay_index.py"), str(tmp_script), "--output", str(tmp_idx)]
            for spk in speakers:
                cmd_idx.extend(["--speaker", spk])
            subprocess.run(cmd_idx, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            if tmp_idx.is_file():
                cmd_est = [sys.executable, str(SD_CORE_DIR / "duration_estimate.py"), str(tmp_script), "--index", str(tmp_idx)]
                r_est = subprocess.run(cmd_est, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
                try:
                    estimates[ep_id] = json.loads(r_est.stdout)
                except Exception:
                    pass

    written_files: list[str] = []
    backup_file = None
    if apply:
        project_dir.mkdir(parents=True, exist_ok=True)
        in_dir = project_dir / "输入"
        in_dir.mkdir(parents=True, exist_ok=True)
        backup_target = in_dir / f"original-{source_path.name}"
        if backup_target.resolve() != source_path.resolve():
            backup_target.write_bytes(raw_bytes)
            backup_file = str(backup_target.relative_to(project_dir)).replace("\\", "/")
        else:
            backup_file = str(source_path.relative_to(project_dir)).replace("\\", "/")

        meta_file = in_dir / "intake-source-record.json"
        preamble_file = None
        if preamble:
            pre_path = in_dir / "人物小传-前言.md"
            pre_path.write_text(preamble + "\n", encoding="utf-8")
            preamble_file = str(pre_path.relative_to(project_dir)).replace("\\", "/")
        meta_file.write_text(json.dumps({
            "original_name": source_path.name,
            "encoding": encoding,
            "sha256": sha256,
            "preamble_file": preamble_file,
            "episodes": [n["episode_id"] for n in normalized],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        for item in normalized:
            ep_dir = project_dir / "剧集" / item["episode_id"]
            ep_dir.mkdir(parents=True, exist_ok=True)
            out_md = ep_dir / "剧本.md"
            out_md.write_text(item["markdown"], encoding="utf-8")
            written_files.append(str(out_md.relative_to(project_dir)).replace("\\", "/"))

        dashboard_url = None
        try:
            from whale_dashboard import ensure_project_registered, auto_start_dashboard
            ensure_project_registered(project_dir)
            if auto_dashboard:
                dashboard_url = auto_start_dashboard(project_dir, open_browser=True)
        except Exception:
            pass

    return {
        "ok": True,
        "mode": "apply" if apply else "dry_run",
        "source": source_path.name,
        "encoding": encoding,
        "sha256": sha256,
        "backup_file": backup_file,
        "dashboard_url": dashboard_url if apply else None,
        "has_preamble": bool(preamble),
        "preamble_lines": len(preamble.splitlines()) if preamble else 0,
        "episodes": [
            {
                "episode_id": item["episode_id"],
                "title": item["title"],
                "stats": item["stats"],
                "estimate": estimates.get(item["episode_id"], {}),
                "preview_head": "\n".join(item["markdown"].splitlines()[:18]),
            }
            for item in normalized
        ],
        "written_files": written_files,
    }



def normalize_workspace_scripts(project_dir: Path, *, apply: bool = False, auto_dashboard: bool = True) -> dict[str, Any]:
    """扫描项目 `剧集/*/剧本.md` 与根目录 `剧本.md`，对非规范剧本做「不改台词」结构统一并备份原稿。"""
    project_dir = project_dir.resolve()
    targets: list[tuple[str, Path]] = []
    ep_root = project_dir / "剧集"
    if ep_root.is_dir():
        for d in sorted(ep_root.iterdir()):
            if d.is_dir() and (d / "剧本.md").is_file():
                targets.append((d.name, d / "剧本.md"))
    if not targets and (project_dir / "剧本.md").is_file():
        targets.append(("EP001", project_dir / "剧本.md"))

    items = []
    for ep_id, sp in targets:
        raw_bytes, raw_text, enc = read_source_text(sp)
        role = detect_document_role(raw_text)
        if role != "screenplay":
            raise ValueError(f"拒绝规范化 {sp.name}：检测到内容实为【{role}】（分镜/提示词），请勿混入 剧本.md。")
        norm = normalize_episode_markdown(ep_id, "", raw_text)
        changed = norm["markdown"].strip() != raw_text.replace("\r\n", "\n").strip()
        if apply and changed:
            in_dir = project_dir / "输入"
            in_dir.mkdir(parents=True, exist_ok=True)
            bak = in_dir / f"backup-{ep_id}-剧本.md"
            if not bak.exists():
                bak.write_bytes(raw_bytes)
            sp.write_text(norm["markdown"], encoding="utf-8")
        items.append({
            "episode_id": norm["episode_id"],
            "file": str(sp.relative_to(project_dir)).replace("\\", "/"),
            "changed": changed,
            "stats": norm["stats"],
        })
    dashboard_url = None
    if apply and auto_dashboard:
        try:
            from whale_dashboard import ensure_project_registered, auto_start_dashboard
            ensure_project_registered(project_dir)
            dashboard_url = auto_start_dashboard(project_dir, open_browser=True)
        except Exception:
            pass
    return {"ok": True, "mode": "apply" if apply else "dry_run", "dashboard_url": dashboard_url, "files": items}


def main():
    ap = argparse.ArgumentParser(description="吞鲸宝典 · 非破坏性剧本导入与结构规范化引擎")
    ap.add_argument("source", nargs="?", default="", help="待导入的原始剧本路径（.md / .txt / .docx），或配合 --standardize-workspace 留空")
    ap.add_argument("--project", required=True, help="目标短剧项目根目录")
    ap.add_argument("--ep", default="EP001", help="单集未写集号时的默认集号（默认 EP001）")
    ap.add_argument("--standardize-workspace", action="store_true", help="对项目内现有非规范 剧本.md 做原件备份并统一结构")
    ap.add_argument("--apply", action="store_true", help="确认写入 剧集/<EP>/剧本.md 并备份原稿到 输入/；不加则仅预览不落盘")
    ap.add_argument("--no-dashboard", action="store_true", help="落盘后不自动拉起本地工作台")
    args = ap.parse_args()

    auto_dash = not args.no_dashboard
    if args.standardize_workspace:
        res = normalize_workspace_scripts(Path(args.project).resolve(), apply=args.apply, auto_dashboard=auto_dash)
    else:
        if not args.source:
            ap.error("请提供待导入的原始剧本路径，或使用 --standardize-workspace")
        res = run_intake(Path(args.source).resolve(), Path(args.project).resolve(), apply=args.apply, default_ep=args.ep, auto_dashboard=auto_dash)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
