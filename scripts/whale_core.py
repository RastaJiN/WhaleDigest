#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
吞鲸宝典 v4.7.1 · 全剧集导演调度与提示词装配共享核心 (WhaleDigest Assembly Core v4.7.1)

核心特性：
1. R1~R12 全肯定无否定式语法（Positive-Only Grammar）：
   - 正向送模文本彻底剥离 `=== NEGATIVE ===` 负向清单（防 Node 328 清零后正向反噬画油光/断肢）
   - 废除 `OUT OF FRAME / no / without` 否定词根，全面改用正面物理存在边界（Positive Cropping & Anatomy Lock）
   - 注入 `MOTION FLOOR:` 底噪生命力锁（破除台词合成时身体僵尸定格）
   - 注入唯一 `Camera:` 量化运镜行与独立 `SPEECH:` 台词行
2. 13 类场地承托面人体高度锚点（Body-Height Furniture Anchor）：
   - 自动将桌面、床沿、吧台、窗台等承托物锚定在人体固定部位高度（如腰带高、膝盖高、胯部高），彻底消除跨镜家具高度乱跳
3. 特写与微距头部自动瘦身裁剪（Macro/Face Header Slimming）：
   - 切入 `macro` 或 `face` 镜头时，自动裁剪掉头部多余的房间全景与全身比例描述，防止模型强行把极特写拉宽为中景
4. 正反打从本场的分镜决定取景、屏幕方向与视线：
   - `srs_male` / `srs_female` 只指定入画角色；画内位置与注视目标随本场调度，不由性别或说话顺序决定。
5. 黄金情绪反应公式（1个明确情绪点名 + 2处可见解剖泄露 + 1.5秒内落定保持）
6. 先静后动三段式运镜（0.0s–1.0s 起幅稳固定格 ➔ 中段平滑运镜 ➔ 尾段 0.8s 稳固落幅）
7. H3 真实语速预算锁（4.1字/秒常速 + 扣除开口前延迟与尾段反应窗口）
"""

import json, os, re
import hmac as _hmac
import hashlib as _hashlib

BASE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(BASE, "..", "references")


# 任务/状态完整性校验：签名绑定任务内容、门禁状态与检查器代码。
# 随包固定密钥可由源码重建，不提供对拥有本机写权限者的防篡改保证。
def _hmac_secret():
    _a = "tunjing"
    _b = "baodian"
    _c = "v4-anti-bypass-seal"
    return (_a + "-" + _b + "-" + _c).encode("utf-8")


def sign_project(project_dir):
    """Bind the integrity token to the selected task, status and validator code."""
    from whale_task_source import load_task_source

    batch_file, _batch, task_sha256 = load_task_source(project_dir)
    batch_bytes = batch_file.read_bytes()
    if _hashlib.sha256(batch_bytes).hexdigest() != task_sha256:
        raise ValueError("Task source changed while calculating the integrity token")
    status_file = os.path.join(project_dir, ".whale_status.json")
    payload = (str(batch_file).encode("utf-8") + b"\0" +
               task_sha256.encode("ascii") + b"\0" + batch_bytes)
    if os.path.exists(status_file):
        with open(status_file, "rb") as fh:
            payload += fh.read()
    for fn in ("whale_gatekeeper.py", "whale_diff_audit.py", "whale_core.py",
               "whale_runner.py", "whale_task_source.py", "whale_compiler.py",
               "whale_audio_contract.py"):
        sp = os.path.join(os.path.dirname(os.path.abspath(__file__)), fn)
        with open(sp, "rb") as fh:
            payload += fn.encode("ascii") + b"\0" + fh.read()
    return _hmac.new(_hmac_secret(), payload, _hashlib.sha256).hexdigest()[:16]


def verify_project_sign(project_dir, signature):
    """Compare the selected task's integrity token in constant time."""
    return isinstance(signature, str) and _hmac.compare_digest(sign_project(project_dir), signature)

TEASE_IDS = {
    "trace_collar", "ear_whisper_tease", "shoulder_strap_slide", "leg_brush_tease",
    "neck_nuzzle_inhale", "waist_pull_collision", "lip_thumb_wipe", "tie_pull_seduce",
    "back_arch_lean", "finger_interlock_pin"
}
DRAMATIC_BODY_IDS = {
    "chin_lift", "wrist_pin", "loosen_tie", "wall_caging", "nape_grip",
    "chest_push", "step_back_guard", "turn_evade", "clutch_fabric",
    "grab_lapel", "collapse_sob", "present_item", "rub_temple", "fix_attire"
}
STACKED_POSES = {
    "cowgirl", "cowgirl_upright", "reverse_cowgirl", "squat_cowgirl",
    "lap_sit", "lap_sit_back", "stand_face_hug", "facesit"
}
STANDING_POSES = {
    "stand_doggy_wall", "stand_bend_doggy", "stand_face_hug",
    "face_insert", "bedside_stand", "carry_insert", "table_doggy",
    "squat_bj", "wall_caging", "mirror_ear_whisper", "mirror_whisper",
}
REAR_POSES = {
    "doggy", "stand_doggy_wall", "table_doggy", "stand_bend_doggy",
    "side_spoon", "prone_bone", "back_arch_lean"
}
SUPINE_POSES = {
    "missionary", "missionary_legup", "floor_missionary", "side_face"
}

# 全肯定物理站位硬锁（100% 正向描写，供肉戏与关键体位直接读取 framingZh/beatsZh 的核心站位真源，
# 严禁写否定词根如 no bed / never kneel，符合 H3 CFG=1.0 物理定律）
STANCE_LOCKS_EN = {
    "stand_doggy_wall": (
        "Stance lock: both subjects remain upright on both feet planted firmly on the floor beside the wall; "
        "she stands leaning forward with both palms braced flat against the vertical wall and hips arched back, "
        "while he stands directly behind her with his pelvis pressed flush against her buttocks and hip drive "
        "traveling laterally across the frame."
    ),
    "stand_bend_doggy": (
        "Stance lock: both subjects remain standing on the floor; she stands on tiptoes with torso bent forward "
        "and hips raised, while he stands upright directly behind her gripping her wrists with his pelvis pressed "
        "flush against her buttocks."
    ),
    "stand_face_hug": (
        "Stance lock: both subjects stand upright face-to-face on the floor with torsos vertical and hips pressed "
        "tightly together, his arms wrapped around her waist."
    ),
    "face_insert": (
        "Stance lock: he stands firmly upright on both feet on the floor facing her, lifting one of her thighs "
        "with one hand while supporting her waist with the other arm, keeping their pelvises pressed flush together."
    ),
    "bedside_stand": (
        "Stance lock: he stands upright on the floor at the edge of the bed while she lies supine along the bed "
        "edge with her legs resting over his shoulders and hips aligned flush at waist height."
    ),
    "carry_insert": (
        "Stance lock: he stands firmly upright on both feet supporting her lifted body under her buttocks while "
        "she faces him with her legs wrapped around his waist and arms clasped around his neck."
    ),
    "table_doggy": (
        "Stance lock: she leans her upper torso across the waist-height tabletop with feet planted on the floor, "
        "while he stands upright behind her gripping her hips with pelvic thrusts traveling laterally across the frame."
    ),
    "doggy": (
        "Stance lock: she braces forward on hands and knees with back arched while he kneels closely behind her "
        "with pelvis pressed flush against her buttocks and hip drive traveling laterally across the frame."
    ),
    "missionary": (
        "Stance lock: she lies supine on her back with knees drawn open while he kneels between her thighs "
        "leaning forward above her, keeping face-to-face alignment and continuous pelvic contact."
    ),
    "missionary_legup": (
        "Stance lock: she lies supine on her back with both legs raised onto his shoulders while he kneels "
        "between her hips leaning forward in continuous face-to-face alignment."
    ),
    "cowgirl": (
        "Stance lock: he lies flat on his back underneath while she straddles his hips face-to-face looking "
        "directly down at him with her hands braced on his chest."
    ),
    "cowgirl_upright": (
        "Stance lock: he lies flat on his back underneath while she straddles him face-to-face with torso held "
        "upright and straight, eyes locked downward on him."
    ),
    "reverse_cowgirl": (
        "Stance lock: he sits upright on the bed edge with both feet flat on the floor while she sits on his lap "
        "facing the same forward direction with her back pressed against his chest and both feet grounded."
    ),
    "squat_cowgirl": (
        "Stance lock: he lies supine underneath while she squats face-to-face over his hips with feet planted on "
        "the surface and hands braced on his chest."
    ),
    "deepthroat": (
        "Stance lock: her hands brace steadily on his thighs while his arms rest relaxed at his sides, lips "
        "sealed firmly around the shaft with deep continuous strokes."
    ),
    "squat_bj": (
        "Stance lock: he stands upright with both feet on the floor and arms relaxed at his sides while she "
        "squats directly in front of him facing his hips."
    ),
    "prone_bj": (
        "Stance lock: he lies supine with legs open and arms resting at his sides while she lies flat belly-down "
        "between his thighs."
    ),
    "facesit": (
        "Stance lock: he lies supine underneath holding her outer thighs while she kneels straddling above his "
        "face."
    ),
}


def stance_lock_for(pose_id):
    first_p = (pose_id or "").split("->")[0]
    return STANCE_LOCKS_EN.get(first_p, "")
ORAL_POSES = {
    "bj", "squat_bj", "prone_bj", "deepthroat", "head_thrust", "facefuck",
    "cunnilingus", "sofa_cunni", "sixty_nine"
}
STAGING_IDS = {
    "env_establish", "blocking_2s", "srs_male", "srs_female",
    "prop_insert", "cut_insert", "spatial_shift", "outro_solo",
    "empty_cut", "corridor_cut"
} | TEASE_IDS | DRAMATIC_BODY_IDS
FINISH_IDS = {"creampie", "cum_face", "cum_chest", "cum_belly", "cum_butt", "squirting_climax"}
ORAL_ONLY = {"bj", "squat_bj", "prone_bj", "deepthroat", "head_thrust", "facefuck",
             "sixty_nine", "cunnilingus", "sofa_cunni", "fingering", "clit_tease",
             "tip_lick", "ball_lick", "penis_slap", "handjob", "titjob"}
FOREPLAY = {"undress", "kiss_fondle", "breast_rub", "nipple_lick",
            "kiss_pin", "kiss_force", "kiss_her", "ass_rub", "masturbation",
            "finger_masturbate", "solo_masturbate", "thigh_grind", "mirror_ear_whisper", "strip_tease"}

# R4 全肯定正向压油词（100% 物理肯定词）
DE_OIL = (
    "authentic matte velvet skin finish, powdered dry complexion texture, natural human skin with "
    "visible fine pores and subtle dermal grain, soft subsurface scattering with gentle matte light absorption, "
    "heavily diffused soft ambient illumination, organic 35mm cinema film grain, photorealistic human anatomy, "
    "clean full-bleed raw 35mm cinema frame"
)

MOTION_FLOOR = (
    "MOTION FLOOR: Continuous organic human micro-kinematics throughout every second; visible ribcage and collarbone "
    "breathing expansion of 1 cm, subtle weight shifts across the support surface, natural hair strand micro-sway, "
    "and realistic soft-tissue recoil."
)

OFFICIAL_CUT_PHRASES = (
    "the camera cuts to",
    "the shot cuts to",
    "the shot transitions to",
    "the shot changes to",
    "the shot switches to",
)

# 吞鲸 v4.7.1 · 黄金情绪反应配方（1个明确情绪点名 + 2处当前景别可见物理泄露 + 1.5s内落定保持）
EMOTION_MUSCLE_CUES = {
    # ── 12 大主动表演情绪底色 ──
    "anger_rage":       "simmering with furious rage; brows drawn sharply together with tense glabella and jaw muscles bulging as nostrils flare, settling into a lethal unblinking glare within 1.5 seconds",
    "cold_wrath":       "frozen in icy wrath; eyes narrowing beneath a lowered brow and chest breathing slowing to a cold steady rhythm, settling into a motionless intimidating stare within 1.5 seconds",
    "grief_sorrow":     "overtaken by deep sorrow; inner eyebrows lifting subtly as tear film gathers along the lower eyelids and chest rises in a shaky sigh, settling within 1.5 seconds",
    "humiliated_tears": "stung by humiliated grief; eye rims reddening with a tear rolling down the cheek while teeth bite hard into the lower lip, settling into a trembling silence within 1.5 seconds",
    "triumph_smirk":    "radiating calculating triumph; eyes curving with sharp satisfaction and one corner of the lips lifting 3 mm into a victorious smirk, holding steady within 1.5 seconds",
    "warm_joy":         "softened by genuine warmth; brow relaxing with bright warm eye contact and cheeks lifting into a natural gentle smile, settling smoothly within 1.5 seconds",
    "fear_panic":       "struck by sudden alarm; pupils widening as lips part 5 mm in a frozen gasp and shoulders pull back 3 cm with rapid shallow breathing, locking still within 1.5 seconds",
    "jealousy_spite":   "burning with bitter jealousy; sideways piercing gaze fixing on the target while the lower jaw shifts tensely and fingers dig into the palm, holding within 1.5 seconds",
    "mockery":          "dripping with cold disdain; eyelids lowering halfway in a slow sweep and one corner of the mouth lifting 2 mm with a scoffing exhale, settling within 1.5 seconds",
    "provocation":      "charged with deliberate provocation; chin tilting up 12 degrees with a slow deliberate blink and collarbones rising on a slow breath, holding steady eye contact within 1.5 seconds",
    "forbearance":      "straining in silent forbearance; jaw clenching tight with throat bobbing once in a hard swallow while knuckles whiten, settling into tense restraint within 1.5 seconds",
    "ecstasy":          "swept into breathless ecstasy; pupils dilating with upward gaze and head tilting back against the support as neck tendons tense, holding within 1.5 seconds",
    # ── 3 大被动心理阈值反应阶段 ──
    "inhibition":       "guarded in hesitant restraint; fingertips tightening against the fabric and gaze shifting between eyes and lips with a 0.5-second pause, settling within 1.5 seconds",
    "surge":            "locked in sudden emotional surge; all secondary hand movement stopping dead as unblinking gaze locks forward with deep ribcage expansion, settling within 1.5 seconds",
    "aftermath":        "drifting in exhausted aftermath; both shoulders dropping 3 cm as torso support relaxes and lips part in a silent exhale, settling within 1.5 seconds",
    "submission":       "yielding in quiet submission; eyelashes trembling with gaze lowered toward the floor and lower lip pressed between teeth, settling within 1.5 seconds",
    "default":          "focused in tense presence; jaw muscles tightening with visible chest breathing and natural head micro-shifts of 2 cm, settling within 1.5 seconds",
}

EMOTION_ZH_ALIAS = {
    "生气": "anger_rage", "暴怒": "anger_rage", "震怒": "anger_rage", "愤怒": "anger_rage", "发火": "anger_rage",
    "冷怒": "cold_wrath", "阴沉": "cold_wrath", "施压": "cold_wrath", "冰冷": "cold_wrath", "压迫": "cold_wrath",
    "忧伤": "grief_sorrow", "悲伤": "grief_sorrow", "心碎": "grief_sorrow", "难过": "grief_sorrow", "哀伤": "grief_sorrow",
    "委屈": "humiliated_tears", "屈辱": "humiliated_tears", "含泪": "humiliated_tears", "哭泣": "humiliated_tears", "流泪": "humiliated_tears",
    "得意": "triumph_smirk", "冷笑": "triumph_smirk", "算计": "triumph_smirk",
    "高兴": "warm_joy", "欣喜": "warm_joy", "温柔": "warm_joy", "笑意": "warm_joy", "开心": "warm_joy",
    "恐惧": "fear_panic", "惊慌": "fear_panic", "害怕": "fear_panic", "惊恐": "fear_panic", "慌乱": "fear_panic",
    "嫉妒": "jealousy_spite", "怨恨": "jealousy_spite", "不甘": "jealousy_spite", "怨毒": "jealousy_spite",
    "嘲讽": "mockery", "轻蔑": "mockery", "不屑": "mockery", "讥讽": "mockery",
    "挑衅": "provocation", "魅惑": "provocation", "勾引": "provocation", "试探": "provocation",
    "隐忍": "forbearance", "克制": "forbearance", "强撑": "forbearance",
    "迷离": "ecstasy", "失神": "ecstasy", "沉沦": "ecstasy", "高潮": "ecstasy",
    "防御": "inhibition", "掩饰": "inhibition",
    "爆发": "surge", "失控": "surge",
    "余波": "aftermath", "消散": "aftermath",
}

# ── 身体决断动作库 (Body Beat Actions)：治站桩木讷的核心，让身体跟着情绪演，不只脸动 ──
# 每个情绪配一套「身体外显动作」，角色不只面部有戏，重心/肩线/手指/步伐/物件都要动。
# 这是从 drama-skills「构造可见的表演变化」内化：目光/呼吸/身体决断三通道，禁止只写情绪词。
EMOTION_BODY_ACTIONS = {
    "anger_rage":   "weight shifting forward onto the balls of the feet, shoulders squared and chest thrusting slightly out, one hand balling into a fist at the side with knuckles whitening",
    "cold_wrath":   "body going rigidly still, chin lowering a fraction as the gaze hardens, hands dropping to the sides with fingers curling slowly inward",
    "grief_sorrow": "shoulders collapsing inward as the chest sinks, one hand rising to press over the mouth, the other arm hugging across the torso",
    "humiliated_tears": "head bowing slightly as the spine curls, shoulders shaking in tiny pulses, hands twisting together at waist height",
    "triumph_smirk": "chin tilting up as the posture straightens, weight settling back onto the rear foot, one hand resting loosely on the hip",
    "warm_joy":     "posture opening up as the shoulders relax downward, head tilting a few degrees, hands unclenching and rising in a natural open gesture",
    "fear_panic":   "upper body recoiling back a step, palms rising defensively in front of the chest, shoulders hunching to protect the neck",
    "jealousy_spite": "body turning obliquely away while the head stays fixed, arms crossing tightly over the chest, one foot pivoting outward as if about to leave",
    "mockery":      "body leaning back with one eyebrow area relaxing, weight slouching onto one leg, a hand flipping dismissively at the wrist",
    "provocation":  "body leaning forward into the other's space, one finger rising to point or tap, hips cocking to one side, chin jutting up",
    "forbearance":  "jaw locking as the throat bobs once, hands pressing flat against a surface or clasping behind the back, feet planted in a wide brace",
    "ecstasy":      "spine arching back, head thrown, fingers clawing at the support surface or the partner's back, hips bucking in bucking rhythm",
    "inhibition":   "body drawing back a fraction, one hand rising to touch the collarbone or hold the other arm, feet retreating half a step",
    "surge":        "body snapping forward into sudden motion, hands leaving their rest position, weight driving onto the front foot",
    "aftermath":    "body going slack as the tension drains, shoulders dropping, arms falling heavy to the sides, gaze going soft and unfocused",
    "submission":   "body lowering slightly, chin tucking, hands folding in the lap or hanging limply, shoulders angled submissively away",
    "default":      "subtle weight shift between the feet, shoulders settling, hands finding a natural rest, chest rising with a measured breath",
}

# 卧姿/贴身床戏情绪动作与面部变体：避免仰卧或贴身状态下出现「看地板/手叠膝上/退半步」等站姿冲突词
EMOTION_BODY_ACTIONS_SUPINE = {
    "submission":   "chin tucking against the support surface, hands drawn in tight against her chest or gripping the bedding beside her, shoulders curling inward as her body yields under the weight above",
    "inhibition":   "body pressing back into the support surface, one hand rising to guard her collarbone, the other gripping the surface edge with a held breath",
    "provocation":  "chin lifting from the support surface to hold the gaze, fingers digging into the surface beside her, chest rising on a deliberate slow breath",
    "surge":        "torso lifting slightly off the support surface on a sharp intake, palms bracing flat on the surface, hips pressing upward into the contact",
    "ecstasy":      "spine arching back against the support surface, head tilting back, fingers gripping the surface or partner's back, hips meeting the steady rhythm",
    "aftermath":    "body going slack into the support surface as tension drains, arms resting open at her sides, gaze going soft and unfocused",
    "forbearance":  "jaw locking as the throat bobs once, palms pressing flat into the surface beneath her, shoulders held taut",
    "default":      "weight settling into the support surface, shoulders relaxing into the pad, hands resting naturally against the surface, chest rising with a measured breath",
}


EMOTION_BODY_ACTIONS_INTIMATE = {
    "submission":   "chin tucking slightly as shoulders yield inward and hands press steadily into the partner or support surface",
    "inhibition":   "spine stiffening momentarily on a held breath with fingertips tightening against skin or sheets",
    "provocation":  "chin tilting slightly to hold direct eye contact while chest lifts on a slow deliberate inhale",
    "surge":        "torso driving forward with rhythmic pelvic engagement and fingertips gripping firmly for leverage",
    "ecstasy":      "spine arching smoothly as breathing deepens, shoulders trembling slightly and fingers tightening in continuous rhythm",
    "aftermath":    "shoulders softening as tension eases, posture settling steadily with a slow silent exhale",
    "forbearance":  "jaw clenching briefly while hands stay firmly braced against the partner or support surface",
    "default":      "torso and hips moving in steady synchronized cadence while hands maintain firm supportive contact and chest rises with measured breathing",
}


def _clean_legacy_actor_refs(text, tier="A_two_shot"):
    if not text:
        return text
    out = str(text)
    f_ref = "she" if tier == "B_solo_male" else "<Subject 1>"
    m_ref = "he" if tier == "B_solo_female" else "<Subject 2>"
    out = re.sub(r"\bWoman\s+[AB]'s\b", "her", out)
    out = re.sub(r"\bMan\s+[AB]'s\b", "his", out)
    out = re.sub(r"\bWoman\s+[AB]\b", f_ref, out)
    out = re.sub(r"\bMan\s+[AB]\b", m_ref, out)
    return out

EMOTION_MUSCLE_CUES_SUPINE = {
    "submission":   "yielding in quiet submission; eyelashes trembling with gaze angled sideways across the support surface and lower lip pressed lightly between teeth, settling within 1.5 seconds",
    "inhibition":   "guarded in hesitant restraint; fingertips tightening against the support surface and gaze shifting between eyes and lips with a 0.5-second pause, settling within 1.5 seconds",
    "provocation":  "charged with deliberate provocation; chin lifting off the support surface to hold eye contact with a slow deliberate blink while collarbones rise, holding within 1.5 seconds",
    "ecstasy":      "swept into breathless ecstasy; pupils dilating with head tilting back into the support as neck tendons tense and lips part on a sharp breath, holding within 1.5 seconds",
    "surge":        "locked in sudden emotional surge; gaze locking upward with deep ribcage expansion and tense jaw, settling within 1.5 seconds",
    "aftermath":    "drifting in exhausted aftermath; shoulders softening into the support surface as chest breathing slows and lips part in a quiet exhale, settling within 1.5 seconds",
    "forbearance":  "straining in silent forbearance; jaw clenching tight with throat bobbing once while fingers press firmly into the surface, settling within 1.5 seconds",
    "default":      "focused in close presence; jaw muscles tightening with visible chest breathing and natural head micro-shifts against the support, settling within 1.5 seconds",
}

# 去AI味翻译腔黑名单（用于门禁与顾问自动拦截书面化/翻译腔废话台词）
AI_CLICHE_PATTERNS = [
    r"你怎么能如此",
    r"我的心好痛",
    r"充满了不可思议",
    r"眼中闪过一丝",
    r"嘴角勾起一抹弧度",
    r"三分薄凉",
    r"扇形统计图",
    r"既然你如此无情",
    r"休怪我无义",
    r"这究竟是为什么",
    r"你听我解释好不好",
]


DIALOGUE_LEAD_SECONDS = 1.1
DIALOGUE_TAIL_SECONDS = 0.7


def dialogue_needed_seconds(line_text):
    """Shared speech budget: lead, audible text, pauses, and final reaction."""
    clean = re.sub(r"\[.*?\]|<[^>]+>", "", (line_text or "")).strip()
    if not clean:
        return 0.0
    non_ascii = sum(1 for c in clean if ord(c) > 127 and c.isalnum())
    words = len(re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", clean))
    pauses = len(re.findall(r"…+|\.{3,}", clean))
    return DIALOGUE_LEAD_SECONDS + DIALOGUE_TAIL_SECONDS + non_ascii / 4.1 + words / 2.5 + pauses * 0.5


def check_dialogue_human_quality(line_text, shot_dur=4.0):
    """
    吞鲸活人感台词与物理语速预算校验器：
    1) 拦截 AI 翻译腔与书面套话
    2) 核算真实语速窗口：说话常速 4.1 字/秒，扣除开口前 1.1s 动作起势延迟与句尾 0.7s 反应余韵
    """
    issues = []
    clean = re.sub(r"\[.*?\]", "", (line_text or "")).strip()
    if not clean:
        return issues

    for pat in AI_CLICHE_PATTERNS:
        if re.search(pat, clean):
            issues.append(f"检测到 AI 翻译腔/网文套话「{pat}」，请改为 12 字以内的活人短句、反问或拿捏把柄的狠话")

    zh_chars = len(re.findall(r"[一-龥]", clean))
    needed_sec = dialogue_needed_seconds(line_text)
    if needed_sec > shot_dur + 0.021:
        issues.append(f"台词「{clean}」含开口前1.1s与句尾0.7s共需 {needed_sec:.2f}s，超出镜头时长 {shot_dur:.2f}s")
    return issues


def parse_audio_fx_mode(speaker_raw="", line_raw="", voiceover=False):
    """
    识别台词声学后期处理模式（供 whale_mastering.py 在后期合成时自动挂载 FFmpeg 音频滤镜）：
    - `phone`：电话/听筒/对讲机音质（后期施加 300Hz–3400Hz 带通滤波 + 轻压缩）
    - `inner_os`：内心独白/混响心声（后期施加轻空间混响 aecho）
    - `normal`：标准同期干声
    """
    s = f"{speaker_raw} {line_raw}".lower()
    if any(k in s for k in ("电话", "听筒", "免提", "语音通话", "对讲", "phone", "call", "telecom")):
        return "phone"
    if voiceover or any(k in s for k in ("心声", "独白", "os", "内心", "暗想", "monologue")):
        return "inner_os"
    return "normal"


def resolve_emotion_key(emotion_input="", line_text="", fallback="default"):
    """
    将中英文情绪标签或台词内容智能解析为 EMOTION_MUSCLE_CUES 标准键
    """
    e = (emotion_input or "").strip()
    if e in EMOTION_MUSCLE_CUES and e != "default":
        return e
    if e in EMOTION_ZH_ALIAS:
        return EMOTION_ZH_ALIAS[e]
    for zh_k, en_v in EMOTION_ZH_ALIAS.items():
        if zh_k in e:
            return en_v

    txt = (line_text or "").strip()
    if txt:
        if any(w in txt for w in ("滚", "混账", "找死", "敢背叛", "闭嘴", "放肆", "该死")):
            return "anger_rage"
        if any(w in txt for w in ("呵", "就凭你", "笑话", "太天真", "以为你能")):
            return "triumph_smirk"
        if any(w in txt for w in ("求你", "别…", "不要…", "放过我", "好疼", "别这样")):
            return "humiliated_tears"
        if any(w in txt for w in ("为什么这样对我", "心痛", "算什么", "眼泪", "忘了我")):
            return "grief_sorrow"
        if any(w in txt for w in ("怎么可能", "谁在外面", "别过来", "救命", "会被发现")):
            return "fear_panic"
        if any(w in txt for w in ("凭什么她", "不甘心", "毁了")):
            return "jealousy_spite"
        if any(w in txt for w in ("真乖", "喜欢吗", "笑一个", "终于见到")):
            return "warm_joy"

    return fallback if fallback in EMOTION_MUSCLE_CUES else "default"


# 视听决策权触发器 (Visual Strategy Triggers：按戏剧意图动态匹配机位与景别)
VISUAL_STRATEGY_TRIGGERS = {
    "suffocation": ("macro", "push_tension", "Intrusive suffocating perspective: extreme close framing with slow relentless push-in and high-contrast shadow falloff"),
    "duel":        ("cu",    "ots_depth",    "Psychological duel perspective: over-the-shoulder framing with dark soft-focus foreground shoulder and 0.5s reaction delay"),
    "cold_gaze":   ("cu",    "static_side",  "Detached clinical observation: locked tripod portrait capturing internal panic against a still frame"),
}

# 仅供离线审计或独立字段存档，严禁拼入送模正向 Node 263 文本！
NEG = """Subtitles, captions, watermarks, UI, logos, on-screen text
Face swap, identity drift, deformed limbs, extra fingers, melting bodies
Detached anatomy, orbiting camera, fast zoom, static frozen frames"""

# ── 13 类场景承托面、声学映射与人体高度物理锚点（防家具跨镜忽高忽低）──
SURFACE_PROFILES = {
    "bed":     {"noun": "bed", "height_anchor": "mattress surface positioned at knee height (approx. 50 cm)", "on": "on the bed", "brace": "bracing palms against the knee-height mattress", "grab": "gripping the bedsheets", "edge": "edge of bed at knee height", "sitEdge": "sitting on the knee-height edge of the bed", "pad": "wrinkled bedsheets", "lie": "lying supine on the bed", "kneel": "kneeling on the bed", "sfx": "creaking bed frame resonance"},
    "hotel":   {"noun": "hotel bed", "height_anchor": "hotel mattress edge positioned at knee height (approx. 55 cm)", "on": "on the hotel bed", "brace": "bracing on the hotel bed", "grab": "gripping crisp hotel sheets", "edge": "hotel bed edge at knee height", "sitEdge": "sitting on the knee-height hotel bed edge", "pad": "white hotel bedsheets", "lie": "lying on the hotel bed", "kneel": "kneeling on the hotel bed", "sfx": "muffled bedspring impact"},
    "sofa":    {"noun": "leather sofa", "height_anchor": "sofa seat cushion at knee height (approx. 45 cm) with backrest at mid-torso height", "on": "on the sofa", "brace": "bracing against the hip-height sofa armrest", "grab": "gripping sofa cushions", "edge": "sofa edge at knee height", "sitEdge": "perched on the knee-height sofa edge", "pad": "soft leather cushions", "lie": "reclined back against the sofa cushions", "kneel": "straddling and kneeling on the sofa", "sfx": "creaking leather upholstery"},
    "chair":   {"noun": "heavy chair", "height_anchor": "chair seat at knee height (approx. 48 cm) with armrests at hip height", "on": "on the chair", "brace": "gripping hip-height armrests", "grab": "holding the backrest", "edge": "seat edge", "sitEdge": "seated on the heavy chair", "pad": "chair seat", "lie": "leaning back into the chair", "kneel": "straddling the chair seat", "sfx": "strained wooden chair creaks"},
    "kitchen": {"noun": "kitchen island counter", "height_anchor": "countertop surface fixed at hip height (approx. 90 cm)", "on": "on the hip-height kitchen counter", "brace": "palms flat on the hip-height cold granite counter", "grab": "gripping the hip-height counter edge", "edge": "counter edge at hip height", "sitEdge": "seated on the hip-height marble counter lip", "pad": "polished cold counter surface", "lie": "arched back over the counter", "kneel": "prone across the kitchen counter", "sfx": "dull hollow countertop thuds"},
    "bath":    {"noun": "bathroom tiled ledge", "height_anchor": "tiled ledge fixed at mid-thigh height (approx. 60 cm)", "on": "in the shower", "brace": "palms pressed against chest-height wet ceramic tiles", "grab": "holding tile wall ledge", "edge": "shower ledge at mid-thigh height", "sitEdge": "seated on the wet tile ledge", "pad": "slick wet bathroom tiles", "lie": "reclined against the tile wall", "kneel": "kneeling on the wet tile floor", "sfx": "splashing wet water echoes on cold tile"},
    "desk":    {"noun": "industrial metal desk", "height_anchor": "tabletop surface fixed at waist-belt height (approx. 75 cm)", "on": "on the waist-height desk", "brace": "palms pressed on the waist-height cold steel desktop", "grab": "white-knuckle grip on the waist-height metal desk lip", "edge": "table rim at waist-belt height", "sitEdge": "seated back on the waist-height desk edge", "pad": "cold dark-grey steel tabletop", "lie": "upper torso flattened over the waist-height desk", "kneel": "prone belly-down over the desk rim", "sfx": "heavy metallic desk frame groan"},
    "wall":    {"noun": "solid concrete wall", "height_anchor": "vertical wall plane extending behind shoulders and head", "on": "against the wall", "brace": "both palms flat against the shoulder-height solid wall", "grab": "fingers pressing wall texture", "edge": "wall corner", "sitEdge": "back pinned flat to the wall", "pad": "solid textured wall surface", "lie": "spine flush against the cold wall", "kneel": "upright against the wall", "sfx": "heavy dull wall impacts"},
    "window":  {"noun": "floor-to-ceiling glass window", "height_anchor": "window sill bar fixed at hip height (approx. 85 cm)", "on": "against the glass window", "brace": "palms pressed against chest-height cold glass pane", "grab": "gripping hip-height window frame", "edge": "window sill at hip height", "sitEdge": "perched against the hip-height window sill", "pad": "steamed reflective glass window", "lie": "pressed back into the glass", "kneel": "kneeling before the window", "sfx": "glass pane vibration resonance"},
    "rug":     {"noun": "thick wool rug", "height_anchor": "floor-level dense wool rug beneath knees and ankles", "on": "on the floor rug", "brace": "palms pressing into dense rug carpet", "grab": "clutching carpet fibers", "edge": "rug border", "sitEdge": "sitting on the rug", "pad": "textured thick rug", "lie": "supine across the soft rug", "kneel": "kneeling upright on the rug", "sfx": "muffled heavy floor impact"},
    "floor":   {"noun": "hardwood floor", "height_anchor": "ground-level hardwood floor plane", "on": "on the bare floor", "brace": "palms braced on bare floorboards", "grab": "gripping hardwood seams", "edge": "floor edge", "sitEdge": "sitting on the floor", "pad": "polished dark hardwood floor", "lie": "flat on the hardwood floor", "kneel": "kneeling on the floor", "sfx": "solid wood floorboard resonance"},
    "car":     {"noun": "car leather seat", "height_anchor": "contoured car seat cushion at knee height inside the cabin", "on": "inside vehicle rear seat", "brace": "bracing on shoulder-height seat headrest", "grab": "gripping front seat back", "edge": "seat edge", "sitEdge": "cramped on the car leather seat", "pad": "contoured dark leather car seat", "lie": "tilted back in the car seat", "kneel": "straddling in the car cabin", "sfx": "leather seat compression squeaks"},
    "balcony": {"noun": "balcony railing", "height_anchor": "metal railing top bar fixed at lower-chest height (approx. 100 cm)", "on": "at the balcony terrace", "brace": "holding the lower-chest-height cold metal balcony railing", "grab": "both hands locked on the railing bar", "edge": "railing bar at lower-chest height", "sitEdge": "leaned against the balcony ledge", "pad": "stone terrace floor", "lie": "bent forward over the terrace railing", "kneel": "kneeling on the stone balcony floor", "sfx": "wind draft and distant ambient air"},
}


def detect_scene_id(scene_name):
    s = (scene_name or "").lower()
    if any(k in s for k in ("车", "座舱", "后座", "car")): return "car"
    if any(k in s for k in ("浴", "淋浴", "温泉", "汤池", "bath", "shower")): return "bath"
    if any(k in s for k in ("沙发", "茶几", "休息室", "客厅", "包厢", "sofa")): return "sofa"
    if any(k in s for k in ("椅", "王座", "宝座", "老板椅", "chair", "throne")): return "chair"
    if any(k in s for k in ("厨", "料理", "吧台", "kitchen", "bar")): return "kitchen"
    if any(k in s for k in ("窗", "落地窗", "window")): return "window"
    if any(k in s for k in ("阳台", "露台", "天台", "balcony")): return "balcony"
    if any(k in s for k in ("墙", "走廊", "巷", "电梯", "楼梯", "试衣间", "镜", "wall", "elevator", "mirror")): return "wall"
    if any(k in s for k in ("地毯", "毯", "榻榻米", "rug")): return "rug"
    if any(k in s for k in ("地面", "地板", "地牢", "密室", "训练室", "祭坛", "floor")): return "floor"
    if any(k in s for k in ("办公", "书房", "桌", "案几", "讲台", "会议", "实验室", "诊室", "desk", "office", "铁桌")): return "desk"
    if any(k in s for k in ("酒店", "宾馆", "套房", "hotel")): return "hotel"
    return "bed"


def with_scene_surface(act_text, scene_name):
    if not act_text: return act_text
    sc_id = detect_scene_id(scene_name)
    if sc_id in ("bed", "hotel"): return act_text
    loc = SURFACE_PROFILES.get(sc_id, SURFACE_PROFILES["desk"])
    out = str(act_text)
    reps = [
        ("坐在床的边缘", loc["sitEdge"]),
        ("坐在床边缘", loc["sitEdge"]),
        ("坐在床沿边缘", loc["sitEdge"]),
        ("坐在床沿", loc["sitEdge"]),
        ("坐床沿", loc["sitEdge"]),
        ("双手撑床或抓床单", loc["brace"] + " or " + loc["grab"]),
        ("撑床或抓床单", loc["brace"] + " or " + loc["grab"]),
        ("双手撑在床面上", loc["brace"]),
        ("双手撑床面上", loc["brace"]),
        ("双手撑床", loc["brace"]),
        ("手撑床", loc["brace"]),
        ("撑床面", loc["brace"]),
        ("撑床", loc["brace"]),
        ("抓紧床单", loc["grab"]),
        ("抓床单", loc["grab"]),
        ("抠床单", loc["grab"]),
        ("按床单", loc["grab"]),
        ("床单", loc["pad"]),
        ("床垫", loc["pad"]),
        ("床面", loc["pad"]),
        ("床沿", loc["edge"]),
        ("床板", loc["edge"]),
        ("仰卧在床上", loc["lie"]),
        ("躺在床上", loc["lie"]),
        ("跪在床上", loc["kneel"]),
        ("在床上", loc["on"]),
        ("床上", loc["on"]),
    ]
    for old, new in reps:
        out = out.replace(old, new)

    reps_en = [
        (r"\bsitting on the edge of the bed\b", loc["sitEdge"]),
        (r"\bsits on the edge of the bed\b", loc["sitEdge"]),
        (r"\bon the edge of the bed\b", f"at the {loc['edge']}"),
        (r"\bon the bed edge\b", f"at the {loc['edge']}"),
        (r"\bbed edge\b", loc["edge"]),
        (r"\bedge of bed\b", loc["edge"]),
        (r"\bgripping the bedsheets\b", loc["grab"]),
        (r"\bgripping the sheets\b", loc["grab"]),
        (r"\bbracing bed/his thighs\b", f"{loc['brace']} or his thighs"),
        (r"\bbraces thigh/bed\b", f"braces thigh or {loc['pad']}"),
        (r"\bbedsheets\b", loc["pad"]),
        (r"\bbedsheet\b", loc["pad"]),
        (r"\bmattress\b", loc["pad"]),
        (r"\bpillow\b", loc["pad"]),
        (r"\bon the bed\b", loc["on"]),
        (r"\binto the bed\b", f"against the {loc['pad']}"),
        (r"\bthe bed\b", f"the {loc['noun']}"),
    ]
    for pat, repl in reps_en:
        out = re.sub(pat, repl, out, flags=re.IGNORECASE)
    return out


def wrap_action_arc(action_text):
    """
    起点-变化-终点动作链包装器（治站桩的最后一块）：
    把体位 beats 的"动作"包成「起点姿态 → 因果动作 → 终点落定」，
    让模型知道角色从哪起、怎么动、停在哪，而不是没头没尾地站桩。
    用相对时序（不按秒卡点），交给模型自然呼吸。
    """
    if not action_text:
        return action_text
    t = str(action_text).strip()
    if not t:
        return t
    # 已有起点语义则不再重复包装
    if "From 0.00s" in t or "At 0.00s" in t or "starting" in t.lower() or "spatial lock" in t.lower():
        return t
    return (f"Starting from a held starting posture, {t.rstrip('. ;')}; "
            f"the movement settles cleanly with continuous anatomical contact and stable balance")


def build_soundscape_en(scene_name, is_staging=False, nude_audio=False):
    sc_id = detect_scene_id(scene_name)
    loc = SURFACE_PROFILES.get(sc_id, SURFACE_PROFILES["bed"])
    surf_sfx = loc.get("sfx", "subtle surface resonance")
    if is_staging and not nude_audio:
        return (f"Quiet interior room tone continues throughout. Crisp fabric rustle, measured footsteps, "
                f"tense breathing, and subtle {surf_sfx}.")
    if is_staging and nude_audio:
        return (f"Quiet intimate room tone continues throughout. Close heavy breathing, soft bare skin contact, "
                f"and subtle {surf_sfx}.")
    return (f"Quiet room tone continues throughout. Rhythmic skin-on-skin collision slaps, "
            f"viscous lubrication friction, heavy ragged breathing, and subtle {surf_sfx}.")


def load_poses():
    with open(os.path.join(REF, "whale_poses_matrix.json"), encoding="utf-8") as f:
        return json.load(f)


def load_recipes():
    with open(os.path.join(REF, "transition_recipes.json"), encoding="utf-8") as f:
        return json.load(f)


# 全肯定裸体锁：H3 在 CFG=1.0 下对否定词+衣物词根敏感，只写纯粹肯定的裸肌物理事实
NUDITY_F = " She is completely unclothed from first frame to last, with continuous bare skin across her shoulders, chest, torso, and hips."
NUDITY_M = " He is completely unclothed from first frame to last, with continuous bare skin across his shoulders, chest, torso, and hips."
NUDITY_RETENTION_F = " Completely unclothed bare-skin continuity preserved from first frame to last."
NUDITY_RETENTION_M = " Completely unclothed bare-skin continuity preserved from first frame to last."
NUDITY_LOCK_SOLO_F = "Nudity continuity: <Subject 1> remains completely unclothed from first frame to last with continuous bare skin across every visible body area."
NUDITY_LOCK_SOLO_M = "Nudity continuity: <Subject 2> remains completely unclothed from first frame to last with continuous bare skin across every visible body area."
NUDITY_LOCK_BOTH = "Nudity continuity: both <Subject 1> and <Subject 2> remain completely unclothed from first frame to last with continuous bare skin across every visible body area."


def build_dynamic_slots_header(slots, dur, aspect="16:9", scene_en="established scene",
                               has_audio_refs=False, summary_text=""):
    """通用动态多槽位头部装配（1~9 槽任意排布，绝不写死 1=女 / 2=男 / 3=场景）。

    slots: list[dict]，每项可声明：
      - picture: int (1..9，对应 ref_images 的 1-based 槽位)
      - subject: int (可选，默认同 picture)
      - desc / role: str (角色、场景或道具的英文锚定描述)
      - kind: "character" | "scene" | "prop" (默认 "character")
      - voice: int | None (可选，例如 1/2/3 -> S1/S2/S3)
      - nudity: bool (可选，仅该角色裸体时追加全肯定裸肌描写)
    """
    if not slots or not 1 <= len(slots) <= 9:
        raise ValueError("slots must contain 1 to 9 ordered reference bindings")
    parts = [
        f"Goal & Audio Contract: Generate a {dur:.2f}-second {aspect} live-action cinema video "
        "with readable physical biomechanics, locked identity consistency, and synchronized native audio.",
        "Audio rule: characters vocalize exclusively the exact words enclosed inside <d>...</d> tags; "
        "all other moments contain pure physical foley and natural breathing. "
        "Never speak stage directions, pose names, camera moves, or any instruction aloud; "
        "only the dialogue inside <d> tags is spoken, everything else stays as unvoiced visual action.",
        "Voice discipline: <d> content is the sole spoken text; "
        "pose labels, intensity tags, and framing terms are never narrated, only enacted silently on screen.",
        "",
        "Anchoring & Consistency:",
        "subject_definitions:",
    ]
    char_subjects = []
    scene_subjects = []
    for idx, sl in enumerate(slots, 1):
        pic = int(sl.get("picture", idx))
        sub = int(sl.get("subject", pic))
        kind = str(sl.get("kind") or "character").lower()
        desc = str(sl.get("desc") or sl.get("role") or "").strip()
        voice = sl.get("voice")
        voice_tag = f" (S{int(voice)})" if voice else ""
        if kind == "scene":
            scene_subjects.append((sub, pic))
            desc_text = desc or f"the {scene_en} environment"
            parts.append(f"<Subject {sub}> is {desc_text} anchored in <Picture {pic}>.")
        elif kind == "prop":
            desc_text = desc or "key physical item"
            parts.append(f"<Subject {sub}> is {desc_text} anchored in <Picture {pic}>.")
        else:
            char_subjects.append((sub, pic, bool(sl.get("nudity"))))
            desc_text = desc or f"character {sub}"
            nude_tail = (
                " Completely unclothed with continuous bare natural skin from shoulders to waist and limbs."
                if sl.get("nudity") else ""
            )
            parts.append(f"<Subject {sub}>{voice_tag} is {desc_text} anchored in <Picture {pic}>.{nude_tail}")

    reference_mode = "reference generation + audio reference" if has_audio_refs else "reference generation"
    parts.append("")
    parts.append("summary:")
    if summary_text:
        parts.append(f"[{reference_mode}] {summary_text.strip()}")
    else:
        sub_list = ", ".join(f"<Subject {s}>" for s, _, _ in char_subjects) or "the scene"
        sc_clause = f" within <Subject {scene_subjects[0][0]}>" if scene_subjects else ""
        parts.append(f"[{reference_mode}] Cinematic interaction featuring {sub_list}{sc_clause}.")
    parts.append("")
    parts.append("retention_analysis:")
    for idx, sl in enumerate(slots, 1):
        pic = int(sl.get("picture", idx))
        sub = int(sl.get("subject", pic))
        kind = str(sl.get("kind") or "character").lower()
        if kind == "scene":
            parts.append(f"<Subject {sub}>: fully_preserved for surface texture and lighting direction from <Picture {pic}>; weak_reference for exact camera framing.")
        elif kind == "prop":
            parts.append(f"<Subject {sub}>: fully_preserved - exact object geometry, surface markings, and material texture are strictly locked to <Picture {pic}>.")
        else:
            nude_ret = " Full bare skin continuity maintained across every frame." if sl.get("nudity") else ""
            parts.append(f"<Subject {sub}>: fully_preserved - facial identity, hairstyle, physique, and skin tone are strictly locked to <Picture {pic}>.{nude_ret}")
    parts.append("")
    return parts


def build_fullref_header(
    dur,
    aspect,
    scene="hotel suite",
    idea="",
    is_undress=False,
    is_staging=False,
    is_stacked=False,
    is_rear=False,
    is_supine=False,
    is_oral=False,
    female_screen_side=None,
    tier="A_two_shot",
    shot_size="mcu",
    female_desc="young woman anchored in <Picture 1>, preserving her exact facial structure, hairstyle, skin tone, and anatomical proportions",
    male_desc="mature man anchored in <Picture 2>, preserving his exact masculine facial identity, hairstyle, skin tone, and muscular build",
    scene_props="",
    prop_ref="",
    prop_desc="key physical item anchored in <Picture 4>, preserving its exact printed markings, shape, and surface texture",
    has_audio_refs=False,
    nudity=False,
):
    """
    吞鲸 v4.7.1 权威头部装配：
    - 100% 遵循 R1~R12 全肯定语法（零否定词）
    - 支持单人正反打/空镜槽位物理隔离描述
    - 支持特写/微距镜头头部自动瘦身裁剪（防特写被房间全景描述拉宽成中景）
    - 内嵌家具人体高度锚点（height_anchor），防止跨镜台面/床沿高度跳变
    """
    sc_id = detect_scene_id(scene)
    surf = SURFACE_PROFILES.get(sc_id, SURFACE_PROFILES["bed"])
    scene_en_map = {
        "bed": "master bedroom", "hotel": "luxury hotel suite", "sofa": "lounge room",
        "chair": "private study", "kitchen": "modern kitchen", "bath": "steamy bathroom",
        "desk": "executive office", "wall": "dimly lit interior wall", "window": "high-rise suite",
        "rug": "living room", "floor": "interior room", "car": "luxury sedan cabin",
        "balcony": "private terrace"
    }
    scene_en = scene if not re.search(r"[一-鿿]", str(scene)) else scene_en_map.get(sc_id, "interior room")
    is_tight_crop = shot_size in ("macro", "face", "hip", "cu")
    if is_staging:
        # A location reference establishes geography, not an actor's furniture or pose.
        scene_en = 'established scene' if re.search(r'[一-鿿]', str(scene)) else scene
        props_clause = ', matching the visible setting in the scene reference'
    elif is_tight_crop:
        # 特写/微距/臀胯交合镜头部自动瘦身：只保留局部接触材质与浅景深锚定，彻底剔除全景大房间与全身陈设，杜绝把微距拉宽成中景
        props_clause = f" showing close-range {surf['pad']} texture in 20% shallow depth-of-field"
    else:
        props_clause = (f", featuring {scene_props} ({surf['height_anchor']})"
                        if scene_props and not re.search(r"[一-鿿]", scene_props)
                        else f", featuring {surf['noun']} ({surf['height_anchor']})")

    parts = []
    # 1. Goal & Audio Contract
    parts.append(f"Goal & Audio Contract: Generate a {dur:.2f}-second {aspect} live-action cinema video "
                 f"with readable physical biomechanics, locked identity consistency, and synchronized native audio.")
    parts.append("Audio rule: characters vocalize exclusively the exact words enclosed inside <d>...</d> tags; "
                 "all other moments contain pure physical foley and natural breathing. "
                 "Never speak stage directions, pose names, camera moves, or any instruction aloud; "
                 "only the dialogue inside <d> tags is spoken, everything else stays as unvoiced visual action.")
    # H3 反念稿死锁：显式声明「提示词指令永不出声、只出声 <d> 内台词」，杜绝模型把 Goal/Camera/负向等工程文本念出来
    parts.append("Voice discipline: <d> content is the sole spoken text; "
                 "pose labels, intensity tags, and framing terms are never narrated, only enacted silently on screen.")
    parts.append("")

    # 2. Anchoring & subject_definitions
    parts.append("Anchoring & Consistency:")
    parts.append("subject_definitions:")
    if tier == "C_empty_cut":
        parts.append(f"<Subject 3> is the pure architectural {scene_en} environment anchored in <Picture 3>{props_clause} and ambient lighting.")
    elif tier == "B_solo_female":
        parts.append(f"<Subject 1> is the {female_desc}." + (NUDITY_F if (nudity and not is_undress) else ""))
        parts.append(f"<Subject 3> is the {scene_en} support surface anchored in <Picture 3>{props_clause}.")
    elif tier == "B_solo_male":
        parts.append(f"<Subject 2> is the {male_desc}." + (NUDITY_M if (nudity and not is_undress) else ""))
        parts.append(f"<Subject 3> is the {scene_en} support surface anchored in <Picture 3>{props_clause}.")
    else:
        if is_undress:
            parts.append(f"<Subject 1> is the {female_desc}; her outer garment unfastens and slides down during this take.")
        else:
            parts.append(f"<Subject 1> is the {female_desc}." + (NUDITY_F if nudity else ""))
        parts.append(f"<Subject 2> is the {male_desc}." + (NUDITY_M if (nudity and not is_undress) else ""))
        parts.append(f"<Subject 3> is the {scene_en} environment anchored in <Picture 3>{props_clause} and ambient lighting.")

    if prop_ref:
        parts.append(f"<Subject 4> is the {prop_desc}.")
    if has_audio_refs and tier != "C_empty_cut":
        audible = (1,) if tier == "B_solo_female" else (2,) if tier == "B_solo_male" else (1, 2)
        parts.append("Audio timbre anchors: " + "; ".join(
            f"<Audio {n}> anchors the vocal timbre of <Subject {n}> (S{n})" for n in audible) + ".")
    parts.append("")

    reference_mode = "reference generation + audio reference" if has_audio_refs else "reference generation"
    # 3. summary
    parts.append("summary:")
    if tier == "C_empty_cut":
        parts.append("[reference generation] Pure architectural environment establishing shot within <Subject 3> anchored in <Picture 3>.")
    elif tier == "B_solo_female":
        parts.append(f"[{reference_mode}] Tight single-subject emotional reaction of <Subject 1> within <Subject 3>.")
    elif tier == "B_solo_male":
        parts.append(f"[{reference_mode}] Tight single-subject dominant focus on <Subject 2> within <Subject 3>.")
    else:
        parts.append(f"[{reference_mode}] High-tension dramatic interaction between <Subject 1> and <Subject 2> within <Subject 3>.")
    parts.append("")

    # 4. retention_analysis
    parts.append("retention_analysis:")
    if tier == "B_solo_female":
        parts.append("<Subject 1> (appears in [Shot 1]): fully_preserved - facial identity, exact hairstyle, body anatomy, and skin texture are strictly locked to <Picture 1>." + (NUDITY_RETENTION_F if (nudity and not is_undress) else ""))
    elif tier == "B_solo_male":
        parts.append("<Subject 2> (appears in [Shot 1]): fully_preserved - masculine facial identity, physique, and skin tone are strictly locked to <Picture 2>." + (NUDITY_RETENTION_M if (nudity and not is_undress) else ""))
    elif tier != "C_empty_cut":
        if is_undress:
            parts.append("<Subject 1> (appears in [Shot 1]): partially_preserved - facial features, hairstyle, and body anatomy fully preserved from <Picture 1>; clothing transitions smoothly.")
        else:
            parts.append("<Subject 1> (appears in [Shot 1]): fully_preserved - facial identity, exact hairstyle, body anatomy, and skin texture are strictly locked to <Picture 1>." + (NUDITY_RETENTION_F if nudity else ""))
        parts.append("<Subject 2> (appears in [Shot 1]): fully_preserved - masculine facial identity, physique, and skin tone are strictly locked to <Picture 2>." + (NUDITY_RETENTION_M if (nudity and not is_undress) else ""))
    parts.append("<Subject 3> (appears in [Shot 1]): partially_preserved - environment texture and lighting direction from <Picture 3>.")
    if prop_ref:
        parts.append("<Subject 4>: fully_preserved - exact object geometry, surface markings, and material texture are strictly locked to <Picture 4>.")
    parts.append("")

    # 5. Consistency, Skin & Lighting, MOTION FLOOR
    if tier == "C_empty_cut":
        parts.append("Consistency: Empty architectural space containing exclusively furniture, structure, and lighting from <Picture 3>.")
    elif tier in ("B_solo_female", "B_solo_male"):
        subj = "<Subject 1>" if tier == "B_solo_female" else "<Subject 2>"
        parts.append(f"Consistency: Single subject {subj} in frame with 20% shallow depth-of-field background showing <Subject 3> surface texture from <Picture 3>.")
    elif is_stacked:
        parts.append("Consistency: Keep the same faces, body proportions, skin tone, hairstyle, and anatomical scale throughout. "
                     "Two adults in frame. <Subject 1> vertically straddles and mounts <Subject 2> in intimate vertical and depth alignment; the camera maintains consistent viewing angle without lateral inversion.")
    elif is_rear:
        parts.append("Consistency: Keep the same faces, body proportions, skin tone, hairstyle, and anatomical scale throughout. "
                     "Two adults in frame. <Subject 2> is positioned directly behind <Subject 1>, driving forward from behind in locked rear-entry depth alignment along the camera axis; no side-by-side lateral split.")
    elif is_supine:
        parts.append("Consistency: Keep the same faces, body proportions, skin tone, hairstyle, and anatomical scale throughout. "
                     "Two adults in frame. <Subject 1> lies supine on the support surface; <Subject 2> hovers and presses directly over her in locked face-to-face vertical and chest-to-chest alignment; no lateral inversion.")
    elif is_oral:
        parts.append("Consistency: Keep the same faces, body proportions, skin tone, hairstyle, and anatomical scale throughout. "
                     "Two adults in frame. <Subject 1> is positioned between the parted thighs of <Subject 2>, kneeling at his lap level in locked close oral alignment.")
    elif female_screen_side in ("left", "right"):
        left_char = "<Subject 1>" if female_screen_side == "left" else "<Subject 2>"
        right_char = "<Subject 2>" if female_screen_side == "left" else "<Subject 1>"
        parts.append("Consistency: Keep the same faces, body proportions, skin tone, hairstyle, and anatomical scale throughout. "
                     f"Two adults in frame. The camera stays on the same side of them throughout; {left_char} is on the left, {right_char} is on the right.")
    parts.append("Skin & Lighting: " + DE_OIL)
    parts.append("Motion quality (Anti-Stiffness): Smooth continuous human kinematics with visible inertia, follow-through, "
                 "and natural breathing. Breasts and buttocks exhibit authentic delayed wave jiggle and recoil upon impact.")
    parts.append(MOTION_FLOOR)
    parts.append("")
    return parts


def _official_ref2va_header(header):
    """Keep only the six H3 Ref2VA top-level blocks in the model body."""
    section = None
    kept = []
    official = {"subject_definitions:", "summary:", "retention_analysis:"}
    internal = (
        "Goal & Audio Contract:", "Audio rule:", "Voice discipline:",
        "Anchoring & Consistency:", "Consistency:", "Skin & Lighting:",
        "Motion quality", "MOTION FLOOR:",
    )
    for raw in header:
        line = sanitize_positive_only(str(raw)).strip()
        if line in official:
            section = line
            kept.append(line)
            continue
        if line.startswith(internal):
            section = None
            continue
        if section and line:
            kept.append(line)
    return kept


def sanitize_positive_only(text):
    """
    R4 正向全肯定净化器：将残留的否定短语转化为纯正面物理描述
    """
    if not text:
        return text
    out = str(text)
    replacements = [
        (r"HEADS,\s*FACES,\s*AND\s*UPPER\s*TORSO\s*ARE\s*STRICTLY\s*OUT\s*OF\s*FRAME\.?",
         "The frame is tightly cropped from waist to mid-thigh, containing exclusively the lower torso, hips, and pelvic contact junction."),
        (r"LOWER\s*BODY\s*AND\s*GENITALIA\s*STRICTLY\s*OUT\s*OF\s*FRAME\.?",
         "The frame is tightly cropped from chest and collarbones up to the head, containing exclusively the upper torso, neck, and face."),
        (r"\bno exaggerated tongue protrusion\b", "tongue stays naturally inside the oral cavity"),
        (r"\bno part ever emerging detached\b", "the anatomical junction remains continuously sealed and aligned throughout"),
        (r"\bno lateral inversion\b", "the camera stays on the same side, preserving left-right orientation"),
        (r"\bno side-by-side lateral split\b", "both bodies remain in the same front-to-back alignment"),
        (r"<Subject 2>: absent_from_frame - not in frame for this tight solo angle\.?", "<Subject 2>: outside the tight solo crop while the composition centers on <Subject 1>."),
        (r"\bwithout cutting\b", "in one continuous unbroken take"),
        (r"\bno hard cuts\b", "continuous unbroken motion"),
        (r"\bwithout surface reflection\b", "with gentle matte light absorption"),
        (r"\bnon-greasy complexion\b", "skin with a natural matte finish under soft light"),
        (r"\bthe\s+the\b", "the"),
        (r"\bzero hard directional light\b", "even ambient illumination"),
        (r"\bunobstructed\b", "clean"),
    ]
    for pat, rep in replacements:
        out = re.sub(pat, rep, out, flags=re.IGNORECASE)
    return out


def format_segmented_camera_en(cam_desc, dur, shot_size=""):
    """
    先静后动三段式运镜封装器：
    - 局部/微距景别（hip/macro）豁免 1.00s 初始硬定格，直接保持连续微动，防止交合冲击波开局卡壳断裂
    - 中远景 0.00s–1.00s 保持静态稳固定格起幅（防止开局前 15 帧人物脸部/手部因运镜产生形变）
    - 1.00s 至 (dur - 0.80s) 平滑执行目标运镜
    - 最后 0.80s 稳固定格落幅，方便下游剪辑切点咬合
    """
    if "tripod" in cam_desc.lower() or dur < 2.2:
        return cam_desc
    if shot_size in ("hip", "macro"):
        return f"{cam_desc} with continuous subtle mechanical stabilization throughout"
    t_move_end = max(1.5, round(dur - 0.8, 2))
    return f"0.00s to 1.00s holds steady locking the initial posture, then from 1.00s to {t_move_end:.2f}s {cam_desc}, holding steady for the final 0.80s"


def resolve_speaker(speaker_raw):
    """Resolve a whole cast label; never guess a role from a substring or a name."""
    key = (speaker_raw or "").strip().casefold()
    if key in {"女子a", "女主", "女方", "女", "女人", "s1", "subject 1", "<subject 1>", "female"}:
        return 1
    if key in {"男子a", "男主", "男方", "男", "男人", "s2", "subject 2", "<subject 2>", "male"}:
        return 2
    raise ValueError(f"未识别说话人 {speaker_raw!r}；请指定女子A/S1 或男子A/S2")


def _speech_lock(actor, words, dur, tier, voiceover, voice_timbre=""):
    start = min(DIALOGUE_LEAD_SECONDS, max(0.0, dur - DIALOGUE_TAIL_SECONDS))
    stop = max(start, dur - DIALOGUE_TAIL_SECONDS)
    mode = " in an off-screen voiceover" if voiceover else ""
    subject = f"<Subject {actor}> (S{actor})"
    solo = {"B_solo_female": 1, "B_solo_male": 2}.get(tier)
    if voiceover and (tier == "C_empty_cut" or (solo is not None and actor != solo)):
        # Name the audio role, not a visual Subject missing from this crop.
        subject = f"the narrator (voice S{actor})"
    timbre_clause = f"in {voice_timbre}, " if voice_timbre else ""
    if voiceover:
        reaction = " All visible lips remain closed." if tier != "C_empty_cut" else ""
    elif tier.startswith("A_two_shot"):
        reaction = f" <Subject {3 - actor}> listens silently with lips closed."
    else:
        reaction = ""
    return (f"\nSPEECH: From {start:.2f}s to {stop:.2f}s, {timbre_clause}only {subject} says{mode}: "
            f"<d>[Chinese]{words}</d>.{reaction}")


def build_shot_description(shot, index, total_shots, dur, size_desc, cam_desc,
                           lines="", speaker="女子A", scene="hotel suite",
                           emotion="default", voiceover=False, hold_last_second=False,
                           female_screen_side=None, tier="A_two_shot", nudity=False,
                           voice_timbre="", apply_de_oil=True, style_label="Live-action cinematic"):
    """
    编译单镜画面与独立 SPEECH 行（100% 对齐 R1~R12 全肯定语法 + 正反打视线互补锁 + 先静后动三段式运镜）
    """
    pid = shot.get("pose", "")
    first_p = pid.split("->")[0]
    p_zh = shot.get("pose_zh", "")
    is_transition = "->" in pid or shot.get("type") == "transition"
    is_staging = first_p in STAGING_IDS

    is_oral = first_p in ORAL_ONLY or "口交" in p_zh or "深喉" in p_zh
    from whale_solo import PROP_IDS
    is_penetration = (first_p not in PROP_IDS and first_p not in FOREPLAY and first_p not in ORAL_ONLY and first_p not in FINISH_IDS
                      and not is_staging and not is_transition)
    is_undress = "undress" in first_p

    actor = resolve_speaker(speaker) if lines else None
    from whale_blocking import DIALOGUE, RELATIONS, neutral_action, visible_notes
    plan = shot.get('blocking_state')
    if female_screen_side not in (None, 'left', 'right'):
        raise ValueError('invalid screen-side decision')
    male_side = {'left':'right', 'right':'left'}.get(female_screen_side)
    effective_vo = bool(voiceover) or (bool(lines) and (
        shot.get("size") in ("hip", "macro") or (is_oral or first_p == "cum_face") and actor == 1
        or first_p in ("env_establish", "prop_insert", "cut_insert")))
    visible = {"srs_male": 2, "srs_female": 1, "outro_solo": 1}.get(first_p)
    if visible is None:
        visible = {"B_solo_male": 2, "B_solo_female": 1}.get(tier)
    if lines and not effective_vo and visible is not None and visible != actor:
        raise ValueError("On-camera speaker does not match the visible actor; select the speaker's shot or voiceover")

    # 防呆熔断 2：双轨物理分流构图死锁 + 正反打屏幕左右方向与俯仰视线互补锁
    comp_lock = ""
    if first_p == "env_establish":
        comp_lock = ("COMPOSITION LOCK: Pure architectural environment framing anchored in <Picture 3>, "
                     "focusing exclusively on spatial geometry, lighting, and existing interior furnishings. ")
    elif first_p in ("prop_insert", "cut_insert"):
        prop_anchor_clause = " holding <Subject 4> anchored in <Picture 4>," if shot.get("prop_ref") else ""
        comp_lock = (f"COMPOSITION LOCK: Extreme macro framing cropped tightly on the hand and surface contact area,{prop_anchor_clause} "
                     "with 20% shallow depth-of-field background anchored in <Picture 3>. ")
    elif first_p in PROP_IDS:
        size_desc = "single medium close profile view including the prop and visible supporting surface"
        comp_lock = "COMPOSITION LOCK: <Subject 1> alone, with the weight-bearing contact on the support in frame. "
    elif first_p in ("srs_male", "srs_female", "outro_solo"):
        side, toward = (female_screen_side, male_side) if visible == 1 else (male_side, female_screen_side)
        size_desc = "single chest-up close-up with face and mouth clearly visible"
        if "shoulder" in cam_desc.lower():
            cam_desc = "eye-level lateral drift of 6 cm from the established camera side"
        mark = f" at screen-{side}" if side else ''
        look = '' if plan and plan['start']['gaze'].get(f'S{visible}') else (f", looking toward screen-{toward}" if toward else '')
        if plan and plan['relation'] in ('side_by_side','shared_view') and not plan['start']['gaze'].get(f'S{visible}'):
            look = ', looking in the established shared direction'
        comp_lock = f"COMPOSITION LOCK: <Subject {visible}> alone{mark}{look} against <Picture 3>. "
    elif first_p == "blocking_2s":
        if lines and not effective_vo:
            size_desc = "chest-up two-shot keeping both faces and the speaking mouth visible"
        marks = (f"<Subject 1> stays at screen-{female_screen_side}; <Subject 2> stays at screen-{male_side}. "
                 if female_screen_side else 'Both performers keep their established marks. ')
        comp_lock = 'COMPOSITION LOCK: ' + marks
        if plan:
            comp_lock += RELATIONS[plan['relation']] + '. '
        # The direct low-level API also accepts an explicit storyboard relation; never infer it from a location.
        elif shot.get('blocking'):
            from whale_dialogue import build_blocking_lock
            comp_lock += build_blocking_lock(shot['blocking'], '')[1] + '. '
    elif shot.get("size") in ("hip", "macro") and is_penetration and (not lines or effective_vo):
        comp_lock = ("COMPOSITION LOCK: Low-angle pelvic framing cropped tightly from waist to mid-thigh, "
                     "containing exclusively the lower torso, joined hips, and rhythmic pelvic collision against <Picture 3> surface. ")
    elif shot.get("size") in ("face", "cu") and not is_oral and not is_transition:
        comp_lock = ("COMPOSITION LOCK: Tight close-up cropped from collarbones to head on facial profile and neck. "
                     "Physical momentum is conveyed through rhythmic shoulder trembling and hair shaking. ")
    elif is_undress:
        comp_lock = ("COMPOSITION LOCK: Medium-close framing cropped from chest to head on shoulders, collarbone, and unbuttoning fingers, "
                     "with <Subject 2> in full wardrobe. ")

    if tier == "C_empty_cut":
        size_desc = "wide architectural establishing shot revealing the room layout and environment"

    if plan:
        if plan['reframe']:
            cam_desc = plan['reframe'].rstrip('.')
        if first_p in DIALOGUE:
            visible_ids = (f'S{visible}',) if visible is not None else ('S1','S2')
            comp_lock += visible_notes(plan, visible_ids) + ' '
            if plan['camera_side'] != 'the established camera side':
                comp_lock += f"Camera position: {plan['camera_side']}. "

    note = shot.get('staging_note',{})
    if note.get('kind')=='hands':
        size_desc='close-up on the hands'
        if note.get('to_face'): cam_desc += ', progressing from the hands to the face'
    segmented_cam = format_segmented_camera_en(cam_desc, dur, shot_size=shot.get("size", ""))

    # 唯一 Camera: 指令行（含实拍去油光质感锁，绝不在 [Shot 1] 行重复复读机位分段词！）
    de_oil_tail = f", {DE_OIL}" if apply_de_oil else ""
    if index == 0:
        shot_prefix = f"Camera: {size_desc}, {segmented_cam}{de_oil_tail}.\n[Shot 1] {style_label}; "
        if first_p == "env_establish":
            at_str = "From 0.00s, within <Subject 3>: "
        elif first_p in PROP_IDS or first_p in ("srs_female", "outro_solo") or tier == "B_solo_female":
            at_str = "From 0.00s, <Subject 1> within <Subject 3>: "
        elif first_p == "srs_male" or tier == "B_solo_male":
            at_str = "From 0.00s, <Subject 2> within <Subject 3>: "
        else:
            at_str = "From 0.00s, <Subject 1> and <Subject 2> in <Subject 3>: "
    else:
        cut_phrase = OFFICIAL_CUT_PHRASES[index % len(OFFICIAL_CUT_PHRASES)]
        shot_prefix = f"Camera: {size_desc}, {segmented_cam}{de_oil_tail}.\n[Shot 1] At 0.00s, {cut_phrase} {size_desc}; "
        at_str = "At 0.00s, actively in motion: "

    if plan:
        # A cut changes the image, not the previous scene's momentum or the cast's marks.
        at_str = 'At 0.00s: '
    raw_action = shot.get("text_en") or shot.get("text") or ""
    if plan and (plan['action'] or first_p in DIALOGUE):
        raw_action = plan['action'] or neutral_action(first_p)
    raw_action = _clean_legacy_actor_refs(raw_action, tier=tier)
    adapted_action = sanitize_positive_only(with_scene_surface(raw_action, scene))
    # 起点-变化-终点动作链（治站桩：动作必须有头有尾，不是没头没尾的体位拍）
    if not plan or not (plan["action"] or first_p in DIALOGUE):
        adapted_action = wrap_action_arc(adapted_action)

    emo_key_body = resolve_emotion_key(emotion, lines, fallback="default")
    emo_cue_extra = ""
    # 按真实身体姿态分流情绪动作表（杜绝往女上位/后入/口交里乱塞“站姿双脚重心转移”）
    _supine_ctx = first_p in SUPINE_POSES
    _intimate_ctx = first_p in (STACKED_POSES | REAR_POSES | ORAL_POSES)
    if _supine_ctx:
        _body_tbl = EMOTION_BODY_ACTIONS_SUPINE
        _face_tbl = EMOTION_MUSCLE_CUES_SUPINE
    elif _intimate_ctx:
        _body_tbl = EMOTION_BODY_ACTIONS_INTIMATE
        _face_tbl = EMOTION_MUSCLE_CUES
    else:
        _body_tbl = EMOTION_BODY_ACTIONS
        _face_tbl = EMOTION_MUSCLE_CUES
    body_action = _body_tbl.get(emo_key_body, _body_tbl["default"])
    facial_cue = _face_tbl.get(emo_key_body, _face_tbl["default"])
    # 面部表情 + 身体决断动作双通道（治站桩木讷：脸和身一起演，不只脸动）
    # 有台词无台词都要加——有台词时角色边说话边演，更需要身体动作
    if shot.get("size") in ("face", "cu") or first_p in ("srs_male", "srs_female", "blocking_2s", "outro_solo"):
        emo_cue_extra = (f" Facial performance: {facial_cue.rstrip('.')}. "
                         f"Body action: {body_action.rstrip('.')}.")
    # 肉戏高潮/泄洪镜也强制加身体表演（不是你之前要的"肉戏要表演、要反馈，不是单纯抽插"）
    elif first_p in FINISH_IDS or is_penetration:
        emo_cue_extra = (f" Facial performance: {facial_cue.rstrip('.')}. "
                         f"Body action: {body_action.rstrip('.')}.")
    if plan and (plan['action'] or first_p in DIALOGUE):
        # Generic body beats may stand a seated actor up or occupy the hand holding a prop.
        emo_cue_extra = ''
    if shot.get("motion_override"):
        adapted_action = raw_action
        emo_cue_extra = ""
    body_text = f"{comp_lock}{at_str}{adapted_action.rstrip('.')}.{emo_cue_extra}"
    if plan and plan['start'] != plan['end'] and first_p in DIALOGUE:
        ending = visible_notes(dict(plan, start=plan['end']), visible_ids)
        if ending:
            body_text += ' At the end: ' + ending
    if any(k in pid for k in ("kiss", "kiss_fondle", "kiss_pin", "kiss_force", "kiss_her")):
        body_text += " (Anatomical lock: lips gently parted 5 mm with subtle contact and natural lip geometry; his left hand is the single hand in frame)."

    # 站位硬锁注入（将 framingZh/beatsZh 的站立/仰卧/跨坐/纵深横向约束稳定写入英文正向描述）
    stance_lock = stance_lock_for(first_p)
    if stance_lock and not is_transition and not shot.get("motion_override") and shot.get("size") not in ("face", "cu"):
        body_text += " " + stance_lock

    if is_penetration and not shot.get("motion_override") and shot.get("size") not in ("face", "cu"):
        body_text += " Sealed pelvic junction: fully seated with the lower abdomen pressed flush against her, the pelvic contact seam staying continuous and physically cohesive with natural soft-tissue compression and elastic recoil."

    tail = ""
    if hold_last_second or first_p == "outro_solo":
        tail += " The movement stops and the picture holds still for the last second."
    if index == total_shots - 1 and first_p != "outro_solo" and tier != "C_empty_cut":
        tail += f" Final state: Continuous anatomical alignment and stable composition held steady to {dur:.2f}s."

    # 独立成段的 SPEECH: 行（扣除开口前 1.1s 延迟与尾段 0.7s 反应余韵）
    speech_line = ""
    if lines:
        speech_line = _speech_lock(actor, lines, dur, tier, effective_vo, voice_timbre=voice_timbre)

    if shot.get('action_steps'):
        body_text = 'At 0.00s: ' + with_scene_surface(shot['text_en'], scene)
        tail = ''  # the card, not the final-shot heuristic, owns hold/exit
    if note:
        body_text = 'At 0.00s: ' + note['visual']
        tail = ''
    # Visual sanitization must never rewrite a character’s words.
    final_visual = re.sub(r"\.\s*;", ".", sanitize_positive_only(f"{shot_prefix}{body_text}{tail}"))
    return final_visual + speech_line


def single_shot_prompt(shot, index, total_shots, dur, size_desc, cam_desc,
                       lines="", speaker="女子A", idea="", scene="hotel suite", pose_names="",
                       female_desc="young woman anchored in <Picture 1>, preserving her exact facial structure, hairstyle, skin tone, and anatomical proportions",
                       male_desc="mature man anchored in <Picture 2>, preserving his exact masculine facial identity, hairstyle, skin tone, and muscular build",
                       scene_props="", prop_ref="", prop_desc="key physical item anchored in <Picture 4>, preserving its exact printed markings, shape, and surface texture",
                       emotion="default", voiceover=False, hold_last_second=False,
                       tier="A_two_shot", has_audio_refs=False, aspect="9:16", nudity=False,
                       voice_timbre="", apply_de_oil=True, style_label="Live-action cinematic"):
    """
    吞鲸 v4.7.1 对外唯一装配接口：
    - 输出纯净正向送模提示词（不含 === NEGATIVE ===，杜绝正向反噬）
    - 100% 兼容 R1~R12 全肯定语法与吞鲸六段式结构锚点
    """
    if not __import__("math").isfinite(dur) or not 0 < dur <= 12.25:
        raise ValueError("Independent request duration must be within 0..12.25 seconds")
    if dialogue_needed_seconds(lines) > dur + 0.021:
        raise ValueError("Dialogue exceeds the independent request duration")
    pid = shot.get("pose", "")
    first_p = pid.split("->")[0]
    is_undress = "undress" in first_p
    is_staging = first_p in STAGING_IDS
    is_stacked = first_p in STACKED_POSES
    is_rear = first_p in REAR_POSES
    is_supine = first_p in SUPINE_POSES
    is_oral = first_p in ORAL_POSES or first_p in ORAL_ONLY
    plan = shot.get('blocking_state')
    female_screen_side = ('left' if plan['screen_left'] == 'S1' else 'right') if plan else shot.get('female_screen_side', shot.get('female_side'))
    shot_size = shot.get("size", "mcu")
    if shot.get('action_steps') and shot['action_steps'][0].get('support') == 'wall':
        scene = 'wall'  # Do not give the wall shot a conflicting mattress anchor or soundscape.

    eff_prop = prop_ref or shot.get("prop_ref", "")
    custom_slots = shot.get("slots")
    if isinstance(custom_slots, list) and custom_slots:
        scene_en_s = scene if not re.search(r"[\u4e00-\u9fff]", str(scene)) else "established scene"
        header = build_dynamic_slots_header(
            custom_slots, dur, aspect=aspect, scene_en=scene_en_s,
            has_audio_refs=has_audio_refs, summary_text=shot.get("summary_en", ""),
        )
    else:
        header = build_fullref_header(
            dur, aspect, scene=scene, idea=idea, is_undress=is_undress,
            is_staging=is_staging, is_stacked=is_stacked, is_rear=is_rear,
            is_supine=is_supine, is_oral=is_oral, female_screen_side=female_screen_side,
            tier=tier, shot_size=shot_size,
            female_desc=female_desc, male_desc=male_desc, scene_props=scene_props,
            prop_ref=eff_prop, prop_desc=prop_desc,
            has_audio_refs=has_audio_refs, nudity=nudity
        )

    shot_body = build_shot_description(
        shot, index, total_shots, dur, size_desc, cam_desc,
        lines=lines, speaker=speaker, scene=scene,
        emotion=emotion, voiceover=voiceover, hold_last_second=hold_last_second,
        female_screen_side=female_screen_side, tier=tier, nudity=nudity,
        voice_timbre=voice_timbre, apply_de_oil=apply_de_oil, style_label=style_label
    )

    parts = _official_ref2va_header(header)
    parts.append("detailed_description:")
    if nudity and not is_undress and tier != "C_empty_cut" and not custom_slots:
        if tier == "B_solo_female":
            parts.append(NUDITY_LOCK_SOLO_F)
        elif tier == "B_solo_male":
            parts.append(NUDITY_LOCK_SOLO_M)
        else:
            parts.append(NUDITY_LOCK_BOTH)
    parts.append(shot_body)
    nude_audio = bool(nudity and not is_undress)
    sound = ('Room tone from the established location.'
             if (plan and is_staging and not nude_audio)
             else build_soundscape_en(scene, is_staging=is_staging, nude_audio=nude_audio))
    parts.append("overall_soundscape: " + sound)
    parts.append("non_diegetic_music: N/A")
    return "\n".join(parts)


def header_block(dur, aspect="9:16", idea="", scene="hotel suite", pose_names=""):
    return build_fullref_header(dur, aspect, scene=scene, idea=idea)


def footer_block(scene="hotel suite"):
    return [
        "Overall Soundscape:",
        "overall_soundscape: " + build_soundscape_en(scene),
        "non_diegetic_music: N/A",
    ]


def insert_hint(pose_id=""):
    first_p = (pose_id or "").split("->")[0]
    if first_p not in FOREPLAY and first_p not in ORAL_ONLY and first_p not in FINISH_IDS and first_p not in STAGING_IDS and "->" not in (pose_id or ""):
        return " Sealed pelvic junction: fully seated with the lower abdomen pressed flush, the contact line continuous and physically cohesive."
    return ""
