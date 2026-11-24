#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
吞鲸宝典 v4.6.3 · 全剧集视听导演调度与自动摄影拆镜引擎 (WhaleDigest Scene & Auto-DP Engine v4.6.3)

核心特性：
1. 全剧集弹性时长（60s ~ 360s 任意定）與自由文/肉节奏：
   - 原生支持 8 大非肉戏导演调度原语（`env_establish`, `blocking_2s`, `srs_male`, `srs_female`, `prop_insert`, `cut_insert`, `spatial_shift`, `outro_solo`）与 55 套肉戏真源无缝混排
   - 正反打（`srs_male` 男方施压正打 ⇄ `srs_female` 女方承受反打）贯穿全片文戏、前戏与肉戏
2. Auto-DP 全自动电影摄影指导（告别死气沉沉的三脚架固定镜）：
   - 内置 12 种竖屏（9:16）受控电影运镜（Z轴慢推/慢拉、Y轴垂直上摇/下摇、前景虚焦过肩微移、10度微弧视差、呼吸感手持微晃、仰俯角压迫）
   - 严禁连续两镜静态死锁，自动编排心电图景别与动态运镜波浪
3. 空间图池单槽轮换法（Multi-View Pool, Single-View Per Shot）：
   - 每镜场景槽（`<Picture 3>`）只挂 1 张最匹配当前机位/景别的空间底图（主全景 `scene_main.png` / 立面墙镜 `scene_wall.png` / 承托面近景 `scene_close.png`），绝不多图混喂，同时永不断开 `<Picture 3>` 空间锚点！
4. 动态 LoRA 分级与 9图3音槽位输出：
   - 自动在 `批量任务.json` 为每镜输出 `lora_mystic_name: "MysticXXX_MMH3-V5-ref2va.safetensors"` 与动态权重（文戏/穿衣/空镜 `0.0`，前戏/肉戏 `0.45`）
   - 自动输出 `ref_audios: ["female_voice.wav", "male_voice.wav"]` 锁定全集声线
5. 全集总帧数同余配平 `(F - 5N) % 17 == 0` 与接戏过继（`承接：前镜末态 → 本镜起态`）
"""

import json, os, argparse, re
from pathlib import Path
import whale_blocking as blocking
import whale_shot_facts as shot_facts
import whale_pacing as pacing
from whale_core import (
    load_poses, DE_OIL, NEG, FINISH_IDS, ORAL_ONLY, FOREPLAY, STAGING_IDS, TEASE_IDS, DRAMATIC_BODY_IDS,
    single_shot_prompt, parse_audio_fx_mode, dialogue_needed_seconds, resolve_speaker
)

BASE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(BASE, "..", "references")

# ── 景别库（分镜表用中文可读，送模提示词强制使用纯英文 SHOT_SIZES_EN）──────────────────────────
SHOT_SIZES = {
    "wide":   "中景（腰以上到膝，交代空间轴线与肢体关系）",
    "mcu":    "中近景（腰胯到胸口，主体动态与受力清晰可读）",
    "cu":     "近景（肩颈至面部或局部受力特写）",
    "macro":  "微距（结合部/指节抓握/局部信物，纯细节特写）",
    "hip":    "腰胯特写（大腿中段到肋下，专攻腰臀冲撞）",
    "face":   "面部特写（眼神交锋/咬唇/泪痕/失神微表情）",
}

SHOT_SIZES_EN = {
    "wide":   "medium-wide shot framed from knees to shoulders",
    "mcu":    "medium close-up framed from hips to chest",
    "cu":     "close-up framed on upper torso, collarbones, and neck",
    "macro":  "extreme macro close-up locked on the contact area",
    "hip":    "pelvic close-up framed from mid-thigh to lower ribs",
    "face":   "tight facial close-up locked on eyes, jaw, and lips",
}

# ── Auto-DP 12 种竖屏（9:16）受控电影运镜库（破除死板三脚架）──────────────────────────
CAMS = {
    "push_tension":    "压迫感慢推（Z轴向前推进15cm，聚焦情绪与发力）",
    "pull_reveal":     "抽离揭示慢拉（Z轴向后拉远18cm，交代空间关系）",
    "tilt_up_desire":  "竖屏垂直上摇（Y轴从腰手缓摇至眼神，展现纵向曲线）",
    "tilt_down_impact":"竖屏垂直下摇（Y轴从紧咬嘴唇下摇至受力接触点）",
    "ots_depth":       "深景深过肩微移（前景虚焦肩部占20%，横向微移6cm撑开纵深）",
    "arc_subtle":      "微弧度立体偏转（10度侧向微弧滑动12cm，制造背景立体视差）",
    "handheld_breath": "呼吸感手持微晃（2cm有机呼吸律动，跟随肉体节奏）",
    "low_upward":      "微仰权力压迫（12度竖屏防变形微仰角向上仰拍并慢推10cm）",
    "high_downward":   "微俯脆弱承受（15度竖屏防变形微俯角向下俯拍并微降8cm）",
    "static_side":     "90度侧向定轴（三脚架稳固锁定，靠纯肉体冲撞带动画面）",
    "static_rear":     "后斜向定轴（三脚架稳固锁定，展现背部与臀胯发力）",
    "low_hip":         "低机位贴腰跟拍（贴近腰胯高度，随冲撞微幅呼吸）",
    # 兼容旧代号映射
    "static_front":    "正面中轴慢推（平视缓推10cm）",
    "ots":             "深景深过肩微移（前景虚焦肩部占20%）",
    "high_angle":      "微俯脆弱承受（15度竖屏防变形微俯角向下俯拍）",
    "slow_push":       "压迫感慢推（Z轴向前推进15cm）",
    "follow_soft":     "微弧度立体跟随（侧向柔和跟随10cm）",
}

CAMS_EN = {
    "push_tension":    "eye-level angle, slow dolly push-in sliding forward 15 cm over four seconds tightening on the subject",
    "pull_reveal":     "eye-level angle, slow dolly pull-back retreating 18 cm over four seconds revealing spatial depth",
    "tilt_up_desire":  "low-to-eye angle, smooth vertical tilt-up panning 18 cm upward along the torso to the eyes over three seconds",
    "tilt_down_impact":"eye-to-low angle, smooth vertical tilt-down panning 18 cm from the face down to the contact point over three seconds",
    "ots_depth":       "over-the-shoulder angle with soft-focus foreground shoulder occupying 20% frame edge, subtle 6 cm lateral drift over three seconds",
    "arc_subtle":      "side-oblique angle, subtle 10-degree lateral dolly arc shifting 12 cm sideways over four seconds for parallax depth",
    "handheld_breath": "intimate close perspective, organic handheld camera with subtle 2 cm breathing micro-sway synchronized with body rhythm",
    "low_upward":      "subtle 12-degree low-angle upward perspective preserving natural vertical body proportions, slow 10 cm push-in over three seconds",
    "high_downward":   "subtle 15-degree high-angle downward perspective preserving natural vertical body proportions, subtle 8 cm vertical descent over three seconds",
    "static_side":     "90-degree side profile angle, camera locked steady on a heavy tripod",
    "static_rear":     "rear-oblique angle, camera locked steady on a heavy tripod",
    "low_hip":         "low-angle hip-level perspective, subtle 4 cm forward tracking with pelvic rhythm",
    # 兼容旧代号
    "static_front":    "eye-level front angle, slow 10 cm dolly push-in over three seconds",
    "ots":             "over-the-shoulder angle with foreground shoulder in soft focus, subtle 6 cm lateral drift",
    "high_angle":      "subtle 15-degree high-angle downward perspective, subtle 8 cm vertical descent",
    "slow_push":       "eye-level angle, camera pushes in sliding forward 12 cm over three seconds",
    "follow_soft":     "side-oblique angle, camera tracks smoothly moving 10 cm over three seconds",
}

# ── 横屏（16:9）景别库：与竖屏语义完全不同，横屏靠「横向空间关系」而非「纵向身体」构图 ──────────
SHOT_SIZES_LANDSCAPE = {
    "wide":   "全景（两人横向并排交代左右空间轴线与环境）",
    "mcu":    "中近景（双人半身左右同框，主体横向关系清晰）",
    "cu":     "近景（单人上半身，交代横向对视/施压）",
    "macro":  "微距（结合部/指节抓握/局部信物，纯细节特写）",
    "hip":    "腰胯特写（双人腰胯横向同框，专攻冲撞轨迹）",
    "face":   "面部特写（横向眼神交锋/咬唇/微表情）",
}

SHOT_SIZES_EN_LANDSCAPE = {
    "wide":   "wide establishing shot framing both bodies side-by-side to reveal left-to-right spatial axis and environment",
    "mcu":    "medium close-up framing both torsos side-by-side in a horizontal two-shot",
    "cu":     "close-up framing a single subject's upper torso and face against a horizontal backdrop",
    "macro":  "extreme macro close-up locked on the contact area",
    "hip":    "pelvic two-shot framing both hips and the junction horizontally from mid-thigh to lower ribs",
    "face":   "tight facial close-up on eyes, jaw, and lips against a shallow horizontal background",
}

# ── 横屏（16:9）机位描述（中文可读 + 英文送模）：横屏靠水平推轨/左右摇/横向过肩，非竖屏的垂直上下摇 ──
CAMS_LANDSCAPE = {
    "push_tension":   "横向压迫慢推（Z轴向前推进15cm，聚焦情绪与发力）",
    "pull_reveal":    "横向抽离慢拉（Z轴向后拉远18cm，交代左右空间关系）",
    "tilt_up_desire": "水平上移微摇（Y轴略上扬，展现横向曲线与眼神）",
    "tilt_down_impact":"水平下移微摇（Y轴略下压至受力接触点）",
    "ots_depth":      "横向过肩微移（前景虚焦肩部占15%，横向微移8cm撑开左右纵深）",
    "arc_subtle":     "横屏微弧偏转（8度侧向微弧滑动12cm，制造左右视差）",
    "handheld_breath":"呼吸感手持微晃（2cm有机律动，跟随肉体节奏）",
    "low_upward":     "横屏微仰（10度防变形微仰角，水平慢推10cm）",
    "high_downward":  "横屏微俯（12度防变形微俯角，水平微降8cm）",
    "static_side":    "横屏90度侧向定轴（三脚架稳固锁定，双人左右同框靠冲撞带动）",
    "static_rear":    "后斜向定轴（三脚架稳固锁定，展现背部与臀胯横向发力）",
    "low_hip":        "低机位贴腰水平跟拍（贴近腰胯高度，随冲撞微幅呼吸）",
    "static_front":   "正面中轴慢推（平视缓推10cm）",
    "ots":            "横向过肩微移（前景虚焦肩部占15%）",
    "high_angle":     "横屏微俯（12度防变形微俯角，水平微降）",
    "slow_push":      "横向慢推（Z轴前推15cm）",
    "follow_soft":    "横向柔和跟随（侧向跟随10cm）",
    "pan_left_right": "水平横摇（左右轻微摇移12cm交代双人横向关系）",
    "track_lateral":  "横向推轨（沿轴线左右平移15cm跟随交合节奏）",
}

CAMS_EN_LANDSCAPE = {
    "push_tension":   "eye-level wide angle, slow lateral dolly push-in sliding forward 15 cm tightening on both subjects",
    "pull_reveal":    "eye-level wide angle, slow dolly pull-back retreating 18 cm revealing left-to-right spatial depth",
    "tilt_up_desire": "low-to-eye angle, smooth vertical tilt-up pedestal shifting 12 cm upward along the torso over three seconds",
    "tilt_down_impact":"eye-to-low angle, smooth vertical tilt-down shifting 12 cm from the face down to the contact point over three seconds",
    "ots_depth":      "over-the-shoulder angle with soft-focus foreground shoulder occupying 15% frame edge, subtle 8 cm lateral drift over three seconds",
    "arc_subtle":     "side-oblique angle, subtle 8-degree lateral dolly arc shifting 12 cm over four seconds for horizontal parallax",
    "handheld_breath":"intimate close perspective, organic handheld camera with subtle 2 cm breathing micro-sway synchronized with body rhythm",
    "low_upward":     "subtle 10-degree low-angle perspective preserving natural body proportions, slow 10 cm horizontal push-in",
    "high_downward":  "subtle 12-degree high-angle perspective preserving natural body proportions, subtle 8 cm vertical crane descent",
    "static_side":    "90-degree side profile angle, tripod locked, both subjects framed left-to-right in a horizontal two-shot",
    "static_rear":    "rear-oblique angle, tripod locked, showing the back and hip drive in horizontal composition",
    "low_hip":        "low-angle hip-level perspective, subtle 4 cm horizontal tracking with pelvic rhythm",
    "static_front":   "eye-level front angle, slow 10 cm dolly push-in over three seconds",
    "ots":            "over-the-shoulder angle with foreground shoulder in soft focus, subtle 8 cm lateral drift",
    "high_angle":     "subtle 12-degree high-angle perspective, subtle 8 cm vertical crane descent",
    "slow_push":      "eye-level angle, camera pushes in sliding forward 12 cm over three seconds",
    "follow_soft":    "side-oblique angle, camera tracks smoothly moving 10 cm over three seconds",
    "pan_left_right": "eye-level angle, smooth horizontal pan shifting 12 cm left-to-right to reveal the two-subject relationship",
    "track_lateral":  "lateral tracking shot gliding 15 cm side-to-side along the action axis in time with the thrust rhythm",
    "static":         "eye-level angle, tripod locked with steady framing",
    "static_top_90":  "top-down 90-degree overhead angle, tripod locked framing the bodies flat against the surface in horizontal composition",
    "static_top":     "top-down overhead angle, tripod locked framing the bodies against the surface",
}

# 横屏单人特写机位措辞：避免单人镜复用双人横屏措辞造成「single subject」与「both subjects」自相矛盾
CAMS_EN_LANDSCAPE_SOLO = {
    "static_side":    "90-degree side profile angle, tripod locked, single subject framed against a horizontal backdrop",
    "static_rear":    "rear-oblique angle, tripod locked, single subject seen from behind in horizontal composition",
    "static_front":   "eye-level front angle, tripod locked with steady single-subject framing",
    "pan_left_right": "eye-level angle, smooth horizontal pan shifting 12 cm across the single subject",
    "push_tension":   "eye-level angle, slow lateral dolly push-in sliding forward 12 cm tightening on the single subject",
}

# ── 画幅工具函数：aspect 参数归一化 + 分辨率映射 + 字典选择 ──
ASPECT_RES = {
    "9:16":  {"width": 928, "height": 1664, "label": "9:16 (Portrait Widescreen)"},
    "16:9":  {"width": 1664, "height": 928, "label": "16:9 (Widescreen)"},
    "1:1":   {"width": 1280, "height": 1280, "label": "1:1 (Square)"},
}

def normalize_aspect(aspect):
    """把任意 aspect 字符串归一化成 '9:16' / '16:9' / '1:1' 三档之一，默认竖屏 9:16。"""
    a = (aspect or "9:16").strip().lower()
    if a in ("landscape", "widescreen", "wide", "横屏", "横"):
        return "16:9"
    if a in ("portrait", "竖屏", "竖"):
        return "9:16"
    if "9:16" in a or a in ("9:16", "portrait", "竖屏", "竖"):
        return "9:16"
    if "16:9" in a or a in ("16:9", "landscape", "横屏", "横", "wide"):
        return "16:9"
    if "1:1" in a or a in ("1:1", "square", "方"):
        return "1:1"
    raise ValueError(f"Unsupported aspect: {aspect!r}")

def is_landscape(aspect):
    return normalize_aspect(aspect) == "16:9"

def pick_dict(landscape, landscape_map, portrait_map):
    """按横/竖屏选择对应字典。横屏时若某 key 在横屏字典中缺失，回退竖屏字典。"""
    if not landscape:
        return portrait_map
    merged = dict(portrait_map)
    merged.update(landscape_map)
    return merged


# ── Auto-DP 导演调度与体位拆镜配方（内嵌正反打 srs_male / srs_female 与动态运镜）──────────────────
POSE_SHOT_PLAN = {
    # 8 大非肉戏导演调度原语（单人镜 srs_male 严禁默认配过肩 ots_depth，防无异性参考图裂出同性双人）
    "env_establish":        [("wide", "pull_reveal")],
    "blocking_2s":          [("wide", "arc_subtle"), ("mcu", "push_tension")],
    "srs_male":             [("cu", "push_tension")],
    "srs_female":           [("face", "high_downward")],
    "prop_insert":          [("macro", "push_tension")],
    "cut_insert":           [("macro", "tilt_down_impact")],
    "spatial_shift":        [("mcu", "arc_subtle")],
    "outro_solo":           [("cu", "pull_reveal")],

    # 10 大暧昧挑逗与诱惑肢体动作 (Seductive & Tease Body Language)
    "trace_collar":         [("cu", "tilt_down_impact"), ("face", "ots_depth")],
    "ear_whisper_tease":    [("cu", "push_tension"), ("face", "handheld_breath")],
    "shoulder_strap_slide": [("mcu", "tilt_up_desire"), ("cu", "push_tension")],
    "leg_brush_tease":      [("mcu", "tilt_up_desire")],
    "neck_nuzzle_inhale":   [("cu", "push_tension"), ("face", "high_downward")],
    "waist_pull_collision": [("mcu", "arc_subtle"), ("cu", "ots_depth")],
    "lip_thumb_wipe":       [("face", "push_tension")],
    "tie_pull_seduce":      [("cu", "low_upward"), ("face", "ots_depth")],
    "back_arch_lean":       [("mcu", "tilt_up_desire")],
    "finger_interlock_pin": [("macro", "push_tension")],

    # 14 大权力对峙、抗拒与情绪宣泄肢体动作 (Dramatic Conflict & Emotional Body Language)
    "chin_lift":            [("cu", "low_upward"), ("face", "high_downward")],
    "wrist_pin":            [("cu", "tilt_down_impact")],
    "loosen_tie":           [("mcu", "push_tension")],
    "wall_caging":          [("mcu", "arc_subtle"), ("cu", "ots_depth")],
    "nape_grip":            [("cu", "ots_depth")],
    "chest_push":           [("mcu", "push_tension")],
    "step_back_guard":      [("mcu", "pull_reveal")],
    "turn_evade":           [("face", "high_downward")],
    "clutch_fabric":        [("macro", "push_tension")],
    "grab_lapel":           [("cu", "handheld_breath")],
    "collapse_sob":         [("cu", "high_downward")],
    "present_item":         [("cu", "tilt_down_impact")],
    "rub_temple":           [("cu", "pull_reveal")],
    "fix_attire":           [("cu", "pull_reveal")],

    # 口爱系：建立 ➔ 男正打低头审视 ➔ 微距吞吐
    "bj":              [("mcu", "tilt_down_impact"), ("cu", "low_upward"), ("macro", "handheld_breath")],
    "squat_bj":        [("mcu", "high_downward"), ("cu", "handheld_breath")],
    "prone_bj":        [("mcu", "high_downward"), ("cu", "push_tension")],
    "deepthroat":      [("mcu", "push_tension"), ("macro", "handheld_breath")],
    "head_thrust":     [("mcu", "low_upward"), ("cu", "handheld_breath")],
    "facefuck":        [("mcu", "handheld_breath"), ("cu", "high_downward")],
    "sixty_nine":      [("wide", "arc_subtle"), ("mcu", "static_side")],
    "tip_lick":        [("macro", "push_tension")],
    "ball_lick":       [("macro", "push_tension")],
    "penis_slap":      [("cu", "handheld_breath")],
    "titjob":          [("mcu", "high_downward"), ("cu", "push_tension")],
    "handjob":         [("cu", "tilt_up_desire"), ("macro", "handheld_breath")],

    # 前戏/指插/舔阴：动态推摇与面部反打结合
    "fingering":       [("mcu", "high_downward"), ("macro", "push_tension"), ("face", "handheld_breath")],
    "clit_tease":      [("macro", "push_tension"), ("face", "high_downward")],
    "cunnilingus":     [("mcu", "high_downward"), ("cu", "push_tension"), ("face", "handheld_breath")],
    "sofa_cunni":      [("wide", "arc_subtle"), ("mcu", "high_downward")],
    "kiss_fondle":     [("mcu", "arc_subtle"), ("cu", "ots_depth")],
    "kiss_pin":        [("mcu", "push_tension"), ("face", "ots_depth")],
    "kiss_force":      [("cu", "ots_depth"), ("face", "handheld_breath")],
    "kiss_her":        [("mcu", "push_tension")],
    "breast_rub":      [("mcu", "tilt_up_desire"), ("cu", "ots_depth")],
    "nipple_lick":     [("macro", "push_tension"), ("face", "high_downward")],
    "undress":         [("mcu", "tilt_up_desire"), ("cu", "push_tension")],

    # 主力交合：错开各体位首拍/反应拍机位梯度（static_side / arc_subtle / high_downward / low_upward / handheld_breath / push_tension），
    # 避免多体位连用时构图单一；同时禁用 face 暗拆、后入正背 static_rear、后入 ots_depth 与站立 wide
    "missionary":      [("mcu", "high_downward"), ("hip", "low_hip"), ("cu", "handheld_breath")],
    "missionary_legup":[("mcu", "push_tension"), ("hip", "low_hip"), ("cu", "high_downward")],
    "doggy":           [("mcu", "arc_subtle"), ("hip", "low_hip"), ("cu", "high_downward")],
    "table_doggy":     [("mcu", "static_side"), ("hip", "low_hip"), ("cu", "handheld_breath")],
    "stand_doggy_wall":[("mcu", "static_side"), ("hip", "low_hip"), ("cu", "arc_subtle")],
    "stand_bend_doggy":[("mcu", "arc_subtle"), ("hip", "low_hip")],
    "bedside_stand":   [("mcu", "low_upward"), ("hip", "low_hip")],
    "anal":            [("mcu", "static_side"), ("hip", "low_hip")],
    "cowgirl":         [("mcu", "low_upward"), ("hip", "low_hip"), ("cu", "push_tension")],
    "cowgirl_upright": [("mcu", "tilt_up_desire"), ("cu", "low_upward")],
    "reverse_cowgirl": [("mcu", "arc_subtle"), ("hip", "low_hip")],
    "squat_cowgirl":   [("mcu", "low_upward"), ("hip", "low_hip")],
    "lap_sit_back":    [("mcu", "ots_depth"), ("hip", "low_hip")],
    "stand_face_hug":  [("mcu", "arc_subtle"), ("cu", "handheld_breath")],
    "carry_insert":    [("mcu", "tilt_up_desire"), ("cu", "handheld_breath")],
    "face_insert":     [("mcu", "arc_subtle"), ("hip", "low_hip")],
    "side_face":       [("mcu", "high_downward"), ("hip", "low_hip")],
    "pov_insert":      [("mcu", "high_downward"), ("hip", "push_tension")],

    # 绝顶清算：微距冲击 ➔ 面部失神反打 ➔ 慢拉余韵
    "creampie":        [("macro", "push_tension"), ("face", "handheld_breath"), ("mcu", "pull_reveal")],
    "cum_face":        [("cu", "high_downward"), ("face", "pull_reveal")],
    "cum_chest":       [("cu", "tilt_down_impact"), ("mcu", "pull_reveal")],
    "cum_belly":       [("cu", "high_downward"), ("mcu", "pull_reveal")],
    "cum_butt":        [("cu", "push_tension"), ("mcu", "pull_reveal")],
}


def load_poses_local():
    return load_poses()


def plan_shot(pid, poses):
    plan = POSE_SHOT_PLAN.get(pid) or [("mcu", "arc_subtle")]
    return plan


def speaker_cue(label):
    """Parse the role separately from optional performance or off-screen direction."""
    m = re.fullmatch(r"\s*([^()（）]+?)(?:\s*[（(]([^()（）]*)[）)])?\s*", label)
    if not m:
        raise ValueError(f"说话人标签无效：{label!r}")
    return resolve_speaker(m[1]), (m[2] or "").strip()


def is_voiceover_cue(cue):
    return bool(re.search(r"(?:画外音|内心|心声|独白|\b(?:OS|VO|voiceover)\b)", cue, re.I))


def prepare_dialogue_shots(shots, lines, want_total):
    """Explicit shot numbers are binding; unnumbered turns skip empty shots and inserts."""
    line_map = {}
    turns = [s.strip() for s in re.split(r"[|\r\n]+", lines or "") if s.strip()]
    sequential = None
    available = iter(i for i, shot in enumerate(shots, 1) if shot.get("pose") not in (
        "env_establish", "empty_cut", "corridor_cut", "prop_insert", "cut_insert"))
    for item in turns:
        index = re.match(r"^(?:shot\s*)?(\d+)\s*[:：]\s*", item, re.I)
        if sequential is not None and sequential != (index is None):
            raise ValueError("带镜号和顺排台词不能混用")
        sequential = index is None
        number = int(index[1]) if index else next(available, 0)
        if not 1 <= number <= len(shots):
            raise ValueError("Dialogue shot index is outside the scene or no speaking shot remains")
        if number in line_map:
            raise ValueError(f"第 {number} 镜重复分配台词；请将下一句放在另一镜")
        value = item[index.end():] if index else item
        parts = re.split(r"[:：]", value, maxsplit=1)
        if len(parts) == 2:
            role, words = parts[0].strip(), parts[1].strip()
            actor, cue = speaker_cue(role)
        elif index or len(turns) == 1:
            # Preserve unlabelled legacy inputs. A reverse shot has just one visible performer.
            actor, cue, words = (2 if shots[number-1].get("pose") == "srs_male" else 1), "", value.strip()
        else:
            raise ValueError("顺排多句对白必须逐句标明说话人")
        if not words:
            raise ValueError(f"第 {number} 镜台词为空")
        role = "女子A" if actor == 1 else "男子A"
        line_map[number] = (f"{role}({cue})" if cue else role, words)
    for number, shot in enumerate(shots,1):
        d = shot.get('dialogue')
        if d is not None:
            if turns: raise ValueError('源稿对白已绑定原说话人；不能用 --lines 重写')
            label = d['actor'] + ('('+d['cue']+')' if d['cue'] else '')
            line_map[number] = (label, d['text'])
    expanded, mapped = [], {}
    for old_index, shot in enumerate(shots, 1):
        if old_index not in line_map:
            expanded.append(shot)
            continue
        speaker, text = line_map[old_index]
        if shot.get("pose") == "env_establish":
            raise ValueError("An empty establishing shot cannot carry character dialogue")
        if shot.get("pose") in ("srs_male", "srs_female"):
            actor, cue = speaker_cue(speaker)
            desired = shot["pose"] if is_voiceover_cue(cue) else ("srs_female" if actor == 1 else "srs_male")
            if shot["pose"] != desired:
                if shot.get("blocking_state", {}).get("adopted"):
                    raise ValueError(f"SHOT-{old_index:02d} 已采用的取景与画内说话人冲突；请回分镜改取景或标注画外音")
                original_pose = shot["pose"]
                entry = load_poses()[desired]
                shot = dict(shot, pose=desired, pose_zh=entry.get("nameZh", desired), pose_en=entry.get("nameEn", desired),
                            text=(entry.get("beatsZh") or [""])[0], text_en=(entry.get("beatsEn") or [""])[0], original_pose=original_pose)
        chunks, chunk = [], ""
        for character in re.findall(r"[A-Za-z0-9]+(?:[’'-][A-Za-z0-9]+)*|\s+|.", text, re.S):
            if chunk and dialogue_needed_seconds(chunk + character) > 12.25:
                chunks.append(chunk)
                chunk = character
            else:
                chunk += character
        if chunk:
            chunks.append(chunk)
        if len(chunks) > 1 and shot.get('action_steps'):
            raise ValueError('Dialogue would replay a reviewed action/exit. Split it in the storyboard first.')
        for part_index, part in enumerate(chunks):
            current = dict(shot)
            if 'dialogue' in shot and len(chunks)>1:
                current['dialogue'] = dict(shot['dialogue'], part=part_index, part_text=part)
            current["required_sec"] = max(min(float(shot.get("required_sec") or 0), 12.25), dialogue_needed_seconds(part))
            if part_index:
                current["dialogue_continuation"] = True
                if "blocking_state" in current:
                    p = current["blocking_state"]
                    current["blocking_state"] = dict(p, start=p["end"], source="同场继承", action="", reframe="", prior_left=p["screen_left"])
            expanded.append(current)
            mapped[len(expanded)] = (speaker, part)
    shots[:] = expanded
    _, actual = allocate_exact_h3_frames(shots, want_total)
    return mapped, actual


def allocate_exact_h3_frames(shots, want_total_sec):
    """
    全集总帧同余配平算法（对白 + 画面双驱动，不按姿势档位查表）：
    1. 每镜必须有最小可见时长 `required_sec`（由「该镜对白时长」与「画面动作可见时长」取大者决定）
    2. 每镜帧长 f_i = 5 + 17 * k_i (k_i >= 2)，向上对齐到能容纳 required_sec 的合法帧长
    3. 对白太长超过单镜机器上限(12s)时，由上层拆镜（说话镜 + 听者反应镜），此处只保证单镜 ≤12.25s
    4. 全集总帧自动对齐到最近合法同余值（5*N + 17*sum(k_i)），不强行均摊到每个镜头
    """
    n_shots = len(shots)
    if n_shots == 0:
        return shots, 0.0

    # 1. 每个镜头的最小可见时长：由对白时长 + 画面动作可见时长决定
    #    shot 已带 required_sec（由调用方按对白/画面算好），缺失时按画面类型给保守基准
    for s in shots:
        if "required_sec" not in s or s["required_sec"] is None:
            pid = s.get("pose", "")
            sz = s.get("size", "")
            # 画面动作可见时长基准：短标点/插入镜短，主力交合/长台词长
            if pid in ("cut_insert", "prop_insert"):
                base = 1.6
            elif s.get("type") == "transition":
                base = 3.5
            elif sz in ("macro",):
                base = 2.3
            elif sz in ("face", "cu") or pid in ("srs_male", "srs_female"):
                base = 3.0
            else:
                base = 4.5
            s["required_sec"] = base

    # 2. 把每个 required_sec 向上对齐到合法帧长 f=5+17k → 得最小 k
    def sec_to_k(sec):
        # 找最小 k>=2 使 (5+17k)/24 >= sec
        k = 2
        while (5 + 17 * k) / 24.0 < sec and k < 17:
            k += 1
        if not __import__("math").isfinite(sec) or sec < 0 or sec > 12.25:
            raise ValueError(f"required_sec outside 0..12.25: {sec}")
        return k

    ks_min = [sec_to_k(s.get("required_sec", 2.0)) for s in shots]

    # 3. 目标总帧对齐：sum(f_i) = 5*N + 17*sum(k_i)，尽量贴近 want_total_sec
    target_raw_frames = max(sum(5 + 17 * k for k in ks_min), round(float(want_total_sec) * 24))
    k_total_needed = max(sum(ks_min), min(17 * n_shots, round((target_raw_frames - 5 * n_shots) / 17.0)))

    # 当前已用的 k 总和（每个镜头的最小 k）
    k_used = sum(ks_min)
    # 剩余可分配的 k（用于把总时长补到目标），余量优先给"长发力主力镜"，不破坏短标点
    ks = list(ks_min)
    extra = k_total_needed - k_used

    # 4. 余量分配：优先给非短标点的镜头（主力交合/长台词），短标点(cut_insert/macro)保持最短
    if extra > 0:
        # 可加长的镜头（非短标点）
        eligible = [i for i, s in enumerate(shots)
                    if s.get("pose", "").split("->")[0] not in ("cut_insert", "prop_insert")
                    and s.get("size") not in ("macro",)]
        idx = 0
        guard = 0
        while extra > 0 and eligible and guard < 5000:
            guard += 1
            i = eligible[idx % len(eligible)]
            idx += 1
            if ks[i] < 17:
                ks[i] += 1
                extra -= 1
    elif extra < 0:
        # 总帧超了，从最长的镜头（>6s）往下挤压，优先保护短标点
        eligible = [i for i, s in enumerate(shots) if ks[i] > 6]
        idx = 0
        guard = 0
        while extra < 0 and eligible and guard < 5000:
            guard += 1
            i = eligible[idx % len(eligible)]
            idx += 1
            if ks[i] > ks_min[i]:
                ks[i] -= 1
                extra += 1

    # 5. 打破连续 3 镜同帧长（保持心电图呼吸，严禁平铺一刀切）
    for i in range(2, n_shots):
        if ks[i] == ks[i - 1] == ks[i - 2]:
            if ks[i - 1] > ks_min[i - 1] and ks[i] < 17:
                ks[i - 1] -= 1
                ks[i] += 1

    # 6. 落盘每镜帧数与时间戳
    t_frames = 0
    for s, k in zip(shots, ks):
        f_cnt = 5 + 17 * k
        dur_sec = round(f_cnt / 24.0, 2)
        s["frames"] = f_cnt
        s["t0"] = round(t_frames / 24.0, 2)
        t_frames += f_cnt
        s["t1"] = round(t_frames / 24.0, 2)
        s["dur"] = dur_sec

    return shots, round(t_frames / 24.0, 2)


def build_scene(chain, total_sec, poses, recipes=None, decisions=None):
    """
    全剧集智能拆镜与 Auto-DP 运镜编排：
    1) 支持文戏/转场原语与 55 套肉戏真源自由混排，绝不强制固定套路
    2) 在主力多拍动作中自动穿插 srs_male (男正打) / srs_female (女反打)，打破全双人同框死板感
    3) 相邻肉戏体位之间自动插入物理换位桥（文戏原语与正反打之间直接硬切，不乱塞换体位桥）
    4) Auto-DP 强制消除连续同景别或连续静态机位，执行工作景别阶梯弹跳（Working Shot Ladder）与接戏过继说明
    """
    recipes = recipes or {}
    if not chain or any(pid not in poses and pid not in recipes for pid in chain):
        raise ValueError("Scene requires known pose identifiers")
    if not __import__("math").isfinite(total_sec) or total_sec <= 0:
        raise ValueError("Scene duration must be positive and finite")
    from whale_solo import PROP_IDS
    shots = []
    for i, pid in enumerate(chain):
        decision = (decisions or {}).get(i)
        metadata = {k:decision[k] for k in ('source_scene','cast','dialogue','staging_note') if decision and k in decision}
        if decision and 'staging' not in decision:
            from whale_pose_choice import direction
            cue = direction(decision)
            visible = decision['visual'].rstrip('.') + '.'
            # The entry/transition instruction precedes the pose; the exit is last.
            action = f"{visible} {cue}." if cue else visible
            if decision['transition'] == 'one_take':
                shot = shots[-1]
                shot['action_steps'].append(decision)
                shot['action_decision'] = decision  # endpoint, retained for single-step consumers
                shot['pose'] = pid if pid in poses else 'blocking_2s'
                shot['pose_zh'] += ' → ' + poses.get(pid,{}).get('nameZh',pid)
                shot['text_en'] += ' Then: ' + action
                shot['text'] = shot['text_en']
                shot['required_sec'] = 2.0 * len(shot['action_steps'])
            else:
                size,cam = decision['framing']['size'],decision['framing']['cam']
                shot = dict(pose=pid if pid in poses else 'blocking_2s', pose_zh=poses.get(pid,{}).get('nameZh',pid),
                            **metadata, pose_en=poses.get(pid,{}).get('nameEn',pid), text=action,text_en=action,size=size,cam=cam,type='action',
                            action_steps=[decision],action_decision=decision,source_line=decision['source_line'])
                if pid in recipes: shot['custom_recipe']=pid
                shots.append(shot)
            continue
        if decision: metadata['source_line'] = decision['line']
        note = metadata.get('staging_note')
        if note:
            shots.append(dict(**metadata,pose=pid,pose_zh=poses[pid]['nameZh'],pose_en=poses[pid]['nameEn'],
                              text=note['visual'],text_en=note['visual'],size=note['size'],cam=note['cam'],type='staging'))
            continue
        if pid in recipes:
            action, size, cam = recipes[pid]
            shots.append(dict(pose="blocking_2s", custom_recipe=pid, **metadata, pose_zh=pid, pose_en=pid,
                              text=action, text_en=action, size=size, cam=cam, type="staging"))
            continue
        p = poses.get(pid)
        if not p:
            continue
        name = p.get("nameZh") or pid
        name_en = p.get("nameEn") or pid
        beats_zh = p.get("beatsZh") or [name]
        beats_en = p.get("beatsEn") or [name_en]
        plan = [("mcu", "static_side")] if pid in PROP_IDS else plan_shot(pid, poses)
        n_beats = max(1, min(len(beats_zh), len(plan)))

        for k in range(1 if decision else n_beats):
            size, cam = plan[k]
            beat_zh = beats_zh[k] if k < len(beats_zh) else beats_zh[-1]
            beat_en = beats_en[k] if k < len(beats_en) else beats_en[-1]
            shot_type = "staging" if pid in STAGING_IDS else "action"
            shots.append({
                **metadata, "pose": pid, "pose_zh": name, "pose_en": name_en,
                "size": size, "cam": cam,
                "text": beat_zh,
                "text_en": beat_en,
                "type": shot_type,
            })

        # 仅当当前与下一个均为非调度类肉戏体位、且体位发生变化时，才插入物理换位转场桥
        if i < len(chain) - 1 and not (decisions or {}).get(i+1):
            nxt_id = chain[i + 1]
            if (pid not in STAGING_IDS and nxt_id not in STAGING_IDS
                    and pid not in PROP_IDS and nxt_id not in PROP_IDS
                    and nxt_id not in recipes and pid != nxt_id and nxt_id not in FINISH_IDS):
                nxt_p = poses.get(nxt_id, {})
                nxt = nxt_p.get("nameZh", nxt_id)
                nxt_en = nxt_p.get("nameEn", nxt_id)
                from_plan = plan_shot(pid, poses)
                prev_size = from_plan[-1][0]
                tr_size = "mcu"
                shots.append({
                    "pose": f"{pid}->{nxt_id}",
                    "pose_zh": f"{name}→{nxt}",
                    "pose_en": f"{name_en} to {nxt_en}",
                    "size": tr_size, "cam": "arc_subtle",
                    "text": f"衔接转场：从「{name}」物理过渡到「{nxt}」（重心平滑转移与支点重新对齐，一气呵成）",
                    "text_en": (f"Continuous physical posture transition from {name_en} into {nxt_en}: "
                                f"<Subject 1> and <Subject 2> shift center of gravity over two seconds, "
                                f"repositioning hands and hips on the support surface and realigning smoothly in one continuous take"),
                    "type": "transition",
                })

    # 肉戏链自动补全男女主不同角度的独立情绪反馈镜（srs_male 微仰/慢推 + srs_female 微俯/呼吸手持）：
    # 仅在纯自由链（无冻结 decisions）、至少含 2 个非终结肉戏主力体位且创作者未手写正反打时触发，
    # 避免破坏已冻结分镜或纯单镜/纯文戏测试，同时兑现“男女主不同角度情绪反馈”硬核指标。
    if not decisions:
        action_main_ids = [
            p for p in chain
            if p not in STAGING_IDS and p not in PROP_IDS and p not in FINISH_IDS and p not in recipes
        ]
        if len(set(action_main_ids)) >= 2:
            has_srs_m = any(s.get("pose") == "srs_male" for s in shots)
            has_srs_f = any(s.get("pose") == "srs_female" for s in shots)
            tr_indices = [idx for idx, s in enumerate(shots) if s.get("type") == "transition"]
            if tr_indices:
                anchor = tr_indices[0]
                insert_pack = []
                if not has_srs_m:
                    insert_pack.append({
                        "pose": "srs_male",
                        "pose_zh": "男主施压情绪反馈",
                        "pose_en": "Male lead dominant emotional reaction",
                        "size": "cu",
                        "cam": "low_upward",
                        "text": "男主压迫情绪反打：微仰角近景捕捉男主紧绷下颌、炽热凝视与急促胸膛起伏",
                        "text_en": (
                            "Single-subject close-up on <Subject 2>: tense jawline, focused intense gaze, "
                            "rapid heavy chest breathing, sweat sheen fading into matte skin texture"
                        ),
                        "type": "staging",
                        "emotion": "surge",
                    })
                if not has_srs_f:
                    insert_pack.append({
                        "pose": "srs_female",
                        "pose_zh": "女主失神情绪反馈",
                        "pose_en": "Female lead breathless emotional reaction",
                        "size": "face",
                        "cam": "high_downward",
                        "text": "女主承受情绪反打：微俯角面部特写捕捉女主微张唇瓣、迷离上翻眼神与肩颈轻颤",
                        "text_en": (
                            "Single-subject facial close-up on <Subject 1>: parted lips catching a ragged breath, "
                            "fluttering eyelids, flushed cheeks and trembling collarbones"
                        ),
                        "type": "staging",
                        "emotion": "ecstasy",
                    })
                if insert_pack:
                    shots = shots[:anchor] + insert_pack + shots[anchor:]

    # Auto-DP 动态运镜与工作景别阶梯（Working Shot Ladder）巡检：
    # 1) 严禁连续两镜同机位同景别，严禁连续两镜 static
    # 2) 极特写(macro)与全景(wide)作为标记镜头，用完一镜后若下一镜仍为同类极端景别，自动弹回工作景别(mcu/cu)
    # 3) 单人镜与后入系轮换池剔除 ots_depth（单人过肩必出同性双人，后入过肩丢失前后贴合）
    # 4) 仅跳过单镜 one_take / 用户在分镜中显式锁定了机位的镜头；普通剧本自动生成的连续镜一律享受呼吸感与运镜轮换
    dynamic_cycle = ["push_tension", "arc_subtle", "tilt_up_desire", "handheld_breath", "high_downward", "low_upward"]
    for idx in range(1, len(shots)):
        if shots[idx].get("custom_recipe"):
            continue
        if len(shots[idx].get("action_steps") or ()) > 1:
            continue
        if shots[idx].get("action_decision") and shots[idx]["action_decision"].get("explicit_camera"):
            continue
        prev_size = shots[idx - 1]["size"]
        curr_size = shots[idx]["size"]
        if prev_size == "macro" and curr_size == "macro":
            shots[idx]["size"] = "cu"
        elif prev_size == "wide" and curr_size == "wide":
            shots[idx]["size"] = "mcu"
        prev_cam = shots[idx - 1]["cam"]
        curr_cam = shots[idx]["cam"]
        if (shots[idx]["size"] == shots[idx - 1]["size"] and curr_cam == prev_cam) or ("static" in prev_cam and "static" in curr_cam):
            picked = dynamic_cycle[idx % len(dynamic_cycle)]
            if picked == prev_cam:
                picked = dynamic_cycle[(idx + 1) % len(dynamic_cycle)]
            shots[idx]["cam"] = picked

    # 生成 CUT-READY 接戏过继契约（前镜末态 → 本镜起态）
    handoff_types = [
        "动作接动作（前镜发力末势无缝切入本镜受力起势）",
        "视线/正反打接戏（前镜施压视线切入本镜面部微表情反应）",
        "景别呼吸切（中近景空间关系切入局部微距细节）",
        "J-Cut声先画后（前镜尾音延入本镜起幅动作）",
    ]
    for idx, s in enumerate(shots):
        if s.get('action_steps'):
            first = s['action_steps'][0]
            s['handoff'] = f"{first['transition']}: {first['pre']} → {first['选择']}"
        elif idx == 0:
            s["handoff"] = "开场首镜建立：0.00s 直接锁定空间光影与初始姿态"
        else:
            prev_s = shots[idx - 1]
            ht = handoff_types[idx % len(handoff_types)]
            s["handoff"] = f"{ht} | 承接：[{prev_s['pose_zh']}·{prev_s['size']}] 末态 ➔ 本镜 [{s['pose_zh']}·{s['size']}] 起态"

    return allocate_exact_h3_frames(shots, total_sec)


def resolve_slot_refs(shot_size, pose_id, is_nude_state=True, asset_dir=""):
    """
    吞鲸 v4.6.3 空间图池单槽轮换法（Multi-View Pool, Single-View Per Shot）+ 单人镜槽位物理隔离：
    1. 每一镜的 <Picture 3> (槽位 2) 永远只挂 1 张最匹配当前机位的空间底图（绝不多张空间图混挂打架，也绝不断开 <Picture 3> 锚点！）：
       - 墙边/立面/封堵戏 -> 优先选 `scene_wall.png`（若无则回退 `scene_main.png`）
       - 面部正反打/腰胯/微距特写 -> 优先选 `scene_close.png` 承托面近景图（解决切特写丢背景/假家具穿帮；若无则回退 `scene_main.png`）
       - 中全景/建立镜 -> 选 `scene_main.png`
    2. 单人正反打物理隔离（防枕边裂殖异性鬼脸）：
       - `srs_female` / `outro_solo` / 女单人 `face` -> `[female_ref, scene_ref, scene_ref]`（拔掉男主槽）
       - `srs_male` -> `[scene_ref, male_ref, scene_ref]`（拔掉女主槽）
       - `env_establish` / `empty_cut` -> `[scene_ref, scene_ref, scene_ref]`
    3. 动态 LoRA 权重分级：
       - 文戏/穿衣/空镜/纯道具镜 -> `lora_mystic_strength = 0.0`（彻底断电防西装长器官）
       - 前戏/肉戏 -> `lora_mystic_strength = 0.45`（激活 MysticXXX_MMH3-V5-ref2va）
    """
    first_p = (pose_id or "").split("->")[0]
    f_img = "female_nude.png" if is_nude_state else "female_dressed.png"
    m_img = "male_nude.png" if is_nude_state else "male_dressed.png"

    # 扫描 00_资产/ 真实图片池：优先匹配实际存在的文件名（避免 00_资产 里叫其他名字时盲填不存在的默认假名）
    s_main = "scene_main.png"
    s_wall = "scene_wall.png"
    s_close = "scene_close.png"
    if asset_dir and os.path.isdir(asset_dir):
        existing = sorted(
            f for f in os.listdir(asset_dir)
            if os.path.isfile(os.path.join(asset_dir, f))
            and f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
            and f.isascii()
        )
        existing_set = set(existing)
        if f_img not in existing_set:
            f_cands = [f for f in existing if ("female" in f.lower() or f.lower().startswith("f_"))
                       and (("nude" in f.lower()) == bool(is_nude_state) or ("nude" not in f.lower() and "dressed" not in f.lower()))]
            if not f_cands:
                f_cands = [f for f in existing if "female" in f.lower() or f.lower().startswith("f_")]
            if f_cands:
                f_img = f_cands[0]
        if m_img not in existing_set:
            m_cands = [f for f in existing if ("male" in f.lower() and "female" not in f.lower()) or f.lower().startswith("m_")]
            m_state = [f for f in m_cands if ("nude" in f.lower()) == bool(is_nude_state)]
            if m_state:
                m_img = m_state[0]
            elif m_cands:
                m_img = m_cands[0]
        if s_main not in existing_set:
            s_cands = [f for f in existing if any(k in f.lower() for k in ("scene", "room", "bg", "env", "office", "corridor"))]
            if s_cands:
                s_main = s_cands[0]
        if s_wall not in existing_set:
            w_cands = [f for f in existing if "wall" in f.lower()]
            s_wall = w_cands[0] if w_cands else s_main
        if s_close not in existing_set:
            c_cands = [f for f in existing if "close" in f.lower()]
            s_close = c_cands[0] if c_cands else s_main
    else:
        # 即使离线未建实体文件，也在逻辑上标记空间视角归属，默认使用 scene_main.png 保底兼容
        s_wall = s_main
        s_close = s_main

    if any(k in first_p for k in ("wall", "pin", "blocking", "corridor")):
        s_img = s_wall
        spatial_zone = "wall_elevation"
    elif shot_size in ("face", "cu", "hip", "macro") or first_p in ("srs_male", "srs_female", "prop_insert", "cut_insert"):
        s_img = s_close
        spatial_zone = "close_surface"
    else:
        s_img = s_main
        spatial_zone = "wide_main"

    # 判定文戏/肉戏 LoRA 权重
    if not is_nude_state or first_p in ("env_establish", "blocking_2s", "prop_insert", "empty_cut", "corridor_cut"):
        lora_weight = 0.0
    else:
        lora_weight = 0.45

    # 自动探测 00_资产/ 下的道具参考图（如 daoju_*.png / prop_*.png / *keycard*.png / *ring*.png）
    # 当镜头为 prop_insert 或 present_item 时，自动追加到第 4 槽位 (<Picture 4> -> Node 43)，绝不挤占前 3 槽！
    prop_img = ""
    if first_p in ("prop_insert", "present_item") and asset_dir and os.path.isdir(asset_dir):
        prop_cands = sorted(
            f for f in os.listdir(asset_dir)
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
            and any(k in f.lower() for k in ("daoju", "prop", "item", "card", "ring", "contract", "phone"))
        )
        if prop_cands:
            prop_img = prop_cands[0]

    if first_p in ("env_establish", "empty_cut", "corridor_cut"):
        return "C_empty_cut", ["s1", "s1", "s1"], [s_img, s_img, s_img], lora_weight, spatial_zone
    if first_p in ("srs_male", "loosen_tie", "rub_temple"):
        return "B_solo_male", ["s1", "m1", "s1"], [s_img, m_img, s_img], lora_weight, spatial_zone
    from whale_solo import PROP_IDS
    if first_p in PROP_IDS or first_p in ("srs_female", "outro_solo", "back_arch_lean", "turn_evade", "collapse_sob", "fix_attire", "shoulder_strap_slide", "solo_masturbate", "finger_masturbate") or (
        shot_size == "face" and first_p not in ("bj", "squat_bj", "prone_bj", "deepthroat", "head_thrust", "facefuck")
    ):
        return "B_solo_female", ["f1", "s1", "s1"], [f_img, s_img, s_img], lora_weight, spatial_zone

    if prop_img:
        return "A_two_shot_with_prop", ["f1", "m1", "s1", "p1"], [f_img, m_img, s_img, prop_img], lora_weight, spatial_zone

    return "A_two_shot", ["f1", "m1", "s1"], [f_img, m_img, s_img], lora_weight, spatial_zone


def h3_frames(sec):
    """按 MiniMax H3 节点公式换算严格物理帧数: length = 5 + 17 * N"""
    raw = max(5, round(float(sec) * 24))
    return raw + (5 - (raw % 17)) % 17


def save_project_artifacts(out_dir, shots, actual_total, want_total, lines="",
                           idea="", scene="卧室", pose_names="", aspect="9:16", scene_id=None, script_path=None, pace_driver=None, pace_overrides=None, pace=None, actor=None, chain=None, review=None, wardrobe_mode=""):
    """一键在项目目录落盘：分镜.md + 视频提示词.md + 批量任务.json（吞鲸 v4.6.3 规范，横竖屏双轨）
    aspect: '9:16' 竖屏 / '16:9' 横屏 / '1:1' 方屏，决定景别/机位/运镜/分辨率整套构图语言。
    """
    import datetime
    os.makedirs(out_dir, exist_ok=True)
    asset_dir = os.path.join(out_dir, "00_资产")

    # Resolve on the storyboard's shot indices, before splitting requests for dialogue.
    root = Path(out_dir)
    sources = blocking.input_hashes(root, script_path, '分镜.md', False)
    adopted = blocking.prepare(shots, scene_name=scene, project=out_dir,
                               script_path=script_path, scene_id=scene_id)
    if any(s.get('action_steps') and s['blocking_state'].get('action') for s in shots):
        raise ValueError('Adopted blocking action conflicts with the reviewed pose; reconcile it in the storyboard')
    shots[:] = pacing.apply(shots, pace_driver, actor=actor, pace=pace, overrides=pace_overrides)
    for shot in shots:
        if shot.get("custom_recipe"):
            if shot["blocking_state"].get("adopted"):
                raise ValueError("Local recipes require a non-adopted storyboard")
            shot["blocking_state"]["action"] = shot["text_en"]
    sb_path = Path(out_dir) / (blocking.EXEC_BOARD if adopted else "分镜.md")
    if adopted and sb_path.exists() and not blocking.untouched_board(sb_path.read_text(encoding="utf-8-sig")):
        raise ValueError(f"执行分镜已被人工修改；先保全或采用这份修改：{sb_path.name}")

    landscape = is_landscape(aspect)
    _sz_zh = pick_dict(landscape, SHOT_SIZES_LANDSCAPE, SHOT_SIZES)
    _sz_en = pick_dict(landscape, SHOT_SIZES_EN_LANDSCAPE, SHOT_SIZES_EN)
    _cams_zh = pick_dict(landscape, CAMS_LANDSCAPE, CAMS)
    _cams_en = pick_dict(landscape, CAMS_EN_LANDSCAPE, CAMS_EN)
    res = ASPECT_RES[normalize_aspect(aspect)]
    orient_label = "横屏 16:9" if landscape else ("方屏 1:1" if normalize_aspect(aspect) == "1:1" else "竖屏 9:16")

    total_frames_sum = sum(s.get("frames", h3_frames(s["dur"])) for s in shots)

    sb_lines = [
        f"# 吞鲸工作室 v4.6.3 · 全剧集导演调度与 Auto-DP 分镜表 ([Track: Ref2V])",
        f"- 目标总时长：{want_total}s | 实际闭合总时长：{actual_total}s | 总帧数：{total_frames_sum}帧 | 总镜数：{len(shots)} 镜 | 画幅：{orient_label} {res['width']}x{res['height']}",
        f"- 调度与姿势主链：{pose_names}",
        f"- 轨道模式：[Track: Ref2V] 全片纯血锚定 + 空间图池单槽轮换 + 单人正反打物理隔离 + {orient_label}构图语言",
        "",
        "---",
        ""
    ]

    prompt_lines = [
        f"# 吞鲸工作室 v4.6.3 · 逐镜 R1~R12 全肯定送模提示词",
        f"- 场景：{scene} | 总镜数：{len(shots)} 镜 | 总帧数：{total_frames_sum}帧 | 画幅：{orient_label}",
        "",
        "---",
        ""
    ]

    batch_shots = []
    macro_tag_idx = 0

    # 针对脱衣类前戏防止首镜露鸟：若首镜包含 undress 且为 wide，强制降级为 mcu
    if shots and "undress" in shots[0].get("pose", "") and shots[0].get("size") == "wide":
        shots[0]["size"] = "mcu"
        shots[0]["cam"] = "tilt_up_desire"

    line_map, actual_total = prepare_dialogue_shots(shots, lines, want_total)
    total_frames_sum = sum(s["frames"] for s in shots)
    # Freeze after shot grouping, blocking and dialogue allocation. Prompt assembly
    # below consumes this exact snapshot, not prose or a second pass of a selector.
    from whale_pose_choice import BOARD, file_hash, prompt_hash, write_json
    reviewed_metadata = {}
    binding = {}
    frozen = None
    if chain is not None:
        frozen = dict(chain=chain, actual_total=actual_total, shots=shots, **(review or {}))
        if review is not None:
            binding = dict(review['review_inputs'])
            if any(file_hash(root/name) != digest for name,digest in binding.items()):
                raise ValueError('Pose review inputs changed during compilation')
        write_json(root/BOARD, frozen)
        frozen = json.loads((root/BOARD).read_text('utf8'))
        shots = frozen['shots']
        if review is not None:
            reviewed_metadata = {'storyboard_cards': frozen['cards'],
                                 'pose_input_hashes': {**binding, BOARD: file_hash(root/BOARD)}}
    sb_lines[1] = f"- 目标总时长：{want_total}s | 实际闭合总时长：{actual_total}s | 总帧数：{total_frames_sum}帧 | 总镜数：{len(shots)} 镜 | 画幅：{orient_label} {res['width']}x{res['height']}"
    prompt_lines[1] = f"- 场景：{scene} | 总镜数：{len(shots)} 镜 | 总帧数：{total_frames_sum}帧 | 画幅：{orient_label}"

    # 单调服装状态机：若前序为文戏调度/对峙肢体/挑逗或脱衣，初始处于穿衣状态；一旦经过脱衣或进入实质前戏/肉戏后单向锁死为素身
    # wardrobe_mode 显式覆盖（"nude_all" / "dressed_all"）用于整段同一服装状态；留空则沿用自动状态机
    wardrobe_mode = (wardrobe_mode or "").strip()
    if wardrobe_mode not in ("", "nude_all", "dressed_all"):
        raise ValueError(f"Unsupported wardrobe_mode: {wardrobe_mode!r}")
    is_nude_state = True
    if shots and (shots[0].get("pose", "") in STAGING_IDS or "undress" in shots[0].get("pose", "")):
        is_nude_state = False
    if wardrobe_mode == "nude_all":
        is_nude_state = True
    elif wardrobe_mode == "dressed_all":
        is_nude_state = False

    for i, s in enumerate(shots, 1):
        size_desc_zh = _sz_zh[s["size"]]
        cam_desc_zh = _cams_zh.get(s["cam"], s["cam"])
        size_desc_en = _sz_en[s["size"]]
        cam_desc_en = _cams_en.get(s["cam"], _cams_en["push_tension"])

        first_p = s.get("pose", "").split("->")[0]
        if wardrobe_mode in ("nude_all", "dressed_all"):
            is_nude_state = (wardrobe_mode == "nude_all")
        elif first_p not in STAGING_IDS and "undress" not in first_p:
            is_nude_state = True
        elif first_p == "fix_attire":
            is_nude_state = False

        # 挂载对应镜头的台词、说话人与显式表演情绪（支持 "4:男子A(生气):台词" 语法）
        shot_line = ""
        shot_speaker = "女子A"
        explicit_emo = ""
        if first_p == "srs_male":
            shot_speaker = "男子A"
        if i in line_map:
            spk, txt = line_map[i]
            emo_m = re.search(r"[（(](.*?)[）)]", spk)
            if emo_m:
                explicit_emo = emo_m.group(1).strip()
                spk = re.sub(r"[（(].*?[）)]", "", spk).strip()
            shot_speaker = spk
            shot_line = txt

        tier_label, ref_keys, ref_imgs, lora_w, spatial_zone = resolve_slot_refs(
            s["size"], s["pose"], is_nude_state=is_nude_state, asset_dir=asset_dir
        )
        if landscape and tier_label in ("B_solo_female", "B_solo_male") and s["cam"] in CAMS_EN_LANDSCAPE_SOLO:
            cam_desc_en = CAMS_EN_LANDSCAPE_SOLO[s["cam"]]
        if len(s.get('action_steps', ())) > 1:
            # Slot membership is the union of visible performers over the take,
            # not the cast of its final step. Keep the opening framing/camera.
            for beat in s['action_steps']:
                slots = resolve_slot_refs(beat['framing']['size'], beat['选择'], is_nude_state, asset_dir)
                if slots[0].startswith('A_two_shot'):
                    tier_label, ref_keys, ref_imgs, lora_w, spatial_zone = slots
                    break
        if len(ref_imgs) >= 4 and ref_imgs[3]:
            s["prop_ref"] = ref_imgs[3]
        from whale_prose import named_references
        ref_imgs = named_references(s,ref_imgs,is_nude_state)

        # 优先采用台词括号显式指定的情绪（如 生气/委屈/忧伤/冷笑），否则按台词语义与剧集推进阶段自动感知
        prog = i / max(1, len(shots))
        if explicit_emo:
            auto_emotion = explicit_emo
        elif first_p == "outro_solo" or first_p in FINISH_IDS or prog > 0.82:
            auto_emotion = "aftermath"
        elif first_p in ("env_establish", "blocking_2s", "undress") or prog < 0.30:
            auto_emotion = "inhibition"
        else:
            auto_emotion = "surge"

        prompt_text = single_shot_prompt(
            s, i - 1, len(shots), s["dur"], size_desc_en, cam_desc_en,
            lines=shot_line, speaker=shot_speaker, idea=idea, scene=s["blocking_state"]["location"], pose_names=pose_names,
            emotion=auto_emotion, voiceover=is_voiceover_cue(explicit_emo),
            tier=tier_label, has_audio_refs=False, aspect=normalize_aspect(aspect),
            nudity=is_nude_state
        )

        extra_tags = []
        if s["size"] in ("hip", "macro") and first_p not in ORAL_ONLY and first_p not in STAGING_IDS:
            macro_tag_idx += 1
            extra_tags.append(f"【交合特写 {macro_tag_idx} · 结合部微距】")
        elif s["size"] == "macro" or first_p in ("cut_insert", "prop_insert"):
            extra_tags.append("【1.5s 生理阻断微距】")
        if first_p in ("bj", "squat_bj", "prone_bj", "deepthroat", "head_thrust", "facefuck"):
            extra_tags.append("【口交/深喉近景特写】")
        if first_p in ("srs_male", "srs_female"):
            extra_tags.append("【正反打单人焦点】")
        tag_str = " ".join(extra_tags)

        frames_val = s.get("frames") or h3_frames(s["dur"])

        sb_lines.append(f"### SHOT-{i:02d} [Track: Ref2V]")
        sb_lines.append(f"- 时长: {s['dur']}s ({s['t0']}-{s['t1']}s) | H3帧数: {frames_val}帧")
        sb_lines.append(f"- 景别: {s['size']} — {size_desc_zh}")
        sb_lines.append(f"- 机位: {s['cam']} — {cam_desc_zh}")
        sb_lines.append(f"- 姿势: `{s['pose']}` ({s['pose_zh']}) {tag_str}")
        sb_lines.append(shot_facts.slot_prefix(tier_label, spatial_zone, ref_imgs) + f"V5-ref2va权重: `{lora_w}`)")
        plan = s["blocking_state"]
        audio_fx = parse_audio_fx_mode(shot_speaker, shot_line, voiceover=is_voiceover_cue(explicit_emo))
        if adopted or review is not None:
            actor_id = f'S{resolve_speaker(shot_speaker)}' if shot_line else None
            sb_lines.append(shot_facts.input_note(plan['source_shot'], ref_keys, audio_fx, actor_id,
                                                  is_voiceover_cue(explicit_emo)))
        sb_lines.append(blocking.board_note(plan))
        action = plan['action'] or (blocking.neutral_action(first_p) if first_p in blocking.DIALOGUE else s['text'])
        if s.get('staging_note'):
            action = s['staging_note']['source']
        sb_lines.append(f"- 动作: {action}")
        if shot_line:
            identity = s.get('dialogue',{}).get('speaker',shot_speaker)
            sb_lines.append(f"- 台词: {identity}：<d>[Chinese]{shot_line}</d>")
        # 肉戏声音反馈标注：肉戏镜必须显式写出呻吟/浪叫/粗喘，满足肉戏公式死锁并供监制审阅
        if first_p not in STAGING_IDS:
            _moan = "女主呻吟/浪叫与男主粗喘" if shot_speaker == "女子A" or first_p not in ("srs_male",) else "女主呻吟/浪叫"
            sb_lines.append(f"- 声音反馈: 全程{_moan}呼吸气声 + 肉体拍击 + 床品摩擦（overall_soundscape）")
        sb_lines.append("")

        prompt_lines.append(f"### SHOT-{i:02d} ({s['dur']}s | {frames_val}f | {s['size']} | {s['cam']} | {s['pose']} | LoRA={lora_w})")
        prompt_lines.append("```text")
        if 'action_steps' in s:
            d = s['action_steps'][0]
            sb_lines.append(f"- 已决调度: {d['source_shot']} | {d['entry_mode']} | foreplay={d['foreplay_mode']} | "
                            + ' → '.join(v['选择'] for v in s['action_steps']))
        if pacing.prompt_clause(s):
            prompt_text += "\n" + pacing.prompt_clause(s)
        prompt_lines.append(prompt_text)
        prompt_lines.append("```")
        prompt_lines.append("")

        ep_m = re.search(r"EP(\d+)", os.path.basename(os.path.abspath(out_dir)), re.IGNORECASE)
        ep_tag = f"EP{int(ep_m.group(1)):03d}" if ep_m else "EP001"
        std_prefix = f"{ep_tag}_SHOT_{i:03d}"
        batch_shots.append({
            "id": f"shot_{i}",
            "shot_id": f"shot_{i:02d}",
            "filename_prefix": std_prefix,
            "title": f"镜头 {i:02d} · {s['pose_zh']} ({s['size']})",
            **({"action_decision": s["action_decision"], "action_steps": s["action_steps"]} if "action_decision" in s else {}),
            **{k:s[k] for k in ('source_line','source_scene','cast','dialogue','staging_note') if k in s},
            "prompt": prompt_text,
            "negative_prompt": NEG,
            "duration": s["dur"],
            "frames": frames_val,
            "aspect": normalize_aspect(aspect),
            "width": res["width"],
            "height": res["height"],
            "camera_motion": s["cam"],
            "shot_size": s["size"],
            "pose": s["pose"],
            **({"custom_recipe": s["custom_recipe"]} if "custom_recipe" in s else {}),
            "tier": tier_label,
            "blocking_state": plan,
            "spatial_zone": spatial_zone,
            "handoff": s.get("handoff", ""),
            "wardrobe_state": "nude" if is_nude_state else "dressed",
            "lora_mystic_name": "MysticXXX_MMH3-V5-ref2va.safetensors",
            "lora_mystic_strength": lora_w,
            "clip_model": "qwen3vl_32b_minimax_h3_ultra_uncensored_heretic_int8_convrot.safetensors",
            "references": ref_keys,
            "audio_fx_mode": audio_fx,
            "ref_images": ref_imgs,
            "audio_mode": "H3_native_audio",
            "audio_reference_required": False,
            "ref_audios": []
        })


    pr_path = os.path.join(out_dir, "视频提示词.md")
    bj_path = os.path.join(out_dir, "批量任务.json")

    if sources != blocking.input_hashes(root, script_path, '分镜.md', False):
        raise ValueError('采用稿在编译期间发生变更；请重新编译')
    with open(pr_path, "w", encoding="utf-8") as f:
        f.write("\n".join(prompt_lines))

    if review is not None and frozen is not None:
        # Seal the exact compiled prompt strings. A schema-valid replacement
        # cannot be re-audited as if it came from the confirmed storyboard.
        frozen['prompt_sha256'] = [prompt_hash(row['prompt']) for row in batch_shots]
        write_json(root/BOARD, frozen)
        reviewed_metadata['pose_input_hashes'].update({BOARD:file_hash(root/BOARD),
                                                     '视频提示词.md':file_hash(Path(pr_path))})

    # Bind the independently resolved sources, not a digest of the outgoing row.
    sources.pop(sb_path.name, None)
    if adopted or review is not None:
        sb_lines.insert(0, shot_facts.header(sources, reviewed_metadata.get('pose_input_hashes')))
    with open(sb_path, "w", encoding="utf-8") as f:
        f.write(blocking.marker("\n".join(sb_lines)))

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    task_obj = {
        **reviewed_metadata,
        "app": "h3-batch",
        "schema": "h3-drama-task",
        "version": 4,
        "engine": "tunjing-baodian",
        "execution_board": sb_path.name,
        "blocking_input_hashes": {**sources, sb_path.name: file_hash(sb_path)},
        "workflow_template": "references/whale_schema.json",
        "project": os.path.basename(os.path.abspath(out_dir)),
        "aspect": normalize_aspect(aspect),
        "width": res["width"],
        "height": res["height"],
        "total_duration": actual_total,
        "total_frames": total_frames_sum,
        "exportedAt": now_iso,
        "export_time": now_iso,
        "shotCount": len(batch_shots),
        "batch_count": len(batch_shots),
        "batch_shots": batch_shots
    }
    with open(bj_path, "w", encoding="utf-8") as f:
        json.dump(task_obj, f, ensure_ascii=False, indent=2)

    print(f"[✓] 已落盘分镜表: {sb_path}")
    print(f"[✓] 已落盘提示词: {pr_path}")
    print(f"[✓] 已落盘吞鲸 v4.6.3 批量任务 JSON ({len(batch_shots)} 镜 / {total_frames_sum} 帧): {bj_path}")
    return str(sb_path), pr_path, bj_path


def print_table(shots, actual_total, want_total, lines="", idea="", scene="卧室",
                pose_names="", emit_prompts=True, aspect="9:16", scene_id=None, script_path=None, pace_driver=None, pace_overrides=None, pace=None, actor=None, wardrobe_mode=""):
    blocking.prepare(shots, scene_name=scene, script_path=script_path, scene_id=scene_id)
    shots[:] = pacing.apply(shots, pace_driver, actor=actor, pace=pace, overrides=pace_overrides)
    line_map, actual_total = prepare_dialogue_shots(shots, lines, want_total)
    print("=" * 100)
    print(f"🐳 吞鲸宝典 v4.6.3 · 全剧集 Auto-DP 拆镜表    目标 {want_total}s / 实际 {actual_total}s / 共 {len(shots)} 镜")
    print("=" * 100)
    print(f"{'镜':<4}{'时间':<14}{'时长':<7}{'帧数':<6}{'景别':<8}{'Auto-DP运镜':<18}{'调度/姿势':<18}")
    print("-" * 100)
    for i, s in enumerate(shots, 1):
        f_cnt = s.get("frames") or h3_frames(s["dur"])
        print(f"{i:<4}{s['t0']:>5.2f}-{s['t1']:<7.2f}{s['dur']:<7.2f}{f_cnt:<6}"
              f"{s['size']:<8}{s['cam']:<18}{s['pose_zh']:<18}")
    print("-" * 100)
    sizes = {}
    cams = {}
    for s in shots:
        sizes[s["size"]] = sizes.get(s["size"], 0) + 1
        cams[s["cam"]] = cams.get(s["cam"], 0) + 1
    print("景别分布:", ", ".join(f"{k}×{v}" for k, v in sorted(sizes.items())))
    print("运镜分布:", ", ".join(f"{k}×{v}" for k, v in sorted(cams.items())))
    print()

    if not emit_prompts:
        return

    print("=" * 100)
    print("=== 逐镜完整送模提示词（R1~R12 全肯定语法，可直接贴进 H3）===")
    print("=" * 100)
    wardrobe_mode = (wardrobe_mode or "").strip()
    if wardrobe_mode not in ("", "nude_all", "dressed_all"):
        raise ValueError(f"Unsupported wardrobe_mode: {wardrobe_mode!r}")
    is_nude_state = True
    if shots and (shots[0].get("pose", "") in STAGING_IDS or "undress" in shots[0].get("pose", "")):
        is_nude_state = False
    if wardrobe_mode == "nude_all":
        is_nude_state = True
    elif wardrobe_mode == "dressed_all":
        is_nude_state = False
    for i, s in enumerate(shots, 1):
        first_p = s.get("pose", "").split("->")[0]
        if wardrobe_mode in ("nude_all", "dressed_all"):
            is_nude_state = (wardrobe_mode == "nude_all")
        elif first_p not in STAGING_IDS and "undress" not in first_p:
            is_nude_state = True
        elif first_p == "fix_attire":
            is_nude_state = False
        size_desc_en = pick_dict(is_landscape(aspect), SHOT_SIZES_EN_LANDSCAPE, SHOT_SIZES_EN)[s["size"]]
        cam_dict = pick_dict(is_landscape(aspect), CAMS_EN_LANDSCAPE, CAMS_EN)
        cam_desc_en = cam_dict.get(s["cam"], cam_dict["push_tension"])
        shot_line = ""
        shot_speaker, explicit_emo = "女子A", ""
        if i in line_map:
            spk, txt = line_map[i]
            actor, explicit_emo = speaker_cue(spk)
            spk = "女子A" if actor == 1 else "男子A"
            if s["pose"] in ("bj", "squat_bj", "prone_bj", "deepthroat", "facefuck", "cum_face") and "女" in spk:
                pass
            elif s["dur"] >= 2.0:
                shot_speaker = spk
                shot_line = txt
        tier_label, _, _, _, _ = resolve_slot_refs(s["size"], s["pose"], is_nude_state=is_nude_state)
        if is_landscape(aspect) and tier_label in ("B_solo_female", "B_solo_male") and s["cam"] in CAMS_EN_LANDSCAPE_SOLO:
            cam_desc_en = CAMS_EN_LANDSCAPE_SOLO[s["cam"]]
        prompt = single_shot_prompt(
            s, i - 1, len(shots), s["dur"], size_desc_en, cam_desc_en,
            lines=shot_line, speaker=shot_speaker, idea=idea, scene=scene, pose_names=pose_names,
            tier=tier_label, emotion=explicit_emo or "default", voiceover=is_voiceover_cue(explicit_emo),
            aspect=normalize_aspect(aspect), nudity=is_nude_state
        )
        print(f"\n{'─' * 100}")
        print(f"### SHOT {i:02d}  {s['dur']}s ({s['t0']}-{s['t1']}s)  "
              f"{SHOT_SIZES[s['size']]} / {CAMS.get(s['cam'], s['cam'])} / {s['pose_zh']}")
        print(f"{'─' * 100}")
        print(prompt)


def main():
    ap = argparse.ArgumentParser(description="吞鲸 v4.6.3 全剧集视听导演调度与 Auto-DP 拆镜引擎")
    ap.add_argument("--chain", help="调度与姿势链，逗号分隔（支持 env_establish,blocking_2s,srs_male,srs_female,prop_insert 及 55 套体位）")
    ap.add_argument("--total", type=float, default=120.0, help="本集目标总时长秒（60~360s 任意弹性指定）")
    ap.add_argument("--lines", default="", help="本段台词")
    ap.add_argument("--idea", default="", help="剧情核心张力描述")
    ap.add_argument("--scene", default="卧室", help="场景名")
    ap.add_argument("--scene-id", help="稳定场次 ID；同一地点可有多个场次")
    ap.add_argument("--card-offset", type=int, help="First source action in resolved chain")
    ap.add_argument("--script-file", help="采用的剧本路径；默认项目内的剧本.md")
    ap.add_argument("--pace-driver", choices=sorted(pacing.PACE), help="Legacy tempo only")
    ap.add_argument("--motion-actor", choices=sorted(pacing.ACTORS), help="可选默认动作发起者 S1/S2；仅作用于物理连续动作")
    ap.add_argument("--pace", nargs="+", choices=sorted(pacing.PACE), help="可选默认有序节奏列表，如 slow steady fast")
    ap.add_argument("--pace-overrides", help="每镜 JSON，如 [{\"shot\":2,\"actor\":\"S2\",\"pace\":[\"slow\",\"fast\"]}]")
    ap.add_argument("--out-dir", default="", help="可选：一键将 分镜.md + 视频提示词.md + 批量任务.json 落盘至指定项目目录")
    ap.add_argument("--aspect", default="9:16", help="画幅：9:16 竖屏(默认) / 16:9 横屏 / 1:1 方屏；决定景别/机位/运镜/分辨率整套构图语言")
    ap.add_argument("--wardrobe-mode", default="", choices=["", "nude_all", "dressed_all"], help="可选服装状态显式覆盖：nude_all 全程裸体 / dressed_all 全程穿衣；留空自动推断")
    ap.add_argument("--table-only", action="store_true", help="只出拆镜表，不出提示词")
    ap.add_argument("--list-poses", action="store_true")
    args = ap.parse_args()

    poses = load_poses()
    if args.list_poses:
        for pid, p in poses.items():
            plan = POSE_SHOT_PLAN.get(pid)
            cat = "【导演调度】" if pid in STAGING_IDS else "【动作真源】"
            tag = "Auto-DP配方" if plan else "（默认动态运镜）"
            print(f"{pid:20s} | {cat} {p.get('nameZh',''):16s} | {tag}")
        return
    if not args.chain:
        ap.print_help()
        return

    chain = [x.strip() for x in args.chain.split(",") if x.strip()]
    from whale_local_recipe import resolve
    try:
        recipes = resolve(chain, poses, args.out_dir)
    except (ValueError, OSError) as exc:
        ap.error(str(exc))
    if not chain:
        ap.error("Empty pose chain")
    normalize_aspect(args.aspect)
    from whale_pose_choice import CARD, PLAN, reviewed_plan, file_hash
    out = Path(args.out_dir) if args.out_dir else None
    review = None
    decisions = {}
    script_bound = out and (args.script_file or (out/'剧本.md').exists())
    if args.card_offset is not None or script_bound or out and any((out/name).exists() for name in (CARD,PLAN)):
        if not out or args.card_offset not in (None,0): ap.error('Review requires a project and the exact source chain')
        try:
            binding = {k:file_hash(out/k) for k in (CARD, PLAN, 'pose_recipes.json')}
            expected, decisions, cards = reviewed_plan(out,args.script_file,args.scene,args.scene_id)
            if expected != chain: raise ValueError('Requested chain differs from the reviewed storyboard')
            if any((args.pace_driver,args.pace_overrides,args.motion_actor,args.pace)):
                raise ValueError('Edit the reviewed card, not a downstream pacing override')
            if not any('recipe_hash' in step for card in cards for step in card['steps']):
                del binding['pose_recipes.json']
            review = {'cards':cards, 'review_inputs':binding}
        except (OSError,ValueError) as exc: ap.error(str(exc))
    shots, actual = build_scene(chain, args.total, poses, recipes, decisions)
    pose_names = "→".join(poses.get(p, {}).get("nameZh", p) for p in chain)

    if out:
        save_project_artifacts(out, shots, actual, args.total,
                               lines=args.lines, idea=args.idea, scene=args.scene, pose_names=pose_names,
                               aspect=args.aspect, scene_id=args.scene_id, script_path=args.script_file,
                               pace_driver=args.pace_driver, pace_overrides=pacing.parse_overrides(args.pace_overrides),
                               pace=args.pace, actor=args.motion_actor, chain=chain, review=review,
                               wardrobe_mode=args.wardrobe_mode)
    else:
        print_table(shots, actual, args.total, lines=args.lines, idea=args.idea,
                    scene=args.scene, pose_names=pose_names,
                    emit_prompts=not args.table_only, aspect=args.aspect, scene_id=args.scene_id, script_path=args.script_file,
                    wardrobe_mode=args.wardrobe_mode)


if __name__ == "__main__":
    main()
