#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WhaleDigest · MiniMax H3 官方标准全场景提示词编译器 + 全集人物音色账本引擎
(Official H3 Ref2VA Six-Section Compiler + Episode Voice Registry)

目标：无论上游用哪个大模型（Claude / GPT / Gemini / DeepSeek）写镜头要素，
都通过同一个确定性编译器输出 100% 符合官方 MiniMax-H3 `h3-prompt-writing`
(commit 199b7d0e1fd95e7b3eafa8c15eca692534142427) + 吞鲸实战经验的标准 H3 提示词。

覆盖全部 6 种发声/画面场景：
  1. empty_shot      : 空镜（仅场景图、严禁虚构人物/嘴部/对白；可选旁白或画外音）
  2. on_screen       : 画内对白（明确音色锚定 + 说话动作 + 同框其他角色强制闭嘴锁）
  3. off_screen_vo   : 画外音（人物不在画面内发声，官方精确句式 `says in an off-screen voiceover` + 画内人物全程闭嘴）
  4. inner_monologue : 内心独白（画内本人心里说话，官方 `says in an off-screen voiceover` + `internal thoughts` + 本人双唇紧闭）
  5. narrator        : 独立旁白（独立全局声源 ID 如 `S9`，绝不抢占任何角色 `S1/S2/...` ID，画内全员闭嘴）
  6. silent          : 有人物无对白镜（无 `<d>` 标签，只写呼吸/拟音/环境声，绝不塞假对白）

全集人物音色账本 (`voice_bible.json` / `series_bible.json['voices']`)：
  - 每个角色绑定唯一稳定的 `(Sx)` 全局声源 ID 与差异化英文音色指纹
    （age + gender + pitch + texture + pace + accent），杜绝同一集里多个人物声音撞车。
  - 若同一集内两个不同角色音色指纹撞车或声源 ID 重复，校验直接报错。
"""
import json
import os
import re
from pathlib import Path

from whale_core import sanitize_positive_only, DE_OIL
from whale_compiler import lint_whale_prompt


# ── 官方 retention_analysis 合法枚举（来自 MiniMax-H3 ref-en.txt Section 4）──
VALID_VISUAL_RETENTION = ("fully_preserved", "partially_preserved", "attribute_transfer", "weak_reference")
VALID_AUDIO_RETENTION = ("fully_copy", "partially_copy", "reference", "weak_reference")

# ── 官方说话模式枚举 ──
VALID_SPEECH_MODES = ("none", "on_screen", "off_screen_vo", "inner_monologue", "narrator")

# ── 预设差异化音色模板库（按年龄/性别/声线区分，确保同集多角色音色天然拉开距离）──
VOICE_TIMBRE_PRESETS = {
    "young_female_clear":   "a clear, bright young female voice in a medium-high register with crisp enunciation and natural conversational cadence",
    "young_female_soft":    "a soft, slightly breathy young female voice with warm midrange resonance and gentle measured pacing",
    "mature_female_cool":   "a composed, poised mature female voice in a low-alto register with cool restraint and deliberate pacing",
    "elder_female_warm":    "a gentle, weathered elderly female voice with slight warmth and unhurried homey cadence",
    "young_male_earnest":   "an earnest, bright young male voice in a medium register with crisp articulation and energetic steady pacing",
    "young_male_casual":    "a relaxed, slightly dry young male baritone with easy conversational rhythm",
    "mature_male_deep":     "a deep, resonant mature male baritone with slight gravel, calm authority, and measured delivery",
    "mature_male_sharp":    "a crisp, assertive mature male voice in a mid-low register with tight cadence and controlled edge",
    "elder_male_raspy":     "a gruff, raspy elderly male voice with earthy texture, heavy breath, and lively colloquial rhythm",
    "child_high":           "a light, high-pitched child voice with innocent bright timbre and quick natural phrasing",
    "mascot_playful":       "a nimble, animated high-pitched youthful voice with playful crisp inflection and bouncy rhythm",
    "narrator_calm":        "a steady, neutral off-screen narrator voice in a warm mid-low register with clean broadcast articulation and unhurried documentary pacing",
}

# 官方 camera motion 规范词映射（对应 base-en.txt Section 4.3: Motion Type + Amplitude + Speed）
OFFICIAL_CAMERA_PHRASES = {
    "static_shot":      "holds a static shot",
    "static_side":      "holds a static shot from a 90-degree side profile angle",
    "static_front":     "holds a static shot from an eye-level front angle",
    "push_tension":     "pushes in with small amplitude at slow speed",
    "pull_reveal":      "pulls out with small amplitude at slow speed",
    "arc_subtle":       "moves in an arc shot with small amplitude at slow speed",
    "tilt_up_desire":   "tilts up with small amplitude at slow speed",
    "tilt_down_impact": "tilts down with small amplitude at slow speed",
    "handheld_breath":  "shakes slightly with subtle breathing rhythm",
    "low_upward":       "frames from a subtle low upward angle and pushes in with small amplitude at slow speed",
    "high_downward":    "frames from a subtle high downward angle and pedestals down with small amplitude at slow speed",
    "low_hip":          "tracks from a low hip-level angle with small amplitude at steady speed",
    "pan_left_right":   "pans right with small amplitude at slow speed",
    "track_lateral":    "trucks right with small amplitude at steady speed",
    "ots_depth":        "tracks slightly laterally from an over-the-shoulder angle with small amplitude at slow speed",
}


class VoiceRegistry:
    """全集人物音色与声源 ID 注册表（一剧一账本，防音色撞车与 Sx 串号）。"""

    def __init__(self, entries=None):
        self.entries = {}
        for item in (entries or []):
            self.register(**item)

    def register(self, character, speaker_id, timbre="", gender="", age_group="", preset=None, notes=""):
        char_key = str(character).strip()
        if not char_key:
            raise ValueError("character name must be nonempty")
        sid = str(speaker_id).strip().upper()
        if not re.fullmatch(r"S[1-9][0-9]*", sid):
            raise ValueError(f"speaker_id must look like S1/S2/..., got {speaker_id!r}")
        timbre_text = (VOICE_TIMBRE_PRESETS.get(preset, "") if preset else "") or str(timbre or "").strip()
        if not timbre_text or re.search(r"[\u4e00-\u9fff]", timbre_text):
            raise ValueError(f"角色 {char_key} ({sid}) 的音色描述 timbre 必须为非空纯英文声学描述")
        self.entries[char_key] = {
            "character": char_key,
            "speaker_id": sid,
            "timbre": timbre_text,
            "gender": str(gender or "").strip(),
            "age_group": str(age_group or "").strip(),
            "notes": str(notes or "").strip(),
        }
        return self.entries[char_key]

    def validate_distinctness(self):
        """校验全集角色声源 ID 无重复、且不同角色不使用完全雷同的音色描述。"""
        errors = []
        by_sid = {}
        by_timbre = {}
        for char_key, entry in self.entries.items():
            sid = entry["speaker_id"]
            if sid in by_sid:
                errors.append(f"音色账本冲突：角色 '{char_key}' 与 '{by_sid[sid]}' 共用了同一个声源编号 {sid}")
            by_sid[sid] = char_key
            norm_timbre = re.sub(r"\s+", " ", entry["timbre"].strip().lower())
            if norm_timbre in by_timbre:
                errors.append(
                    f"音色撞车拦截：角色 '{char_key}' ({sid}) 与 '{by_timbre[norm_timbre]}' 使用了完全相同的英文音色描述，"
                    "会导致 H3 原生语音分不清谁在说话！必须为每人拉开音高/质感/语速差异。"
                )
            by_timbre[norm_timbre] = f"{char_key} ({sid})"
        return errors

    def get(self, character_or_sid):
        key = str(character_or_sid or "").strip()
        if key in self.entries:
            return self.entries[key]
        up = key.upper()
        for entry in self.entries.values():
            if entry["speaker_id"] == up:
                return entry
        return None

    def to_dict(self):
        return {
            "schema": "whale-voice-bible-v1",
            "voices": list(self.entries.values()),
        }

    def save(self, path):
        errs = self.validate_distinctness()
        if errs:
            raise ValueError("; ".join(errs))
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        voices = data.get("voices", data) if isinstance(data, dict) else data
        return cls(voices)


def load_project_voice_registry(project_dir):
    """自动从项目目录（或父级剧集目录）加载 voice_bible.json（若存在）。"""
    root = Path(project_dir).resolve()
    for candidate in (root / "voice_bible.json", root.parent / "voice_bible.json"):
        if candidate.is_file():
            return VoiceRegistry.load(candidate)
    return None


def _normalize_retention(kind, value):
    if kind == "audio":
        val = str(value or "reference").strip()
        if val not in VALID_AUDIO_RETENTION:
            raise ValueError(f"Invalid audio retention marker {val!r}; expected one of {VALID_AUDIO_RETENTION}")
        return val
    val = str(value or ("weak_reference" if kind == "scene" else "fully_preserved")).strip()
    if val not in VALID_VISUAL_RETENTION:
        raise ValueError(f"Invalid visual retention marker {val!r}; expected one of {VALID_VISUAL_RETENTION}")
    return val


def _clean_en(text, field_name):
    s = sanitize_positive_only(str(text or "").strip())
    if re.search(r"[\u4e00-\u9fff]", s):
        raise ValueError(f"H3 字段 {field_name} 必须为英文（仅 <d> 台词内保留中文），检测到汉字: {s[:60]}")
    return s


def compile_h3_ref2va_prompt(spec, voice_registry=None):
    """将结构化镜头规范编译为 100% 符合官方 MiniMax-H3 六段式 + 吞鲸实战铁律的纯正向提示词。

    spec 字段：
      - shot_mode: "empty_shot" | "standard" | "intimate" (默认 "standard")
      - style: str (英文画面风格，例如 "Realistic 35mm live-action cinema" 或 "Pixar-style 3D animated cinema")
      - aspect: "16:9" | "9:16" | "1:1"
      - slots: list[dict] (1..9 个有序参考图槽位，顺序与 ref_images 一一对应)：
          * picture: int (1..9，默认按顺序 1..N)
          * subject: int (可选，默认同 picture；若 kind=="keyframe" 则直接作为 <Picture N> 不建 Subject)
          * kind: "character" | "scene" | "prop" | "keyframe"
          * name: str (可选角色中文/英文名，用于查 voice_registry)
          * desc: str (英文外观/环境描述)
          * retention: "fully_preserved" | "partially_preserved" | "attribute_transfer" | "weak_reference"
          * retention_note: str (可选保留细节说明)
          * on_screen: bool (默认 True；若角色本镜不在画内可标 False)
          * nudity: bool (默认 False；肉戏裸体段为 True 时追加全肯定裸肌描写)
      - camera: str (机位代号如 "push_tension" 或自然英文机位句)
      - framing: str (英文景别构图，如 "medium close-up", "wide architectural establishing shot")
      - summary: str (英文单段总结，不含任务前缀时自动补 `[reference generation]`)
      - action: str (英文画面动作与状态变化；空镜只写环境/光影/物体运动，严禁人物与嘴部)
      - speech: dict | None (可选发声配置，单镜最多一条)：
          * mode: "none" | "on_screen" | "off_screen_vo" | "inner_monologue" | "narrator"
          * speaker_subject: int | None (画内说话或本人内心独白时对应的 <Subject N>)
          * character: str (可选，用于查 voice_registry)
          * speaker_id: str (如 "S1" / "S2" / "S9"，若省略自动从 voice_registry 查)
          * timbre: str (英文音色描述，若省略自动从 voice_registry 查)
          * delivery: str (英文语气/语速，如 "in a calm, steady tone")
          * verb: str (发声动词，默认 "says")
          * language: str (默认 "Chinese")
          * text: str (逐字中文/原文台词)
          * start_sec: float (可选起始秒，默认 0.50)
          * end_sec: float (可选结束秒，默认按字数推算)
      - soundscape: str (英文环境声/拟音；空镜与无对白镜写清底噪与物理声响)
      - non_diegetic_music: str (默认 "N/A")
      - apply_de_oil: bool (真人写实默认 True；3D 动画可设 False)
    """
    if not isinstance(spec, dict):
        raise ValueError("spec must be a dict")
    slots = spec.get("slots") or []
    if not isinstance(slots, list) or not 1 <= len(slots) <= 9:
        raise ValueError("spec['slots'] must contain 1 to 9 ordered reference bindings")

    shot_mode = str(spec.get("shot_mode") or "standard").strip().lower()
    is_empty = shot_mode == "empty_shot"
    speech = spec.get("speech") or None
    speech_mode = str((speech or {}).get("mode") or "none").strip().lower()
    if speech_mode not in VALID_SPEECH_MODES:
        raise ValueError(f"Unsupported speech mode: {speech_mode!r}; expected {VALID_SPEECH_MODES}")

    # 空镜防呆：空镜禁止绑定 character 槽，且禁止画内对白
    if is_empty:
        if any(str(sl.get("kind") or "").lower() == "character" for sl in slots):
            raise ValueError("空镜 (empty_shot) 不得声明 character 人物槽，请只挂 scene/prop/keyframe 参考图")
        if speech_mode == "on_screen":
            raise ValueError("空镜 (empty_shot) 无画内人物，不能使用 on_screen 画内对白（若需画外声请改用 narrator 或 off_screen_vo）")

    # 1) 解析槽位 & 构建 subject_definitions + retention_analysis
    sub_defs = []
    ret_lines = []
    char_slots = []
    has_keyframe = False
    scene_subject_id = None

    for idx, sl in enumerate(slots, 1):
        pic = int(sl.get("picture", idx))
        if not 1 <= pic <= 9:
            raise ValueError(f"Picture slot must be 1..9, got {pic}")
        kind = str(sl.get("kind") or ("scene" if is_empty else "character")).strip().lower()
        desc = _clean_en(sl.get("desc") or "", f"slots[{idx}].desc")
        if not desc:
            raise ValueError(f"slots[{idx}].desc must be a nonempty English description")
        ret_marker = _normalize_retention(kind, sl.get("retention"))
        ret_note = _clean_en(sl.get("retention_note") or "", f"slots[{idx}].retention_note")

        if kind == "keyframe":
            has_keyframe = True
            sub_defs.append(f"<Picture {pic}> is the opening frame of [Shot 1], showing {desc}.")
            note = ret_note or "opening composition, subject placement, and lighting are retained as the starting frame."
            ret_lines.append(f"<Picture {pic}> ([Shot 1] first frame): {ret_marker} - {note}")
            continue

        sub = int(sl.get("subject", pic))
        if kind == "scene":
            scene_subject_id = scene_subject_id or sub
            sub_defs.append(f"<Subject {sub}> is {desc}, anchored in <Picture {pic}>.")
            note = ret_note or f"environment layout, surface texture, and lighting direction from <Picture {pic}> are retained while camera framing adapts to the shot."
            ret_lines.append(f"<Subject {sub}> (appears in [Shot 1]): {ret_marker} - {note}")
        elif kind == "prop":
            sub_defs.append(f"<Subject {sub}> is {desc}, anchored in <Picture {pic}>.")
            note = ret_note or f"object geometry, printed markings, and material texture are strictly locked to <Picture {pic}>."
            ret_lines.append(f"<Subject {sub}> (appears in [Shot 1]): {ret_marker} - {note}")
        else:
            # 若该人物在 voice_registry 中已有全局声源编号 (Sx)，在 subject_definitions 就显式声明 <Subject N> (Sx)，
            # 让官方多角色跨槽位映射（例如第 4 号角色苏晚 (S4) 放在第 1 槽 <Subject 1>）100% 明确无歧义
            reg_char = voice_registry.get(sl.get("name")) if (voice_registry is not None and sl.get("name")) else None
            char_sid = str(sl.get("speaker_id") or (reg_char["speaker_id"] if reg_char else "")).strip().upper()
            voice_tag = f" ({char_sid})" if re.fullmatch(r"S[1-9][0-9]*", char_sid) else ""
            nude_tail = (
                " Completely unclothed with continuous bare natural skin from shoulders to waist and limbs."
                if sl.get("nudity") else ""
            )
            sub_defs.append(f"<Subject {sub}>{voice_tag} is {desc}, anchored in <Picture {pic}>.{nude_tail}")
            note = ret_note or (
                f"facial identity, hairstyle, physique, and skin tone are strictly locked to <Picture {pic}>."
                + (" Full bare skin continuity maintained across every frame." if sl.get("nudity") else "")
            )
            ret_lines.append(f"<Subject {sub}> (appears in [Shot 1]): {ret_marker} - {note}")
            char_slots.append({
                "subject": sub,
                "picture": pic,
                "name": str(sl.get("name") or "").strip(),
                "on_screen": bool(sl.get("on_screen", True)),
            })

    # 2) 构建 summary（遵循官方 [task type] 前缀）
    task_prefix = "[keyframe completion + reference generation]" if has_keyframe else "[reference generation]"
    summary_body = _clean_en(spec.get("summary") or "", "summary")
    if not summary_body:
        raise ValueError("spec['summary'] must be a nonempty English summary")
    if not summary_body.startswith("["):
        summary_line = f"{task_prefix} {summary_body}"
    else:
        summary_line = summary_body

    # 3) 构建 detailed_description（风格句 + 独立 Camera: 行 + [Shot 1] + 可选 SPEECH: 行）
    style = _clean_en(spec.get("style") or "Realistic live-action cinema with natural lighting", "style")
    framing = _clean_en(spec.get("framing") or ("wide architectural establishing shot" if is_empty else "medium close-up"), "framing")
    raw_cam = str(spec.get("camera") or "push_tension").strip()
    cam_phrase = OFFICIAL_CAMERA_PHRASES.get(raw_cam, _clean_en(raw_cam, "camera"))
    de_oil_clause = f", {DE_OIL}" if spec.get("apply_de_oil", True) else ""
    camera_line = f"Camera: {framing}; the camera {cam_phrase}{de_oil_clause}."

    action = _clean_en(spec.get("action") or "", "action")
    if not action:
        raise ValueError("spec['action'] must be a nonempty English visual action description")

    # 4) 处理 5 种发声模式 + 全集音色绑定 + 非说话人闭嘴物理锁
    speech_line = ""
    if speech and speech_mode != "none":
        raw_text = str(speech.get("text") or "").strip()
        if not raw_text:
            raise ValueError("speech.text cannot be empty when speech.mode != 'none'")
        if "\n" in raw_text or "\r" in raw_text:
            raise ValueError("speech.text must be a single line without embedded newlines")
        lang = str(speech.get("language") or "Chinese").strip()
        verb = str(speech.get("verb") or "says").strip().lower()
        if verb not in ("says", "asks", "replies", "whispers", "shouts", "speaks", "calls", "murmurs", "cries", "answers", "states", "declares", "adds", "continues"):
            verb = "says"
        delivery = _clean_en(speech.get("delivery") or "with natural conversational pacing", "speech.delivery")

        # 查音色账本（优先显式字段，缺失自动按角色名或 speaker_id 从 voice_registry 补齐）
        reg_entry = None
        if voice_registry is not None:
            reg_entry = voice_registry.get(speech.get("character") or speech.get("speaker_id"))
        sid = str(speech.get("speaker_id") or (reg_entry["speaker_id"] if reg_entry else "")).strip().upper()
        if not re.fullmatch(r"S[1-9][0-9]*", sid):
            raise ValueError(f"说话人必须绑定合法全局声源编号 (S1/S2/...)，实测: {sid!r}")
        timbre = _clean_en(
            speech.get("timbre") or (reg_entry["timbre"] if reg_entry else ""),
            "speech.timbre",
        )
        if not timbre:
            raise ValueError(f"说话人 {sid} 缺少英文音色指纹 timbre（请在 voice_bible 或 speech.timbre 中明确指定，避免同集音色撞车）")

        t_start = float(speech.get("start_sec", 0.50))
        if speech.get("end_sec") is not None:
            t_end = float(speech["end_sec"])
        else:
            t_end = round(t_start + max(1.0, len(re.sub(r"\s+", "", raw_text)) / 4.1), 2)

        on_screen_chars = [c["subject"] for c in char_slots if c["on_screen"]]
        spk_sub = speech.get("speaker_subject")

        if speech_mode == "on_screen":
            if spk_sub is None:
                raise ValueError("on_screen 模式必须指定 speaker_subject（画内说话的 <Subject N> 编号）")
            spk_sub = int(spk_sub)
            if spk_sub not in [c["subject"] for c in char_slots]:
                raise ValueError(f"speaker_subject={spk_sub} 未在 slots 中声明为人物主体")
            # 同框非说话人全部显式闭嘴锁（解决 H3 把口型张在最显眼正脸上的老毛病）
            silent_others = [s for s in on_screen_chars if s != spk_sub]
            if silent_others:
                others_str = " and ".join(f"<Subject {s}>" for s in silent_others)
                verb_be = "remain" if len(silent_others) > 1 else "remains"
                close_lock = f" {others_str} stays silent; lips {verb_be} completely closed."
            else:
                close_lock = ""
            speech_line = (
                f"\nSPEECH: From {t_start:.2f}s to {t_end:.2f}s, only <Subject {spk_sub}> ({sid}), "
                f"speaking on-screen in {timbre}, {delivery}, {verb}: "
                f"<d>[{lang}]{raw_text}</d>.{close_lock}"
            )

        elif speech_mode == "off_screen_vo":
            # 画外音：人物不在画内，用官方精确短语 `says in an off-screen voiceover`，画内全员闭嘴
            if spk_sub is not None and int(spk_sub) in on_screen_chars:
                raise ValueError("off_screen_vo（画外音）说话人不能同时标记为画内说话；若是画内人物心里话请用 inner_monologue")
            spk_label = f"<Subject {int(spk_sub)}> ({sid})" if spk_sub is not None else f"The off-screen speaker ({sid})"
            if on_screen_chars:
                all_str = " and ".join(f"<Subject {s}>" for s in on_screen_chars)
                close_lock = f" while {all_str}'s lips remain completely closed."
            else:
                close_lock = "."
            speech_line = (
                f"\nSPEECH: From {t_start:.2f}s to {t_end:.2f}s, {spk_label}, "
                f"in {timbre}, {delivery}, {verb} in an off-screen voiceover: "
                f"<d>[{lang}]{raw_text}</d>{close_lock}"
            )

        elif speech_mode == "inner_monologue":
            # 内心独白：画内角色心里独白，遵循官方 `says in an off-screen voiceover` + 本人及同框人物双唇紧闭
            if spk_sub is not None:
                spk_sub = int(spk_sub)
                spk_label = f"<Subject {spk_sub}> ({sid})"
            else:
                spk_label = f"The speaker ({sid})"
            if on_screen_chars:
                all_str = " and ".join(f"<Subject {s}>" for s in on_screen_chars)
                close_lock = f" while {all_str}'s lips remain completely closed throughout the internal monologue."
            else:
                close_lock = " as an internal monologue with intimate close-mic presence."
            speech_line = (
                f"\nSPEECH: From {t_start:.2f}s to {t_end:.2f}s, {spk_label}, "
                f"in {timbre} heard as quiet internal thoughts, {delivery}, {verb} in an off-screen voiceover: "
                f"<d>[{lang}]{raw_text}</d>{close_lock}"
            )

        elif speech_mode == "narrator":
            # 独立旁白：不绑定任何画面人物 Subject，用独立全局 ID（如 S9），画内人物全员闭嘴
            if on_screen_chars:
                all_str = " and ".join(f"<Subject {s}>" for s in on_screen_chars)
                close_lock = f" while {all_str}'s lips remain completely closed."
            else:
                close_lock = "."
            speech_line = (
                f"\nSPEECH: From {t_start:.2f}s to {t_end:.2f}s, the narrator ({sid}), "
                f"speaking in {timbre}, {delivery}, {verb} in an off-screen voiceover: "
                f"<d>[{lang}]{raw_text}</d>{close_lock}"
            )

    # 5) 组装最终六段式正文（精确对齐官方 ref-en.txt 顺序与边界）
    soundscape = _clean_en(
        spec.get("soundscape") or ("Quiet ambient environment tone continues naturally throughout the shot." if is_empty else "Natural room tone and subtle physical foley continue throughout the shot."),
        "soundscape",
    )
    music = _clean_en(spec.get("non_diegetic_music") or "N/A", "non_diegetic_music")

    shot_open = f"{style}.\n{camera_line}\n[Shot 1] {action.rstrip('.')}."
    if has_keyframe and "<Picture 1>" not in action:
        shot_open = f"{style}.\n{camera_line}\n[Shot 1] The shot begins from <Picture 1>; {action.rstrip('.')}."

    prompt = "\n".join([
        "subject_definitions:",
        *sub_defs,
        f"summary: {summary_line}",
        "retention_analysis:",
        *ret_lines,
        "detailed_description:",
        shot_open + speech_line,
        f"overall_soundscape: {soundscape}",
        f"non_diegetic_music: {music}",
    ])

    errors, _ = lint_whale_prompt(prompt)
    if errors:
        raise ValueError("Compiled H3 prompt failed compiler check: " + "; ".join(errors))
    return prompt


def validate_batch_voice_consistency(batch, voice_registry=None):
    """全集/批量音色一致性与跨镜声源校验（供 Gate 4 / Gate 5 调用）：
    1. 若项目存在 voice_bible.json，强制校验无声源 ID 重复、无雷同音色描述；
    2. 校验批量任务中同一个角色名/同主语跨镜不能随意更换 (Sx) 编号；
    3. 校验画外音/内心独白/旁白必须包含闭嘴锁（当镜头存在画内人物时）。
    """
    errors = []
    warnings = []
    if voice_registry is not None:
        errors.extend(voice_registry.validate_distinctness())

    char_to_sid = {}
    for idx, shot in enumerate(batch.get("batch_shots", []), 1):
        sid_label = shot.get("shot_id") or shot.get("id") or idx
        prompt = str(shot.get("prompt") or "")
        # 检查画外音/独白是否漏掉闭嘴锁（针对存在画内人物的镜头）
        if "off-screen voiceover" in prompt.lower():
            has_person = bool(re.search(r"<Subject\s+\d+>.*?(?:woman|man|boy|girl|ranger|clerk|leader|character|colleague|resident|elder|child)", prompt, re.I))
            has_closed_lips = bool(re.search(r"lips?\s+remain(?:s)?\s+(?:completely\s+)?closed", prompt, re.I))
            if has_person and not has_closed_lips:
                errors.append(
                    f"镜头 {sid_label} [画外音/独白漏闭嘴锁]：含 off-screen voiceover 且画面有人物，必须写明画内人物 lips remain completely closed 防错张嘴！"
                )
        # 检查结构化 speech 元数据中的角色声源 ID 是否全集稳定
        sp = shot.get("speech")
        if isinstance(sp, dict) and sp.get("character") and sp.get("speaker_id"):
            cname = str(sp["character"]).strip()
            spk_id = str(sp["speaker_id"]).strip().upper()
            if cname in char_to_sid and char_to_sid[cname] != spk_id:
                errors.append(
                    f"镜头 {sid_label} [声源串号]：角色 '{cname}' 前文绑定 {char_to_sid[cname]}，本镜变成 {spk_id}！"
                )
            char_to_sid[cname] = spk_id
            if voice_registry is not None:
                reg = voice_registry.get(cname)
                if reg and reg["speaker_id"] != spk_id:
                    errors.append(
                        f"镜头 {sid_label} [音色账本冲突]：角色 '{cname}' 在 voice_bible.json 中固定为 {reg['speaker_id']}，本镜错写为 {spk_id}！"
                    )
    return errors, warnings


def ensure_default_voice_registry(speakers=None):
    """当项目未手工配置 voice_bible.json 时，提供默认全集差异化英文音色账本（S1 女主 / S2 男主 / S9 旁白）。"""
    entries = [
        {"character": "女子A", "speaker_id": "S1", "preset": "young_female_clear", "gender": "female", "age_group": "young_adult"},
        {"character": "男子A", "speaker_id": "S2", "preset": "mature_male_deep", "gender": "male", "age_group": "adult"},
        {"character": "旁白", "speaker_id": "S9", "preset": "narrator_calm", "gender": "neutral", "age_group": "adult"},
    ]
    presets = list(VOICE_TIMBRE_PRESETS.keys())
    used_sids = {e["speaker_id"] for e in entries}
    used_presets = {e["preset"] for e in entries}
    next_sid = 3
    for spk in (speakers or []):
        name = str(spk or "").strip()
        if not name or any(e["character"] == name for e in entries):
            continue
        while f"S{next_sid}" in used_sids:
            next_sid += 1
        sid = f"S{next_sid}"
        used_sids.add(sid)
        pick = next((p for p in presets if p not in used_presets), presets[next_sid % len(presets)])
        used_presets.add(pick)
        entries.append({"character": name, "speaker_id": sid, "preset": pick})
    return VoiceRegistry(entries)


def compile_h3_base_prompt(spec, voice_registry=None):
    """编译官方 MiniMax H3 三段式提示词（Base 文生 / first_frame 首帧 / first_last_frame 首尾帧）。

    输出结构严格遵循官方 base-en.txt 与 references/dialects/minimax-h3.md：
      integrated_multimodal_description: [Shot 1] ...
      overall_soundscape: ...
      non_diegetic_music: ...
    """
    if not isinstance(spec, dict):
        raise ValueError("spec must be a dict")
    mode = str(spec.get("mode") or "text").strip().lower()
    if mode not in ("text", "first_frame", "first_last_frame"):
        raise ValueError(f"Base 3-section mode must be text/first_frame/first_last_frame, got {mode!r}")
    style = _clean_en(spec.get("style") or "Realistic 35mm live-action cinema", "style")
    framing = _clean_en(spec.get("framing") or "medium close-up", "framing")
    raw_cam = str(spec.get("camera") or "push_tension").strip()
    cam_phrase = OFFICIAL_CAMERA_PHRASES.get(raw_cam, _clean_en(raw_cam, "camera"))
    de_oil_clause = f", {DE_OIL}" if spec.get("apply_de_oil", True) else ""

    cuts = spec.get("shots") or [
        {"action": spec.get("action") or "", "speech": spec.get("speech"), "t0": 0.0}
    ]
    shot_lines = []
    for idx, c in enumerate(cuts, 1):
        act = _clean_en(c.get("action") or "", f"shots[{idx}].action")
        if not act:
            raise ValueError(f"shots[{idx}].action must be nonempty English")
        prefix = f"[Shot {idx}] " if idx == 1 else f"[Shot {idx}] At {float(c.get('t0', 0.0)):06.3f}s, ".replace("At 00", "At 00:")
        if idx > 1:
            t_val = float(c.get("t0", 0.0))
            mm = int(t_val // 60)
            ss = t_val - mm * 60
            prefix = f"[Shot {idx}] At {mm:02d}:{ss:06.3f}, "
        line = f"{prefix}{style}; {framing}; the camera {cam_phrase}{de_oil_clause}; {act.rstrip('.')}."
        sp = c.get("speech")
        if isinstance(sp, dict) and str(sp.get("mode") or "none").lower() != "none":
            raw_txt = str(sp.get("text") or "").strip()
            if not raw_txt:
                raise ValueError(f"shots[{idx}].speech.text cannot be empty")
            lang = str(sp.get("language") or "Chinese").strip()
            reg = voice_registry.get(sp.get("character") or sp.get("speaker_id")) if voice_registry else None
            sid = str(sp.get("speaker_id") or (reg["speaker_id"] if reg else "S1")).strip().upper()
            timbre = _clean_en(sp.get("timbre") or (reg["timbre"] if reg else VOICE_TIMBRE_PRESETS["young_female_clear"]), "speech.timbre")
            sp_mode = str(sp.get("mode") or "on_screen").lower()
            vo_phrase = " in an off-screen voiceover" if sp_mode in ("off_screen_vo", "inner_monologue", "narrator") else ""
            close_note = " Visible performers keep their lips completely closed." if vo_phrase else ""
            line += f" The speaker ({sid}), in {timbre}, says{vo_phrase}: <d>[{lang}]{raw_txt}</d>.{close_note}"
        shot_lines.append(line)

    soundscape = _clean_en(spec.get("soundscape") or "Natural ambient room tone and subtle physical foley continue throughout.", "soundscape")
    music = _clean_en(spec.get("non_diegetic_music") or "N/A", "non_diegetic_music")
    return "\n".join([
        "integrated_multimodal_description: " + " ".join(shot_lines),
        f"overall_soundscape: {soundscape}",
        f"non_diegetic_music: {music}",
    ])


def compile_h3_container_prompt(cuts, voice_registry=None, *, style="Realistic 35mm live-action cinema", apply_de_oil=True, soundscape="", non_diegetic_music="N/A"):
    """编译官方 MiniMax H3 多镜容器六段式提示词（4–15s 内打包 2–3 个连续切镜，每切绑定独立起始帧）。

    严格按 `references/dialects/minimax-h3.md#多镜容器每切一张关键帧` 生成：
      - 首行锚定句：`<Picture 1> aligns with the 0.00-second mark as the opening frame of [Shot 1]; <Picture 2> aligns with the ...`
      - `subject_definitions` / `summary` / `retention_analysis` / `detailed_description` / `overall_soundscape` / `non_diegetic_music`
    """
    if not isinstance(cuts, list) or not 2 <= len(cuts) <= 4:
        raise ValueError("Multi-cut container requires 2 to 4 cuts within 4-15s")
    total_dur = sum(float(c.get("duration") or 0.0) for c in cuts)
    if not 4.0 <= total_dur <= 15.0:
        raise ValueError(f"Multi-cut container total duration must stay within 4..15s, got {total_dur:.2f}s")

    align_parts = []
    sub_defs = []
    ret_lines = []
    shared_slots = []
    shared_pic_idx = len(cuts) + 1

    t_cursor = 0.0
    shot_blocks = []
    for idx, cut in enumerate(cuts, 1):
        kf_desc = _clean_en(cut.get("keyframe_desc") or "", f"cuts[{idx}].keyframe_desc")
        if not kf_desc:
            raise ValueError(f"cuts[{idx}] requires keyframe_desc (every cut in a container must bind its own keyframe)")
        align_parts.append(f"<Picture {idx}> aligns with the {t_cursor:.2f}-second mark as the {'opening ' if idx == 1 else ''}frame of [Shot {idx}]")
        sub_defs.append(f"<Picture {idx}> is the opening keyframe of [Shot {idx}], showing {kf_desc}.")
        ret_lines.append(f"<Picture {idx}> ([Shot {idx}] opening frame): fully_preserved - composition, pose, and lighting from <Picture {idx}> anchor [Shot {idx}].")

        act = _clean_en(cut.get("action") or "", f"cuts[{idx}].action")
        framing = _clean_en(cut.get("framing") or "medium close-up", f"cuts[{idx}].framing")
        raw_cam = str(cut.get("camera") or "push_tension").strip()
        cam_phrase = OFFICIAL_CAMERA_PHRASES.get(raw_cam, _clean_en(raw_cam, "camera"))
        de_oil_clause = f", {DE_OIL}" if apply_de_oil else ""
        if idx == 1:
            head = f"[Shot 1] {_clean_en(style, 'style')}; {framing}; the camera {cam_phrase}{de_oil_clause}; the shot opens from <Picture 1>, {act.rstrip('.')}."
        else:
            mm = int(t_cursor // 60)
            ss = t_cursor - mm * 60
            head = f"[Shot {idx}] At {mm:02d}:{ss:06.3f}, the shot cuts to {framing}; the camera {cam_phrase}; starting from <Picture {idx}>, {act.rstrip('.')}."
        sp = cut.get("speech")
        if isinstance(sp, dict) and str(sp.get("mode") or "none").lower() != "none":
            raw_txt = str(sp.get("text") or "").strip()
            lang = str(sp.get("language") or "Chinese").strip()
            reg = voice_registry.get(sp.get("character") or sp.get("speaker_id")) if voice_registry else None
            sid = str(sp.get("speaker_id") or (reg["speaker_id"] if reg else "S1")).strip().upper()
            timbre = _clean_en(sp.get("timbre") or (reg["timbre"] if reg else VOICE_TIMBRE_PRESETS["young_female_clear"]), "speech.timbre")
            head += f" {sid}, speaking in {timbre}, says: <d>[{lang}]{raw_txt}</d>."
        shot_blocks.append(head)
        t_cursor += float(cut.get("duration") or 0.0)

        for sh_slot in (cut.get("shared_slots") or []):
            key = (sh_slot.get("subject"), sh_slot.get("desc"))
            if key not in [(s.get("subject"), s.get("desc")) for s in shared_slots]:
                shared_slots.append({**sh_slot, "_pic": shared_pic_idx})
                shared_pic_idx += 1

    for sh in shared_slots:
        sub_num = int(sh.get("subject") or 1)
        pic_num = int(sh["_pic"])
        desc = _clean_en(sh.get("desc") or "", "shared_slot.desc")
        kind = str(sh.get("kind") or "character").lower()
        ret = _normalize_retention(kind, sh.get("retention"))
        sub_defs.append(f"<Subject {sub_num}> is {desc}, anchored in <Picture {pic_num}>.")
        ret_lines.append(f"<Subject {sub_num}> (appears across shots): {ret} - identity and appearance locked to <Picture {pic_num}>.")

    align_sentence = "; ".join(align_parts) + "."
    ss_txt = _clean_en(soundscape or "Continuous natural environment tone and synchronized foley across cuts.", "soundscape")
    mu_txt = _clean_en(non_diegetic_music or "N/A", "non_diegetic_music")
    return "\n".join([
        align_sentence,
        "subject_definitions:",
        *sub_defs,
        f"summary: [keyframe completion + reference generation] A {len(cuts)}-shot continuous multi-cut sequence spanning {total_dur:.2f} seconds.",
        "retention_analysis:",
        *ret_lines,
        "detailed_description:",
        f"Camera: multi-cut sequence over {total_dur:.2f}s{', ' + DE_OIL if apply_de_oil else ''}.",
        *shot_blocks,
        f"overall_soundscape: {ss_txt}",
        f"non_diegetic_music: {mu_txt}",
    ])
