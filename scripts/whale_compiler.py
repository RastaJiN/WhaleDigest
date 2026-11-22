#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate each H3 Ref2VA prompt using the same six-section contract."""
import argparse
import re
import sys

OFFICIAL_SECTIONS = (
    "subject_definitions", "summary", "retention_analysis",
    "detailed_description", "overall_soundscape", "non_diegetic_music",
)
_SECTION_RE = re.compile(r"^[ \t]*(" + "|".join(OFFICIAL_SECTIONS) + r"):[ \t]*(.*)$", re.MULTILINE)
_DIALOGUE_RE = re.compile(r"<d>(.*?)</d>", re.IGNORECASE | re.DOTALL)


def strip_dialogue(text):
    """Remove quoted speech while preserving line boundaries for structure checks."""
    return _DIALOGUE_RE.sub(lambda match: "\n" * match.group(0).count("\n"), text)


def parse_prompt_sections(text):
    """Return section values and structure errors; speech cannot declare fields."""
    positive = strip_dialogue(text)
    matches = list(_SECTION_RE.finditer(positive))
    errors, sections = [], {}
    if matches and positive[:matches[0].start()].strip():
        errors.append("结构错误：subject_definitions 之前不能夹带标题或工作指令")
    extra_fields = re.findall(r"^[ \t]*([a-z]+(?:_[a-z0-9]+)+):", positive, re.M)
    for name in sorted(set(extra_fields) - set(OFFICIAL_SECTIONS)):
        errors.append(f"结构错误：未知顶层字段 {name}:")
    if re.search(r"^[ \t]*(?:\[Visual Constraints\b|(?:Goal & Audio Contract|Audio rule|Voice discipline|MOTION FLOOR):)", positive, re.M | re.I):
        errors.append("结构错误：内部工作指令不能作为送模段头或尾块")
    for index, match in enumerate(matches):
        name = match.group(1)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(positive)
        value = (match.group(2) + positive[match.end():end]).strip()
        if name in sections:
            errors.append(f"结构错误：重复顶层字段 {name}:")
        else:
            sections[name] = value
        if not value:
            errors.append(f"结构错误：顶层字段 {name}: 不能为空")
    for name in OFFICIAL_SECTIONS:
        if name not in sections:
            errors.append(f"结构错误：missing H3 Ref2VA {name}")
    observed = [m.group(1) for m in matches]
    if len(observed) == len(OFFICIAL_SECTIONS) and set(observed) == set(OFFICIAL_SECTIONS) and tuple(observed) != OFFICIAL_SECTIONS:
        errors.append("结构错误：H3 Ref2VA 六个顶层字段顺序不一致")
    return sections, errors


def _validate_dialogue(text):
    errors, stack = [], []
    if re.search(r"<\s*/?\s*d\b[^>]*>", re.sub(r"</?d>", "", text, flags=re.IGNORECASE), re.IGNORECASE):
        errors.append("结构错误：台词标签只允许 <d> 和 </d>，不得使用属性或空格变体")
    for match in re.finditer(r"</?d>", text, re.IGNORECASE):
        if match.group(0).lower() == "<d>":
            if stack:
                errors.append("结构错误：台词 <d> 标签不得嵌套")
            stack.append(match.start())
        elif not stack:
            errors.append("结构错误：台词 </d> 缺少对应 <d>")
        else:
            stack.pop()
    if stack:
        errors.append("结构错误：台词 <d> 缺少闭合 </d>")
    utterances = list(_DIALOGUE_RE.finditer(text))
    speech_rows = [row for row in strip_dialogue(text).splitlines() if row.lstrip().upper().startswith("SPEECH:")]
    # Silent declarations ("SPEECH: No spoken dialogue; natural breathing only.") are not real dialogue.
    silent_rows = [row for row in speech_rows
                   if re.search(r"\bno\s+spoken\s+(?:dialogue|line|speech)\b", row, re.I)]
    real_rows = [row for row in speech_rows if row not in silent_rows]
    if len(utterances) > 1 or len(real_rows) != len(utterances) or (silent_rows and utterances):
        errors.append("对白错误：每个单镜请求只允许一条独立台词，换人请拆镜")
    for row in speech_rows:
        if re.search(r"\b(?:in unison|both voices|(?:both|they) (?:speak|say|recite) together)\b", row, re.I):
            errors.append("对白错误：单人台词不能要求两人齐读")
    for match in utterances:
        # Inspect the original quote before strip_dialogue removes it from the visual checks.
        label = re.search(r"<\s*/?\s*(?:Picture|Audio|Video|Subject)\s*\d+\s*>", match.group(1), re.I)
        if label:
            errors.append(f"对白错误：台词内不能包含素材或主体标签 {label.group(0)}")
        if not re.match(r"^\s*\[[^\]\r\n]+\]", match.group(1)):
            errors.append("结构错误：台词缺少独立语言标签，如 [Chinese]")
        speech = re.sub(r"^\s*\[[^\]\r\n]+\]\s*", "", match.group(1)).strip()
        if not speech:
            errors.append("错误：检测到空的真实台词（语言标签后没有正文）")
        if "\n" in match.group(1) or "\r" in match.group(1):
            errors.append("对白错误：逐字台词必须写在同一行")
        line_start = text.rfind("\n", 0, match.start()) + 1
        prefix = text[line_start:match.start()]
        if not re.fullmatch(r"[ \t]*SPEECH:[ \t]*(?:From[ \t]+[^<>\r\n]*?[ \t])?(?:ONLY[ \t]+)?(?:<Subject\s+\d+>|(?:The\s+)?(?:woman|man|speaker|narrator))[^<>\r\n]*?\b(?:says|asks|replies|whispers|shouts|speaks|calls|murmurs|cries|answers|states|declares|adds|continues)\b[^<>\r\n]*:[ \t]*", prefix, re.IGNORECASE):
            errors.append("结构错误：每句真实台词必须位于独立 SPEECH: 行，包含说话者和发声动词")
    return errors


_SUBJECT = r"<Subject ([1-9][0-9]*)>"
_PICTURE = r"<Picture ([1-9][0-9]*)>"
_SUBJECT_ROW = re.compile(r"^\s*" + _SUBJECT + r"\s*(?:\(S([1-9][0-9]*)\)\s*)?(?:is\b|:|=)(.*)$")
_VOICE_PAIR = re.compile(_SUBJECT + r"\s*\(S([1-9][0-9]*)\)")


def _binding_errors(sections):
    """Compare explicit bindings, not English prose, gaze, or screen direction."""
    errors, pictures, voices, declared = [], {}, {}, set()
    defs = sections.get('subject_definitions', '')
    for row in defs.splitlines():
        match = _SUBJECT_ROW.match(row)
        if not match:
            continue
        sid, _, description = match.groups()
        if sid in declared:
            errors.append(f"实体映射错误：<Subject {sid}> 重复定义")
        declared.add(sid)
        pictures[sid] = set(re.findall(_PICTURE, description))
    for sid, vid in _VOICE_PAIR.findall(defs):
        if sid in voices and voices[sid] != vid:
            errors.append(f"声源映射错误：<Subject {sid}> 的声音编号冲突")
        voices[sid] = vid
    # The local two-actor profile supplies a default when there is no explicit
    # vocal binding. H3 does not require that the two ID namespaces be equal.
    for sid in ('1', '2'):
        if sid in pictures.get(sid, set()):
            voices.setdefault(sid, sid)
    outside = '\n'.join(value for name, value in sections.items() if name != 'subject_definitions')
    for sid, vid in _VOICE_PAIR.findall(outside):
        if sid in voices and vid != voices[sid]:
            errors.append(f"声源映射错误：<Subject {sid}> 已绑定 S{voices[sid]}，不能改绑 S{vid}")
    # Only test an explicit identity claim. A secondary picture may guide lighting,
    # pose, costume, etc.; co-occurrence with a Subject is not evidence of rebinding.
    for row in sections.get('retention_analysis', '').splitlines():
        match = re.match(r'^\s*' + _SUBJECT + r'\s*:(.*)$', row)
        if match and pictures.get(match[1]):
            ref = re.search(r'\bidentity\b[^.;<>]*?\b(?:from|(?:anchored|locked) (?:in|to))\s*' + _PICTURE, match[2], re.I)
            if ref and ref[1] not in pictures[match[1]]:
                errors.append(f"实体映射错误：<Subject {match[1]}> 的身份参考 <Picture {ref[1]}> 与定义不符")
    return errors


def _lint_single_prompt(text):
    errors, warnings = [], []
    if not isinstance(text, str):
        return ["结构错误：prompt 必须是字符串"], []
    try:
        if len(text.encode("utf-8")) > 8000:
            errors.append("结构错误：单镜提示词超过 8000 UTF-8 字节")
    except UnicodeError:
        errors.append("结构错误：提示词不是有效 UTF-8")
    errors.extend(_validate_dialogue(text))
    positive = strip_dialogue(text)
    for token in re.finditer(r"<\s*/?\s*(?:Subject|Picture|Audio|Video)\s*[0-9]+\s*>", positive, re.I):
        if not re.fullmatch(r"<(?:Subject|Picture|Audio|Video) [1-9][0-9]*>", token[0]):
            errors.append(f"引用格式错误：{token[0]}；使用标准大小写、单空格与正整数")
    sections, structure_errors = parse_prompt_sections(text)
    errors.extend(structure_errors)
    visual = sections.get("detailed_description", "")
    errors.extend(_binding_errors(sections))
    if any(row.lstrip().upper().startswith("SPEECH:")
           for key, value in sections.items() if key != "detailed_description" for row in value.splitlines()):
        errors.append("对白错误：SPEECH: 只能在 detailed_description 内出现")
    cameras = re.findall(r"^[ \t]*Camera:[ \t]*(.*)$", positive, re.MULTILINE)
    visual_cameras = re.findall(r"^[ \t]*Camera:[ \t]*(.*)$", visual, re.MULTILINE)
    if len(cameras) != 1 or len(visual_cameras) != 1:
        errors.append("结构错误：每镜画面段必须恰有一个独立 Camera: 行")
    elif not visual_cameras[0].strip():
        errors.append("结构错误：Camera: 指令不能为空")
    if re.search(r"\baxis\b", positive, re.IGNORECASE):
        warnings.append("视角轴线词仅作兼容性警告，不阻断 H3 Ref2VA 正文")
    if not re.search(r"matte velvet skin finish|powdered dry|visible fine pores", positive, re.IGNORECASE):
        warnings.append("DE_OIL styling phrase is absent; H3 Ref2VA schema validation remains valid")

    # Material names and speech do not determine skin styling.
    skin_oil = re.findall(
        r"\b(?:glossy|greasy|glistening|shiny plastic|dewy)\s+(?:facial\s+)?(?:skin|face|complexion)\b"
        r"|\b(?:skin|face|complexion)\s+(?:is|looks|appears)\s+(?:glossy|greasy|glistening|shiny plastic|dewy)\b"
        r"|\b(?:oily face|vaseline skin)\b", positive, re.IGNORECASE)
    if skin_oil:
        errors.append(f"皮肤样式错误：检测到明确油光皮肤描述 {sorted(set(skin_oil))}")
    for phrase in ("matte bodily fluids", "dry squirting", "powdered saliva", "matte semen"):
        if phrase in positive.lower():
            errors.append(f"反物理词错误：检测到 '{phrase}'")

    definitions = sections.get("subject_definitions", "")
    declared_pictures = [int(v) for v in re.findall(r"<Picture\s+(\d+)>", definitions)]
    if not declared_pictures:
        errors.append("空间锚点错误：subject_definitions 中至少需要声明一个 <Picture N> 参考图")
    declared_subjects = set(re.findall(r"<Subject\s+(\d+)>", definitions))
    outside_definitions = "\n".join(value for key, value in sections.items() if key != "subject_definitions")
    undeclared = set(re.findall(r"<Subject\s+(\d+)>", outside_definitions)) - declared_subjects
    if undeclared:
        errors.append(f"实体映射错误：正文引用未声明 Subject {sorted(undeclared)}")
    picture_ids = [int(value) for value in re.findall(r"<Picture\s+(\d+)>", positive)]
    if any(not 1 <= value <= 9 for value in picture_ids):
        errors.append("参考槽位错误：Picture 编号必须在 1 到 9 之间")
    if "=== NEGATIVE ===" in positive:
        errors.append("正向提示词不得混入 === NEGATIVE === 块")
    sub_hits = re.findall(r"\b(subtitles?|captions?|on-screen text|burn-in text|text ban)\b", positive, re.IGNORECASE)
    if sub_hits:
        errors.append(f"正向字幕诱导词：{sorted(set(sub_hits))}")
    wreckage = re.findall(r"(?:,\s*,+|,\s*\.|;\s*,|\b(?:STRICTLY|TEXT BAN|BACKGROUND LOCK|FRAME EDGE)\s*[:;,.]\s*(?:\n|$))", positive)
    if wreckage:
        errors.append(f"破碎标点或空壳语法：{wreckage[:3]}")
    chinese = re.findall(r"[\u4e00-\u9fff]+", positive)
    if chinese:
        errors.append(f"正向描述在台词外含汉字：{chinese[:4]}")
    if "OUT OF FRAME" in positive.upper():
        errors.append("正向描述含 OUT OF FRAME，请使用具体的肯定式裁切描述")
    if re.search(r"At 0\.00s,\s*(?:wide|mcu|cu|macro|hip|face)\s*,", positive, re.IGNORECASE):
        errors.append("相机描述不得直接复读景别与机位工程代号")
    line_hits = re.findall(r"\b(line|lines|line-up)\b", visual, re.IGNORECASE)
    risky_lines = re.findall(r"\b(?:(?:red|blue|green|dashed|dotted|guide|guidance|composition|overlay|overlaid|drawn|graphic|reference|alignment|horizontal|vertical)\s+lines?|line-up|lines?\s+(?:overlay|across the frame|on the screen))\b", visual, re.IGNORECASE)
    if risky_lines:
        warnings.append(f"构图线词请复核：{sorted(set(risky_lines))}；物体纹理与后期叠线不能仅由词形判断")
    elif line_hits:
        warnings.append(f"构图线词兼容性建议：{sorted(set(line_hits))}；应确认其描述可见物体还是叠加线")
    # A visible instrument is valid visual content; abstract sound belongs in audio.
    sound_hits = re.findall(r"\b(bgm|background music|music swells|music plays|echoes)\b", visual, re.IGNORECASE)
    if sound_hits:
        errors.append(f"画面段混入抽象声响描述 {sorted(set(sound_hits))}，请移入 overall_soundscape")
    for line in visual.splitlines():
        if line.strip().startswith("[Shot") and ";" not in line:
            warnings.append("镜行建议用分号分隔相机与动作描述")
    if re.search(r"\b(very slowly|extremely|somehow|suddenly)\b", visual, re.IGNORECASE):
        warnings.append("建议把模糊程度词改为具体的距离与时间")
    return errors, warnings


def lint_whale_prompt(text):
    errors, warnings = _lint_single_prompt(text)
    if isinstance(text, str) and "```" in text:
        errors.append("任务 prompt 必须是原文，不能包含 Markdown 代码围栏")
    return errors, warnings


def lint_task_prompt(shot, batch=None):
    """Validate immutable model text against this shot's actual reference inventory."""
    if __package__:
        from .whale_audio_contract import resolve_audio_contract
    else:
        from whale_audio_contract import resolve_audio_contract
    prompt = shot.get('prompt')
    errors, warnings = lint_whale_prompt(prompt)
    if not isinstance(prompt, str):
        return errors, warnings
    try:
        audio = resolve_audio_contract(shot, batch)
    except ValueError as exc:
        return errors + [str(exc)], warnings
    images = shot.get('ref_images')
    limits = {'Picture': len(images) if isinstance(images, list) else 0,
              'Audio': len(audio['ref_audios']), 'Video': 0}
    for kind, number in re.findall(r'<(Picture|Audio|Video) ([0-9]+)>', strip_dialogue(prompt)):
        if not 1 <= int(number) <= limits[kind]:
            message = f'参考槽位错误：本镜没有绑定 <{kind} {number}>'
            if message not in errors:
                errors.append(message)
    return errors, warnings


def lint_whale_document(text):
    """Validate all text fences and reject unfinished fences instead of skipping them."""
    if "```" not in text:
        return lint_whale_prompt(text)
    blocks, current, language, opened = [], [], None, False
    errors, warnings = [], []
    for line in text.splitlines():
        fence = re.fullmatch(r"[ \t]*```([A-Za-z0-9_-]*)[ \t]*", line)
        if fence:
            if not opened:
                language, current, opened = fence.group(1).lower(), [], True
            elif fence.group(1):
                errors.append("Markdown 代码围栏嵌套或缺少闭合")
            else:
                if language in ("", "text"):
                    blocks.append("\n".join(current))
                opened = False
            continue
        if opened:
            current.append(line)
    if opened:
        errors.append("Markdown 提示词代码块未闭合，末镜不能跳过检查")
    if not blocks:
        errors.append("Markdown 文档中没有完整的 text 提示词代码块")
    for index, block in enumerate(blocks, 1):
        errs, warns = lint_whale_prompt(block)
        errors.extend(f"block {index}: {item}" for item in errs)
        warnings.extend(f"block {index}: {item}" for item in warns)
    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description="H3 Ref2VA six-section prompt validator")
    parser.add_argument("file")
    args = parser.parse_args()
    try:
        with open(args.file, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeError) as exc:
        print(f"读取文件失败: {exc}")
        return 1
    errors, warnings = (lint_whale_document(text) if args.file.lower().endswith(".md") else lint_whale_prompt(text))
    for warning in warnings:
        print("WARNING: " + warning)
    for error in errors:
        print("ERROR: " + error)
    print("FAIL" if errors else "PASS (文本结构通过；画面效果尚需实测)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
