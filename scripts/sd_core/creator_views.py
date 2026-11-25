#!/usr/bin/env python3
"""Read an episode's creator documents into the structures the dashboard shows.

The dashboard never parses Markdown in the browser. Everything here reads the
same documents the checker reads, with the checker's own patterns wherever one
exists, so the dashboard and ``creator_markdown_check.py`` cannot disagree
about what a shot, a reference slot or a continuity lock is.

Two documents belong to other stages: the screenplay grammar is owned by the
write stage's index builder and the cut list by the edit tool. Skills install
one at a time, so this module does not import them; it keeps a minimal reader
of each and ``tests/test_dashboard_server.py`` holds both to the canonical
parser on the same inputs.

Every reader is tolerant: a section it cannot read comes back as ``None`` with
one sentence the creator can act on, and the view falls back to the raw text.
Nothing here reads files; the server hands in text it read safely.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Optional


MINIMUM_PYTHON = (3, 9)
if sys.version_info < MINIMUM_PYTHON:
    raise SystemExit(
        "short-drama needs Python {}.{} or newer; this interpreter is {}.{}".format(
            *MINIMUM_PYTHON, sys.version_info.major, sys.version_info.minor
        )
    )


def _load_checker() -> ModuleType:
    path = Path(__file__).resolve().with_name("creator_markdown_check.py")
    spec = importlib.util.spec_from_file_location("creator_views_checker", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the creator document checker: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load_checker()

SCREENPLAY = "剧本.md"
SETTINGS = "视觉设定.md"
STORYBOARD = "分镜.md"
IMAGE_PROMPTS = "图片提示词.md"
VIDEO_PROMPTS = "视频提示词.md"
CUT_LIST = "剪辑单.md"
CREATOR_DOCUMENTS = (SCREENPLAY, SETTINGS, STORYBOARD, IMAGE_PROMPTS, VIDEO_PROMPTS)
# Where the edit stage writes the finished film, relative to the episode.
FILM = "制作成果/成片/成片.mp4"

# ------------------------------------------------------------------ shot size

# Ordered far to close. 中近景 is its own rung between 中景 and 近景.
SCALES = ("远景", "全景", "中景", "中近景", "近景", "特写", "大特写", "细节")
# The rhythm profile's close_shot_share_min counts exactly these (develop's
# episode-design reference): 近景、特写、大特写与细节镜头. 中近景 is not one.
CLOSE_SCALES = frozenset({"近景", "特写", "大特写", "细节"})
_SCALE_RE = re.compile("大特写|中近景|远景|全景|中景|近景|特写|细节")


def shot_scale(framing: str) -> str:
    """The first shot-size word in a 景别/机位 value, or "" when none is named.

    Longer words are tried first at each position, so 中近景 and 大特写 are read
    whole instead of as the 近景 or 特写 inside them.
    """

    match = _SCALE_RE.search(framing or "")
    return match.group(0) if match else ""


# ------------------------------------------------------------------ screenplay

# The write stage's grammar (screenplay_index.py): one scene heading per scene,
# one paragraph per block, production tags in half-width brackets.
_EPISODE = r"EP(?:[0-9]{3}|[1-9][0-9]{3,})"
# The same spelling project_tool.py's EPISODE_ID_RE enforces on 剧集/<EP>/.
EPISODE_ID_RE = re.compile(_EPISODE)
TITLE_RE = re.compile(r"^# (?:" + _EPISODE + r")?\s*(?:·\s*)?(.*)$")
SCENE_RE = re.compile(
    r"^## (?P<scene>" + _EPISODE + r"-SC[0-9]{3}) "
    r"(?P<space>内外|内|外) · (?P<location>\S(?:.*\S)?) · (?P<time>\S(?:.*\S)?)$"
)
TAG_RE = re.compile(r"^\[(?P<tag>VO|OS|SFX|画面文字|连续性|转场)\]\s*(?P<body>\S[\s\S]*)$")
VOICE_BODY_RE = re.compile(r"^(?P<speaker>[^\s：（）:\[\]#]{1,40})：(?P<text>\S[\s\S]*)$")
DIALOGUE_RE = re.compile(
    r"^(?:\*\*)?(?P<speaker>[^：（）:\[\]#*\r\n，。！？；、.!?,]{1,18}?)"
    r"(?:（(?P<cue>[^（）\r\n]+)）)?(?:：\*\*|\*\*：|：)\s*(?P<text>\S[\s\S]*)$"
)


_NON_SPEAKER_SUFFIXES = ("近景", "特写", "远景", "全景", "中景", "结尾", "几步", "底线", "阶段", "节拍")


def _looks_like_speaker(speaker: str) -> bool:
    s = re.sub(r"^\*+|\*+$", "", (speaker or "").strip()).strip()
    if not s or any(s.endswith(sfx) for sfx in _NON_SPEAKER_SUFFIXES):
        return False
    return len(s) <= 16


def _clean_speaker_and_tag(raw_speaker: str, default_tag: str = "") -> tuple[str, str]:
    spk = re.sub(r"^\*+|\*+$", "", (raw_speaker or "").strip()).strip()
    tag = default_tag
    m_v = re.fullmatch(r"(.+?)\s+(VO|OS|旁白|画外音)", spk, re.I)
    if m_v:
        spk = m_v.group(1).strip()
        raw_t = m_v.group(2).upper()
        tag = "VO" if raw_t in ("VO", "旁白") else "OS"
    return spk, tag


def _unwrap_dialogue_display(raw_text: str) -> str:
    s = (raw_text or "").strip()
    if len(s) >= 2 and s[0] == "`" and s[-1] == "`":
        s = s[1:-1].strip()
    m_d = re.fullmatch(r"<d>\s*(?:\[[A-Za-z_ -]+\]\s*)?([\s\S]*?)\s*</d>", s, re.I)
    if m_d:
        s = m_d.group(1).strip()
    return s
VOICED_TAGS = frozenset({"VO", "OS"})


def spoken_characters(line: str) -> int:
    """What is voiced: no whitespace, no bracketed direction (duration_estimate.py)."""

    stripped = re.sub(r"（[^）]*）|\([^)]*\)", "", line)
    return len(re.sub(r"\s", "", stripped))


def _paragraphs(text: str) -> list[str]:
    """Blank-line separated blocks, headings on their own, comments dropped."""

    blocks: list[str] = []
    current: list[str] = []
    in_comment = False
    for raw in text.splitlines():
        line = raw.strip()
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if line.startswith("<!--"):
            if current:
                blocks.append("\n".join(current))
                current = []
            in_comment = "-->" not in line
            continue
        if not line or line.startswith("#"):
            if current:
                blocks.append("\n".join(current))
                current = []
            if line:
                blocks.append(line)
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def parse_screenplay(text: str) -> dict[str, Any]:
    """Scenes with their action, dialogue and production-tag blocks, in order."""

    title = ""
    scenes: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    for paragraph in _paragraphs(text):
        if paragraph.startswith("## "):
            match = SCENE_RE.fullmatch(paragraph)
            current = None
            if match:
                current = {
                    "id": match.group("scene"),
                    "space": match.group("space"),
                    "place": match.group("location"),
                    "time": match.group("time"),
                    "blocks": [],
                }
                scenes.append(current)
            continue
        if paragraph.startswith("# "):
            found = TITLE_RE.match(paragraph)
            title = (found.group(1) if found else paragraph[2:]).strip()
            continue
        if paragraph.startswith("#") or current is None:
            continue
        tag = TAG_RE.fullmatch(paragraph)
        if tag:
            body = tag.group("body").strip()
            voice = VOICE_BODY_RE.fullmatch(body) if tag.group("tag") in VOICED_TAGS else None
            if voice:
                current["blocks"].append({
                    "k": "line", "tag": tag.group("tag"), "who": voice.group("speaker"),
                    "paren": "", "text": voice.group("text").strip(),
                })
            else:
                current["blocks"].append({"k": "tag", "tag": tag.group("tag"), "text": body})
            continue
        dialogue = DIALOGUE_RE.fullmatch(paragraph)
        if dialogue and _looks_like_speaker(dialogue.group("speaker")):
            who_c, tag_c = _clean_speaker_and_tag(dialogue.group("speaker"))
            current["blocks"].append({
                "k": "line", "tag": tag_c, "who": who_c,
                "paren": dialogue.group("cue") or "", "text": _unwrap_dialogue_display(dialogue.group("text")),
            })
            continue
        current["blocks"].append({"k": "action", "text": paragraph})
    if not scenes:
        # 兼容吞鲸传统剧本格式：### 场景一：...（夜） 或 ## 场次 A
        alt_scene_re = re.compile(r"^(?:#{2,3}\s+)?(?:场景[^：:\s]*[：:]\s*)?((?:EP\d+-SC\d+|SC\d+).+|.+)$")
        cur_alt = None
        sc_idx = 0
        for paragraph in _paragraphs(text):
            if paragraph.startswith("### ") and cur_alt is not None:
                beat_lbl = re.sub(r"^#{2,4}\s*", "", paragraph).strip()
                if re.match(r"^(?:阶段|节拍|Part|Beat|Stage)", beat_lbl, re.I):
                    cur_alt["blocks"].append({"k": "tag", "tag": "连续性", "text": beat_lbl})
                    continue
            if paragraph.startswith("## ") or paragraph.startswith("### ") or re.match(r"^(?:EP\d+-)?SC\d+\b", paragraph):
                if any(k in paragraph for k in ("场景", "场次", "SC", "序幕", "尾声", "终章", "第", "幕")) and "剧本正文" not in paragraph and "核心人物" not in paragraph:
                    sc_idx += 1
                    m_loc = alt_scene_re.match(paragraph)
                    raw_loc = (m_loc.group(1) if m_loc else paragraph).strip()
                    sc_m = re.match(r"^(?:EP\d+-)?(SC\d+)[·・\s]+(.+)$", raw_loc)
                    sc_key = sc_m.group(1) if sc_m else f"SC{sc_idx:03d}"
                    body_loc = sc_m.group(2).strip() if sc_m else raw_loc
                    parts = [pt.strip() for pt in re.split(r"[·・]", body_loc) if pt.strip()]
                    if len(parts) >= 3 and parts[0] in {"内", "外", "内外"}:
                        sp_val, loc, tm = parts[0], parts[1], parts[2]
                    else:
                        sp_val = "内"
                        t_m = re.search(r"[（(]([^）)]+)[）)]\s*$", body_loc)
                        tm = t_m.group(1) if t_m else "日"
                        loc = re.sub(r"[（(][^）)]+[）)]\s*$", "", body_loc).strip()
                    cur_alt = {"id": sc_key, "space": sp_val, "place": loc or f"场{sc_idx}", "time": tm, "blocks": []}
                    scenes.append(cur_alt)
                    continue
            if cur_alt is not None and not paragraph.startswith("#") and paragraph != "---":
                cleaned = re.sub(r"^[△▲]\s*", "", paragraph).strip()
                if cleaned.startswith("**出场资产**"):
                    continue
                d_m = DIALOGUE_RE.match(cleaned)
                if d_m and _looks_like_speaker(d_m.group("speaker")):
                    who_c, tag_c = _clean_speaker_and_tag(d_m.group("speaker"))
                    cur_alt["blocks"].append({
                        "k": "line", "tag": tag_c, "who": who_c,
                        "paren": (d_m.group("cue") or "").strip(), "text": _unwrap_dialogue_display(d_m.group("text")),
                    })
                elif cleaned:
                    cur_alt["blocks"].append({"k": "action", "text": cleaned})
    if not scenes:
        if len(re.findall(r"^#{1,4}\s+\[?(?:SHOT|MOTION)-|^SHOT-\d+\b", text, re.M)) >= 2:
            raise ValueError("当前 剧本.md 内混入了分镜条目 (SHOT-xx) 而非场次剧本，请把分镜放入 分镜.md")
        # 执行稿剧本终极兜底（保留真实对话/动作，不再报空）
        fallback_blocks = []
        for paragraph in _paragraphs(text):
            if paragraph.startswith("#") or paragraph == "---":
                continue
            cleaned = re.sub(r"^[△▲]\s*", "", paragraph).strip()
            if not cleaned:
                continue
            d_m = DIALOGUE_RE.match(cleaned)
            if d_m and _looks_like_speaker(d_m.group("speaker")):
                who_c, tag_c = _clean_speaker_and_tag(d_m.group("speaker"))
                fallback_blocks.append({
                    "k": "line", "tag": tag_c, "who": who_c,
                    "paren": (d_m.group("cue") or "").strip(), "text": _unwrap_dialogue_display(d_m.group("text")),
                })
            else:
                fallback_blocks.append({"k": "action", "text": cleaned})
        if fallback_blocks:
            scenes.append({"id": "SC001", "space": "内", "place": "正片执行稿", "time": "日", "blocks": fallback_blocks})
    if not scenes:
        raise ValueError("没有找到 `## EP001-SC001 内 · 地点 · 时间` 这样的场次标题")
    return {"title": title, "scenes": scenes}


def voice_share(script: dict[str, Any]) -> dict[str, int]:
    """Spoken characters overall and in [VO]; [OS] is dialogue, not voice-over."""

    spoken = voiced = 0
    for scene in script["scenes"]:
        for block in scene["blocks"]:
            if block["k"] != "line":
                continue
            count = spoken_characters(block["text"])
            spoken += count
            if block["tag"] == "VO":
                voiced += count
    return {"spoken": spoken, "vo": voiced}


# ------------------------------------------------------------------ visual settings

FIELD_RE = re.compile(r"^- ([^：\n]+)：(.+)$", re.MULTILINE)
LOCK_HEAD_RE = re.compile(r"连续性锁：(LOCK-[A-Z0-9-]+)《([^》]+)》")
OVERLAY_ONLY_RE = re.compile(r"只在后期叠加")


def parse_settings(text: str) -> dict[str, Any]:
    errors: list[str] = []
    entries = {(entry.category, entry.name): entry for entry in check._visual_entries(text, errors)}
    locks = {lock.lock_id: lock for lock in check._continuity_locks(text, errors)}
    heads = list(check.VISUAL_SETTING_HEADING_RE.finditer(text))
    preamble = text[: heads[0].start()] if heads else text
    meta = dict(FIELD_RE.findall(preamble))
    era_parts = [part.strip() for part in meta.get("时代锚点", "").split("；") if part.strip()]
    facets: list[dict[str, str]] = []
    for part in era_parts[1:]:
        key, _, value = part.partition("：")
        facets.append({"k": key.strip(), "v": value.strip().rstrip("。")})
    era = {"period": era_parts[0] if era_parts else "", "facets": facets}
    items = []
    for index, head in enumerate(heads):
        body = text[head.end(): heads[index + 1].start() if index + 1 < len(heads) else None]
        category, name = head.group(1), head.group(2).strip()
        entry = entries.get((category, name))
        fields = {key.strip(): value.strip() for key, value in FIELD_RE.findall(body)}
        loose = [
            line[2:].strip()
            for line in body.splitlines()
            if line.startswith("- ") and not FIELD_RE.match(line)
        ]
        lock = None
        named = LOCK_HEAD_RE.search(body)
        if named and named.group(1) in locks:
            found = locks[named.group(1)]
            lock = {
                "id": found.lock_id, "name": named.group(2), "surface": found.surface,
                "shots": list(found.shots), "images": list(found.images),
            }
        designators = list(entry.designators) if entry else []
        items.append({
            "cat": category,
            "name": name,
            "designators": [item for item in designators if item != name],
            "desc": loose,
            "fields": {k: v for k, v in fields.items() if k not in ("连续性锁", "画面代称")},
            "lock": lock,
            "overlay": bool(OVERLAY_ONLY_RE.search(body)),
        })
    if not items:
        cur_cat = "人物"
        for ln in text.splitlines():
            s_ln = ln.strip()
            if s_ln.startswith("#"):
                if "场景" in s_ln:
                    cur_cat = "场景"
                elif "道具" in s_ln or "物" in s_ln:
                    cur_cat = "道具"
                elif "角色" in s_ln or "人物" in s_ln:
                    cur_cat = "人物"
                continue
            if s_ln.startswith("|") and s_ln.endswith("|"):
                cols = [c.strip() for c in s_ln.strip("|").split("|")]
                if len(cols) >= 4 and not cols[0].startswith(":") and cols[0] not in ("角色代码", "场景代码", "道具代码", "名称"):
                    nm = re.sub(r"\*\*", "", cols[0]).strip()
                    img_f = re.sub(r"`", "", cols[1]).strip()
                    spec = cols[2]
                    desc_txt = cols[3]
                    items.append({
                        "cat": cur_cat,
                        "name": nm,
                        "designators": [],
                        "desc": [desc_txt] if desc_txt else [],
                        "fields": {"资产文件": img_f, "规格": spec},
                        "lock": None,
                        "overlay": False,
                    })
    if not items:
        raise ValueError("没有找到 `## 人物 · 名称` 这样的设定条目")
    return {"form": meta.get("制作形态", "").rstrip("。"), "era": era, "items": items}


# ------------------------------------------------------------------ storyboard

SHOT_TITLE_RE = re.compile(r"^## \S+ · (.+)$", re.MULTILINE)
NOTE_RE = re.compile(r"^> (.+)$", re.MULTILINE)
REF_STATES = {
    "t2v": "文生视频（创作者已选择不用图）",
    "pending": "待补参考图",
    "bound": "已写参考图",
    "none": "未写参考图",
}


def _number(identifier: str) -> str:
    found = re.search(r"(\d+)$", identifier)
    return found.group(1) if found else identifier


def _slots(value: str) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for match in check.REF_RE.finditer(value):
        slots.append({
            "kind": "REF", "id": match.group(1), "order": int(match.group(2)),
            "path": match.group(3), "name": match.group(4), "use": (match.group(5) or "").strip(),
        })
    for match in check.PLAN_RE.finditer(value):
        slots.append({
            "kind": "PLAN", "id": match.group(1), "order": int(match.group(2)),
            "target": match.group(3), "name": match.group(4), "use": (match.group(5) or "").strip(),
        })
    return sorted(slots, key=lambda slot: slot["order"])


def _ref_state(value: str, slots: list[dict[str, Any]]) -> str:
    if check._is_explicit_text_to_video(value):
        return "t2v"
    if check._has_pending_references(value):
        return "pending"
    return "bound" if slots else "none"


def parse_storyboard(text: str) -> dict[str, Any]:
    head = text.split("\n## ", 1)[0]
    note = NOTE_RE.search(head)
    shots = []
    for shot_id, section in check._sections(text, "SHOT").items():
        fields = check._fields(section, owner=shot_id, errors=[])
        title = SHOT_TITLE_RE.search(section)
        framing = fields.get("景别/机位", "")
        move = fields.get("运镜", "")
        scale = shot_scale(framing)
        reference = fields.get("输入参考图", "")
        slots = _slots(reference)
        scene = check.SCENE_ID_RE.search(fields.get("来源", ""))
        basis_text = fields.get("视觉依据", "").split(check.OFFSCREEN_PREFIX)[0]
        seconds = check._declared_seconds(fields.get("时长", ""))
        shots.append({
            "id": shot_id,
            "n": _number(shot_id),
            "title": title.group(1).strip() if title else "",
            "scene": scene.group(0) if scene else "",
            "sec": seconds if seconds is not None else 0,
            "secDeclared": seconds is not None,
            "purpose": fields.get("目的", ""),
            "framing": framing,
            "scale": scale,
            "close": scale in CLOSE_SCALES,
            "move": move,
            "moveKind": re.split(r"[；;，,]", move)[0].strip(),
            "start": fields.get("起点", ""),
            "action": fields.get("唯一动作", ""),
            "end": fields.get("终点", ""),
            "sound": fields.get("声音", ""),
            "screenText": fields.get("画面文字", ""),
            "imgs": [
                {"id": ident, "name": name, "ctl": control}
                for ident, name, control in check.IMG_RE.findall(fields.get("图片提示词项", ""))
            ],
            "refs": slots,
            "refState": _ref_state(reference, slots),
            "refLabel": REF_STATES[_ref_state(reference, slots)],
            "basis": [
                {"cat": category, "name": name, "ctl": control}
                for category, name, control in check.VISUAL_BASIS_ENTRY_RE.findall(basis_text)
            ],
            "keyframe": check._copyable_prompt(section, "冻结关键帧提示词") or "",
        })
    if not shots:
        def _infer_scale(fr: str) -> str:
            sc = shot_scale(fr)
            if sc:
                return sc
            for code, zh_sc in {"wide": "远景", "mcu": "中近景", "cu": "近景", "macro": "大特写", "hip": "特写", "face": "特写"}.items():
                if re.search(rf"\b{code}\b", fr, re.I):
                    return zh_sc
            if any(k in fr for k in ("极远景", "大远景", "大全景", "超广角", "定调", "大景")):
                return "远景"
            if any(k in fr for k in ("极近", "微距")):
                return "大特写"
            if "中特写" in fr:
                return "近景"
            if any(k in fr for k in ("局部", "手部", "脚部", "道具")):
                return "细节"
            if any(k in fr for k in ("全身", "广角", "门", "空间", "跟拍", "群像")):
                return "全景"
            if any(k in fr for k in ("半身", "过肩", "正面", "侧面", "仰拍", "俯拍", "反打", "双人")):
                return "中景"
            return "中景"

        # 兼容1：### SHOT-01 / #### [SHOT-EP001-001] 标题 / #### SHOT-EP002-001｜标题
        alt_head_re = re.compile(r"^(?:#{2,4}\s+)?\[?((?:SHOT|R\d+)-[A-Za-z0-9-]+|SHOT-\d+)\]?[·・｜|\s]*(.*)$", re.MULTILINE)
        alt_matches = list(alt_head_re.finditer(text))
        sc_marks = []
        act_idx = 0
        for sm in re.finditer(r"^(?:#{2,4}\s+)?((?:EP\d+-)?SC\d+)\b|^#{2,4}\s+(第[一二三四五六七八九十百0-9]+[幕场]\s*[^\r\n]*)", text, re.MULTILINE):
            if sm.group(1):
                sc_marks.append((sm.start(), sm.group(1)))
            else:
                act_idx += 1
                sc_marks.append((sm.start(), f"SC{act_idx:03d}"))
        for idx, m in enumerate(alt_matches):
            sid = m.group(1)
            sec = text[m.start(): alt_matches[idx + 1].start() if idx + 1 < len(alt_matches) else None]
            nearest_sc = next((sc_id for pos, sc_id in reversed(sc_marks) if pos < m.start()), "SC001")
            raw_title = re.sub(r"^\[Track:[^\]]+\]\s*|^[·｜|\s]+", "", m.group(2)).strip()
            kv = {}
            for ln in sec.splitlines()[1:]:
                fm = re.match(r"^(?:[-*]\s*)?(?:\*\*)?([^：:*|\s][^：:*]{0,18}?)(?:\*\*)?[：:]\s*(.*)$", ln.strip())
                if fm:
                    kv[fm.group(1).strip()] = fm.group(2).strip()
            framing_raw = kv.get("景别/机位") or kv.get("景别/运镜") or kv.get("景别 / 运镜") or kv.get("景别 / 机位") or kv.get("景别机位") or " / ".join(x for x in [kv.get("景别", ""), kv.get("机位", "")] if x) or m.group(2).strip()
            scale = _infer_scale(framing_raw)
            dur_txt = kv.get("物理时长") or kv.get("时长") or m.group(2) + "\n" + sec
            dm = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:秒|s\b)", dur_txt, re.I)
            sec_val = float(dm.group(1)) if dm else 4.0
            move = (
                kv.get("运镜")
                or (re.search(r"运镜[：:]\s*(.+)$", framing_raw).group(1).strip() if "运镜" in framing_raw else "")
                or (framing_raw.split("➔", 1)[1].strip() if "➔" in framing_raw else "")
                or (re.sub(r"`", "", framing_raw.split("/", 1)[1]).strip() if "/" in framing_raw else "")
            )
            action = kv.get("动作") or kv.get("唯一动作") or kv.get("画面") or kv.get("画面动线与构图") or kv.get("姿势") or ""
            speech_txt = kv.get("台词") or kv.get("OS") or kv.get("VO") or kv.get("发声") or ""
            sfx_txt = kv.get("声音设计") or kv.get("声音反馈") or kv.get("声音") or ""
            sound = "｜".join(x for x in [speech_txt, sfx_txt] if x and x not in {"无", "无对白", "无对白。"}) or sfx_txt or speech_txt
            ref_files = re.findall(r"([^\s`'\"“”‘’\[\](),，;；<>]+\.(?:png|jpg|jpeg|webp))", sec, re.I)
            slots = [{"kind": "REF", "id": f"REF-{si+1:02d}", "order": si + 1, "path": rf, "name": Path(rf).name, "use": "参考"} for si, rf in enumerate(ref_files[:9])]
            ref_st = "bound" if slots else "none"
            shots.append({
                "id": sid, "n": idx + 1, "title": raw_title or action[:24] or sid,
                "scene": kv.get("来源") or nearest_sc, "sec": sec_val, "secDeclared": dm is not None,
                "purpose": kv.get("目的") or kv.get("体位") or kv.get("姿势") or "承接本镜叙事动作",
                "framing": framing_raw, "scale": scale, "close": scale in CLOSE_SCALES,
                "move": move or "静态锁定", "moveKind": re.split(r"[；;，,➔]", move or "静态锁定")[0].strip(),
                "start": kv.get("起点") or kv.get("画面") or "", "action": action, "end": kv.get("终点") or kv.get("结束状态") or kv.get("终点与承接") or "",
                "sound": sound, "screenText": kv.get("画面文字") or "",
                "imgs": [], "refs": slots, "refState": ref_st, "refLabel": REF_STATES[ref_st],
                "basis": [], "keyframe": "",
            })

        # 兼容2：Markdown 表格分镜 (| **001** | 大全景·缓俯移 | 画面动作 | 台词 | 6.0s / 141f | ref... |)
        if not shots:
            cur_scene = "SC001"
            sc_i = 0
            for ln in text.splitlines():
                s_ln = ln.strip()
                if s_ln.startswith("## ") and any(k in s_ln for k in ("幕", "场", "阶段")):
                    sc_i += 1
                    cur_scene = f"SC{sc_i:03d}"
                    continue
                if s_ln.startswith("|") and s_ln.endswith("|"):
                    cols = [c.strip() for c in s_ln.strip("|").split("|")]
                    if len(cols) >= 5 and re.fullmatch(r"(?:\*\*)?\d{2,4}[A-Za-z]?(?:\*\*)?", cols[0]):
                        num = re.sub(r"\*", "", cols[0]).strip()
                        sid = f"SHOT-{num}"
                        framing_raw = cols[1]
                        action = re.sub(r"\*\*", "", cols[2]).strip()
                        sound = cols[3]
                        dm = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:秒|s\b)", cols[4], re.I)
                        sec_val = float(dm.group(1)) if dm else 4.0
                        ref_col = cols[5] if len(cols) > 5 else ""
                        ref_tokens = re.findall(r"`ref_image_\d+`[：:]\s*([A-Za-z0-9_.-]+)", ref_col)
                        if not ref_tokens:
                            ref_tokens = re.findall(r"([A-Za-z0-9_.-]+\.(?:png|jpg|jpeg|webp))", ref_col, re.I)
                        slots = [{"kind": "REF", "id": f"REF-{si+1:02d}", "order": si + 1, "path": rf, "name": Path(rf).name, "use": "参考"} for si, rf in enumerate(ref_tokens[:9])]
                        ref_st = "bound" if slots else "none"
                        scale = _infer_scale(framing_raw)
                        move = framing_raw.split("·", 1)[1].strip() if "·" in framing_raw else "静态锁定"
                        shots.append({
                            "id": sid, "n": len(shots) + 1, "title": action[:28] or sid,
                            "scene": cur_scene, "sec": sec_val, "secDeclared": dm is not None,
                            "purpose": "表格分镜映射", "framing": framing_raw, "scale": scale,
                            "close": scale in CLOSE_SCALES, "move": move, "moveKind": move,
                            "start": "", "action": action, "end": "", "sound": sound, "screenText": "",
                            "imgs": [], "refs": slots, "refState": ref_st, "refLabel": REF_STATES[ref_st],
                            "basis": [], "keyframe": "",
                        })
    if not shots:
        raise ValueError("没有找到 `## SHOT-EP001-001 · 标题` 这样的镜头")
    return {"note": note.group(1).strip() if note else "", "shots": shots}


def start_frame(shot: dict[str, Any]) -> Optional[str]:
    """The one picture a shot binds as its first frame, if any."""

    for slot in shot["refs"]:
        if slot["kind"] == "REF" and slot["use"] == "起始帧":
            return str(slot["path"])
    return None


# ------------------------------------------------------------------ prompts

IMG_HEADING_RE = re.compile(r"^## (IMG-[A-Z0-9-]+) · (.+)$", re.MULTILINE)


def parse_image_prompts(text: str) -> list[dict[str, Any]]:
    parts = list(IMG_HEADING_RE.finditer(text))
    prompts = []
    for index, match in enumerate(parts):
        section = text[match.start(): parts[index + 1].start() if index + 1 < len(parts) else None]
        fields = check._fields(section, owner=match.group(1), errors=[])
        prompts.append({
            "id": match.group(1), "title": match.group(2).strip(),
            "use": fields.get("用途", ""), "ref": fields.get("参考", ""),
            "prompt": check._copyable_prompt(section) or "",
        })
    if not prompts:
        raise ValueError("没有找到 `## IMG-… · 标题` 这样的图片提示词条目")
    return prompts


def parse_video_prompts(text: str) -> list[dict[str, Any]]:
    prompts = []
    for motion_id, section in check._sections(text, "MOTION").items():
        fields = check._fields(section, owner=motion_id, errors=[])
        title = SHOT_TITLE_RE.search(section)
        shot = re.search(r"SHOT-[A-Z0-9-]+", fields.get("分镜", ""))
        prompts.append({
            "id": motion_id,
            "n": _number(motion_id),
            "title": title.group(1).strip() if title else "",
            "shot": shot.group(0) if shot else "",
            "sec": check._declared_seconds(fields.get("时长", "")) or 0,
            "mode": fields.get("生成方式", ""),
            "chain": fields.get("状态链", ""),
            "prompt": check._copyable_prompt(section) or "",
        })
    if not prompts:
        alt_vp_re = re.compile(r"^#{2,4}\s+\[?((?:MOTION|SHOT|R\d+)-[A-Za-z0-9-]+|SHOT-\d+)\]?\s*(.*)$", re.MULTILINE)
        alt_matches = list(alt_vp_re.finditer(text))
        for idx, m in enumerate(alt_matches):
            mid = m.group(1)
            sec = text[m.start(): alt_matches[idx + 1].start() if idx + 1 < len(alt_matches) else None]
            code_m = re.search(r"```(?:text|prompt)?\s*\n([\s\S]*?)\n```", sec)
            if not code_m:
                continue
            dm = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:秒|s\b)", m.group(2) + " " + sec[:200], re.I)
            prompts.append({
                "id": mid,
                "n": idx + 1,
                "title": re.sub(r"^\([^)]*\)|^[·\s]+", "", m.group(2)).strip() or mid,
                "shot": mid if mid.startswith("SHOT-") else f"SHOT-{idx+1:02d}",
                "sec": float(dm.group(1)) if dm else 0,
                "mode": "Ref2V",
                "chain": "",
                "prompt": code_m.group(1).strip(),
            })
    if not prompts:
        raise ValueError("没有找到 `## MOTION-… · 标题` 这样的视频提示词条目")
    return prompts


# ------------------------------------------------------------------ cut list

# The edit stage's grammar (short-drama-edit/scripts/edit_tool.py). Only reading:
# the edit tool is the one that refuses a malformed cut list.
CUT_HEADING_RE = re.compile(r"^##\s+(CUT-[^\s·]+)\s*(?:·\s*(.*))?$")
CUT_FIELD_RE = re.compile(r"^-\s*([^：]+)：\s*(.*)$")
SOURCE_RE = re.compile(r"^((?:MOTION|SHOT|IMG)-\S+)\s*·\s*(.+?)\s*$")
MOVE_RE = re.compile(r"^(推近|拉远|左移|右移|上移|下移)\s*([0-9]+)\s*[%％]$")
MOVE_RATE_RE = re.compile(r"^(推近|拉远|左移|右移|上移|下移)\s*([0-9]+(?:\.[0-9]+)?)\s*[%％]\s*[/／]\s*秒$")
BED_RE = re.compile(r"^\s*(?:(-?[0-9]+(?:\.[0-9]+)?)\s+)?(.+?)\s*$")
VOICE_RE = re.compile(r"^\s*(-?[0-9]+(?:\.[0-9]+)?)\s+(.+?)\s*$")
WINDOW_RE = re.compile(r"^\s*([0-9.]+)\s*[-–~]\s*([0-9.]+)\s*$")
CUE_RE = re.compile(r"^\s*([0-9.]+)\s*[-–~]\s*([0-9.]+)\s+(.+?)\s*$")
KEYWORDS_RE = re.compile(r"[（(]重点[：:]\s*(.+?)\s*[）)]\s*$")
SCREEN_TEXT_STYLES = ("卡片", "系统面板", "任务面板", "角标")
SCREEN_TEXT_RE = re.compile(
    r"^\s*([0-9.]+)\s*[-–~]\s*([0-9.]+)\s+(" + "|".join(SCREEN_TEXT_STYLES) + r")\s+(.+?)\s*$"
)
COUNTDOWN_RE = re.compile(r"[（(]倒计时[：:]\s*([0-9]+(?:\.[0-9]+)?|接续)\s*[）)]\s*$")
RARITY_RE = re.compile(r"[（(](传说|史诗|稀有)[）)]$")
OPTIONS_RE = re.compile(r"[（(]\s*((?:起点|增益)[：:][^（）()]*)[）)]\s*$")
OPTION_RE = re.compile(r"^(起点|增益)[：:]\s*([+-]?[0-9]+(?:\.[0-9]+)?)\s*(?:dB)?$", re.I)
NUMBERED_RE = {
    "字幕": re.compile(r"^字幕(?:\s*(\d+))?$"),
    "画面文字": re.compile(r"^画面文字(?:\s*(\d+))?$"),
    "音效": re.compile(r"^音效(?:\s*(\d+))?$"),
    "配音": re.compile(r"^配音(?:\s*(\d+))?$"),
}


def _delivery(lines: list[str]) -> dict[str, Any]:
    delivery: dict[str, Any] = {"target": None, "lufs": None, "burn": True, "frame": None, "fps": None}
    for raw in lines:
        match = CUT_FIELD_RE.match(raw)
        if not match:
            continue
        name, value = match.group(1).strip(), match.group(2).strip()
        if name == "成片目标时长":
            found = re.search(r"[0-9]+(?:\.[0-9]+)?", value)
            delivery["target"] = float(found.group(0)) if found else None
        elif name == "交付响度":
            found = re.search(r"-?[0-9]+(?:\.[0-9]+)?", value)
            delivery["lufs"] = float(found.group(0)) if found else None
        elif name == "字幕":
            delivery["burn"] = value != "无" and "不烧" not in value
        elif name == "画幅与帧率":
            size = re.search(r"([0-9]{2,5})\s*[×x*]\s*([0-9]{2,5})", value)
            if size:
                delivery["frame"] = [int(size.group(1)), int(size.group(2))]
            rate = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*fps", value, re.I)
            if rate:
                delivery["fps"] = float(rate.group(1))
    return delivery


def _entries(fields: dict[str, str], label: str) -> tuple[bool, list[str]]:
    """One kind of field, written once plain or as 「<label> 1..N」, in order.

    Returns whether the numbered form was used, and the values.
    """

    numbered: list[tuple[int, str]] = []
    plain: Optional[str] = None
    for key, value in fields.items():
        match = NUMBERED_RE[label].match(key)
        if not match:
            continue
        if match.group(1) is None:
            plain = value
        else:
            numbered.append((int(match.group(1)), value))
    if numbered:
        return True, [value for _, value in sorted(numbered)]
    return False, [] if plain is None else [plain]


def _subtitles(fields: dict[str, str]) -> list[dict[str, Any]]:
    def keywords(value: str) -> tuple[str, list[str]]:
        marked = KEYWORDS_RE.search(value)
        if not marked:
            return value.strip(), []
        words = [word.strip() for word in marked.group(1).split("｜")]
        return value[: marked.start()].strip(), words

    numbered, entries = _entries(fields, "字幕")
    cues: list[dict[str, Any]] = []
    if numbered:
        for value in entries:
            found = CUE_RE.match(value)
            if not found:
                continue
            text, words = keywords(found.group(3))
            cues.append({"s": float(found.group(1)), "e": float(found.group(2)), "text": text, "keys": words})
        return cues
    if not entries or entries[0].strip() == "无":
        return []
    text, words = keywords(entries[0])
    window = WINDOW_RE.match(fields.get("字幕时间", ""))
    return [{
        "s": float(window.group(1)) if window else None,
        "e": float(window.group(2)) if window else None,
        "text": text, "keys": words,
    }]


def _screen_texts(fields: dict[str, str]) -> list[dict[str, Any]]:
    texts = []
    for value in _entries(fields, "画面文字")[1]:
        if value.strip() == "无":
            continue
        countdown: Optional[float] = None
        resume = False
        counted = COUNTDOWN_RE.search(value)
        if counted:
            value = value[: counted.start()]
            if counted.group(1) == "接续":
                resume = True
            else:
                countdown = float(counted.group(1))
        found = SCREEN_TEXT_RE.match(value)
        if not found:
            continue
        items, rarities = [], []
        for raw in found.group(4).split("｜"):
            item = raw.strip()
            rare = RARITY_RE.search(item)
            items.append(item[: rare.start()].strip() if rare else item)
            rarities.append(rare.group(1) if rare else None)
        texts.append({
            "s": float(found.group(1)), "e": float(found.group(2)), "style": found.group(3),
            "items": items, "rarities": rarities, "countdown": countdown, "resume": resume,
        })
    return texts


def _sound_effects(fields: dict[str, str]) -> list[dict[str, Any]]:
    effects = []
    for value in _entries(fields, "音效")[1]:
        if value.strip() == "无":
            continue
        value, gain, offset = _options(value)
        found = CUE_RE.match(value)
        if not found:
            continue
        effects.append({
            "s": float(found.group(1)), "e": float(found.group(2)), "path": found.group(3),
            "gain": gain, "from": offset,
        })
    return effects


def _options(value: str) -> tuple[str, float, float]:
    """Split 「（起点：<秒>；增益：<dB>）」 off a sound line: (rest, gain, 起点)."""

    stated = OPTIONS_RE.search(value)
    if not stated:
        return value, 0.0, 0.0
    options = {}
    for part in re.split(r"[；;]", stated.group(1)):
        found = OPTION_RE.match(part.strip())
        if found:
            options[found.group(1)] = float(found.group(2))
    return value[: stated.start()], options.get("增益", 0.0), options.get("起点", 0.0)


def _voices(fields: dict[str, str]) -> list[dict[str, Any]]:
    voices = []
    for value in _entries(fields, "配音")[1]:
        if value.strip() == "无":
            continue
        value, gain, offset = _options(value)
        found = VOICE_RE.match(value)
        if found:
            voices.append({"s": float(found.group(1)), "path": found.group(2), "gain": gain, "from": offset})
    return voices


def _bed(fields: dict[str, str]) -> Optional[dict[str, Any]]:
    """A 「环境声」 line: where it starts in its cut and what loops; path None is 「无」."""

    if "环境声" not in fields:
        return None
    value, gain, offset = _options(fields["环境声"])
    found = BED_RE.match(value)
    if not found:
        return None
    path = found.group(2)
    return {"s": float(found.group(1) or 0.0), "path": None if path == "无" else path, "gain": gain, "from": offset}


def _move(fields: dict[str, str], still: bool) -> Optional[dict[str, Any]]:
    """A still's 「运镜」; 固定 when unwritten or unreadable, None on a video cut."""

    if not still:
        return None
    written = fields.get("运镜", "").strip()
    paced = MOVE_RATE_RE.match(written)
    if paced:
        return {"kind": paced.group(1), "amount": 0, "rate": float(paced.group(2))}
    found = MOVE_RE.match(written)
    if found:
        return {"kind": found.group(1), "amount": int(found.group(2)), "rate": None}
    return {"kind": "固定", "amount": 0, "rate": None}


def _seconds(value: Optional[str]) -> Optional[float]:
    try:
        return float((value or "").strip())
    except ValueError:
        return None


def parse_cut_list(text: str) -> dict[str, Any]:
    preamble: list[str] = []
    unused: list[str] = []
    pending: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    for raw in text.splitlines():
        heading = CUT_HEADING_RE.match(raw)
        if heading:
            current = {"id": heading.group(1), "title": (heading.group(2) or "").strip(), "fields": {}}
            pending.append(current)
            continue
        if raw.startswith("## "):
            current = None
            continue
        if current is None:
            found = re.match(r"^-\s*未采用镜头：\s*(.*)$", raw)
            if found:
                unused.extend(item.strip() for item in found.group(1).split("；") if item.strip())
            preamble.append(raw)
            continue
        field = CUT_FIELD_RE.match(raw)
        if field and field.group(1).strip() not in current["fields"]:
            current["fields"][field.group(1).strip()] = field.group(2).strip()
    cuts = []
    cursor = 0.0
    for item in pending:
        fields = item["fields"]
        source = SOURCE_RE.match(fields.get("来源", ""))
        start, end, declared = (_seconds(fields.get(name)) for name in ("入点", "出点", "时长"))
        if source is None or start is None or end is None or declared is None:
            # The edit tool refuses this cut; the dashboard shows the rest.
            continue
        motion = source.group(1)
        still = not motion.startswith("MOTION-")
        # A still names its storyboard shot directly; an IMG- still names none.
        shot = motion if motion.startswith("SHOT-") else None if still else "SHOT-" + motion[len("MOTION-"):]
        cuts.append({
            "id": item["id"], "n": _number(item["id"]), "title": item["title"],
            "motion": motion, "shot": shot, "still": still, "move": _move(fields, still),
            "media": source.group(2), "in": start, "out": end, "sec": declared,
            "at": round(cursor, 3),
            "subs": _subtitles(fields), "texts": _screen_texts(fields), "sfx": _sound_effects(fields),
            "voices": _voices(fields), "bed": _bed(fields),
        })
        cursor += declared
    if not cuts:
        raise ValueError("没有读到可用的 `## CUT-… · 标题` 段落（每段要有来源、入点、出点、时长）")
    return {**_delivery(preamble), "unused": unused, "cuts": cuts, "seconds": round(cursor, 3)}


# ------------------------------------------------------------------ review

# The review stage's suggested structure. Rule ids and the reviewer's internal
# severity names stay on the server: the creator reads what to change.
FINDING_RE = re.compile(r"^## (\S+) · (REV-[A-Za-z0-9-]+) · (.+)$", re.MULTILINE)
SEVERITIES = {
    "blocker": "must", "必须改": "must", "major": "should", "建议改": "should",
    "minor": "could", "可以更好": "could",
}
VERDICTS = {
    "REVISE": "需要修改", "APPROVE": "可以继续", "APPROVE_WITH_NOTES": "可以继续，有建议",
    "REJECT": "需要重做",
}
TARGET_RE = re.compile(r"SHOT-[A-Z0-9-]+|CUT-[A-Z0-9-]+|(?:[A-Za-z0-9]+-)+SC[0-9]+")


def parse_review(text: str) -> dict[str, Any]:
    head = dict(FIELD_RE.findall(text.split("\n## ", 1)[0]))
    parts = list(FINDING_RE.finditer(text))
    findings = []
    for index, match in enumerate(parts):
        body = text[match.end(): parts[index + 1].start() if index + 1 < len(parts) else None]
        fields = {key.strip(): value.strip() for key, value in FIELD_RE.findall(body)}
        where = fields.get("位置", "")
        findings.append({
            "sev": SEVERITIES.get(match.group(1).casefold(), "could"),
            "id": match.group(2),
            "title": match.group(3).strip(),
            "where": where,
            "targets": list(dict.fromkeys(TARGET_RE.findall(where))),
            "evidence": fields.get("证据", ""),
            "impact": fields.get("影响", ""),
            "fix": fields.get("修订结果", ""),
        })
    verdict = head.get("结论", "").strip()
    return {
        "scope": head.get("范围", "").strip(),
        "verdict": VERDICTS.get(verdict.upper(), verdict),
        "independent": "独立" in head.get("复核方式", ""),
        "findings": findings,
    }


# ------------------------------------------------------------------ episode

def _attempt(
    problems: list[str], document: str, reader: Callable[[str], Any], text: Optional[str]
) -> Any:
    if text is None:
        return None
    try:
        return reader(text)
    except (ValueError, KeyError, IndexError, AttributeError, TypeError) as exc:
        detail = str(exc) if isinstance(exc, ValueError) and str(exc) else "格式和约定不一致"
        problems.append(f"{document} 没有按结构读出来：{detail}。下面按原文显示。")
        return None


def episode_title(script: Optional[dict[str, Any]]) -> str:
    return str(script.get("title", "")) if script else ""


def metrics(script: Optional[dict[str, Any]], board: Optional[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"shots": 0, "seconds": 0, "avg": None, "close": None, "unsized": 0,
                              "vo": None, "spoken": 0}
    if board:
        shots = board["shots"]
        seconds = sum(shot["sec"] for shot in shots)
        sized = [shot for shot in shots if shot["scale"]]
        result.update({
            "shots": len(shots),
            "seconds": round(seconds, 3),
            "avg": round(seconds / len(shots), 2) if shots else None,
            "close": round(sum(1 for shot in shots if shot["close"]) / len(shots), 3) if shots else None,
            "closeCount": sum(1 for shot in shots if shot["close"]),
            "unsized": len(shots) - len(sized),
        })
    if script:
        counts = voice_share(script)
        result["spoken"] = counts["spoken"]
        result["vo"] = round(counts["vo"] / counts["spoken"], 3) if counts["spoken"] else None
    return result


def read_episode(episode_id: str, documents: dict[str, Optional[str]], review: Optional[str]) -> dict[str, Any]:
    """Parse whatever of the episode exists. Missing documents are ``None``."""

    problems: list[str] = []
    script = _attempt(problems, SCREENPLAY, parse_screenplay, documents.get(SCREENPLAY))
    settings = _attempt(problems, SETTINGS, parse_settings, documents.get(SETTINGS))
    board = _attempt(problems, STORYBOARD, parse_storyboard, documents.get(STORYBOARD))
    images = _attempt(problems, IMAGE_PROMPTS, parse_image_prompts, documents.get(IMAGE_PROMPTS))
    videos = _attempt(problems, VIDEO_PROMPTS, parse_video_prompts, documents.get(VIDEO_PROMPTS))
    cutlist = _attempt(problems, CUT_LIST, parse_cut_list, documents.get(CUT_LIST))
    parsed_review = _attempt(problems, "审查意见", parse_review, review)
    return {
        "id": episode_id,
        "title": episode_title(script),
        "script": script,
        "settings": settings,
        "board": board,
        "imagePrompts": images,
        "videoPrompts": videos,
        "cutlist": cutlist,
        "review": parsed_review,
        "metrics": metrics(script, board),
        "problems": problems,
    }


def review_counts(review: Optional[dict[str, Any]]) -> dict[str, int]:
    counts = {"must": 0, "should": 0, "could": 0}
    for finding in (review or {}).get("findings", []):
        counts[finding["sev"]] += 1
    return counts


# ------------------------------------------------------------------ search

def search_entries(episode: dict[str, Any]) -> list[dict[str, Any]]:
    """Everything a creator asks "where is it" about, one row per findable thing.

    ``view``/``arg`` name where the result opens, in the dashboard's own terms.
    """

    ep = episode["id"]
    rows: list[dict[str, Any]] = []

    def add(group: str, who: str, title: str, extra: str, view: str, arg: str = "", **more: Any) -> None:
        rows.append({"g": group, "w": who, "t": title, "x": extra, "ep": ep, "view": view, "arg": arg, **more})

    for shot in (episode.get("board") or {}).get("shots", []):
        add("镜头", f"{shot['n']} {shot['scale']}".strip(), shot["title"],
            " ".join([shot["purpose"], shot["framing"], shot["move"], shot["start"], shot["action"],
                      shot["end"], shot["sound"], shot["screenText"]]), "board", shot["id"])
    for scene in (episode.get("script") or {}).get("scenes", []):
        short = _number(scene["id"])
        for block in scene["blocks"]:
            if block["k"] == "line":
                add("台词", block["who"], block["text"], "", "script", scene["id"], line=block["text"])
            elif block["k"] == "tag":
                group = {"画面文字": "画面文字", "SFX": "音效"}.get(block["tag"], "剧本")
                add(group, f"SC{short}", block["text"], "", "script", scene["id"], line=block["text"])
            else:
                add("剧本动作", f"SC{short}", block["text"], "", "script", scene["id"])
    for item in (episode.get("settings") or {}).get("items", []):
        add("设定", item["cat"], item["name"],
            " ".join([*item["desc"], *item["fields"].values(), *item["designators"]]), "settings", item["name"])
    for prompt in episode.get("videoPrompts") or []:
        add("提示词", prompt["id"], prompt["title"], prompt["prompt"], "prompts", "video", id=prompt["id"])
    for prompt in episode.get("imagePrompts") or []:
        add("提示词", prompt["id"], prompt["title"], prompt["prompt"] + " " + prompt["use"],
            "prompts", "image", id=prompt["id"])
    for finding in (episode.get("review") or {}).get("findings", []):
        label = {"must": "必须改", "should": "建议改", "could": "可以更好"}[finding["sev"]]
        add("审查", label, finding["title"],
            " ".join([finding["evidence"], finding["impact"], finding["fix"], " ".join(finding["targets"])]),
            "review", finding["id"])
    for cut in (episode.get("cutlist") or {}).get("cuts", []):
        for sub in cut["subs"]:
            add("剪辑", cut["id"], sub["text"], cut["title"], "film", "", cut=cut["id"])
        for text in cut["texts"]:
            add("剪辑", cut["id"], "｜".join(text["items"]), text["style"], "film", "", cut=cut["id"])
    return rows


def search(rows: list[dict[str, Any]], query: str, limit: int = 60) -> list[dict[str, Any]]:
    """Rows whose title, label or body contain the query, with where it matched."""

    needle = query.strip().casefold()
    if not needle:
        return []
    hits = []
    for row in rows:
        for field in ("t", "w", "x"):
            haystack = str(row[field])
            at = haystack.casefold().find(needle)
            if at < 0:
                continue
            start = max(0, at - 24) if field == "x" else 0
            snippet = haystack[start: at + len(needle) + 60] if field == "x" else haystack
            hits.append({
                **{key: value for key, value in row.items() if key != "x"},
                "field": field,
                "snippet": snippet,
                "clipped": start > 0,
                "at": at - start,
                "len": len(needle),
            })
            break
        if len(hits) >= limit:
            break
    return hits
