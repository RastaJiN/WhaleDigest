#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
吞鲸宝典 · 床戏动作实时响应引擎 (WhaleDigest Pose Real-time Resolver)

用法：在创作到床戏环节时，直接喊动作需求，本引擎 1:1 从吞鲸宝典内置引擎矩阵
返回该动作的完整送模提示词（Framing + 压油 + Beats + Line）。

命令行：
    python whale_resolver.py "女口交"          # 单个动作
    python whale_resolver.py "扣女穴"          # 指插
    python whale_resolver.py "女上位"          # 骑乘
    python whale_resolver.py --list            # 列出全部 55 套可用动作
    python whale_resolver.py --scene "..." --aspect 16:9  # 整段床戏剧本按横屏拆解
"""

import argparse
import json
import sys
import os
import re

MATRIX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "references", "whale_poses_matrix.json")

# 恒定正向压油模板（吞鲸引擎 Node 328 零化负向的物理真相：靠正向肯定句压油）
DE_OIL = ("authentic matte velvet skin finish, powdered dry texture, natural human skin "
          "with visible fine pores and subtle imperfections, soft subsurface scattering "
          "without surface reflection, non-greasy complexion, heavily diffused soft ambient light, "
          "zero hard directional light, 35mm film grain, photorealistic anatomy, "
          "strictly zero extra limbs and zero fused body parts")

# 中文/口语动作别名 -> 矩阵 pose id（关键：把用户口语映射到吞鲸引擎原版 ID）
ALIAS = {
    # 口爱
    "女口交": "bj", "口交": "bj", "含": "bj", "吹": "bj", "跪口": "bj", "跪姿口交": "bj",
    "深喉": "deepthroat", "喉咙": "deepthroat", "吞吐": "deepthroat",
    "口爆": "facefuck", "打桩口": "facefuck", "按头": "head_thrust",
    "69": "sixty_nine", "舔蛋": "ball_lick", "舔龟头": "tip_lick",
    # 指插/前戏
    "扣女穴": "fingering", "指插": "fingering", "扣穴": "fingering", "手指": "fingering",
    "揉阴蒂": "clit_tease", "揉豆": "clit_tease",
    "舔女穴": "cunnilingus", "舔逼": "cunnilingus", "口女": "cunnilingus", "舔阴": "cunnilingus",
    "揉胸": "breast_rub", "摸胸": "breast_rub", "揉奶": "breast_rub", "摸奶": "breast_rub",
    "舔乳头": "nipple_lick", "舔奶头": "nipple_lick",
    "撸管": "handjob", "打飞机": "handjob", "乳交": "titjob",
    "抚摸": "breast_rub", "爱抚": "breast_rub",
    # 主力交合
    "传教士": "missionary", "正常位": "missionary", "第一体位": "missionary",
    "后入": "doggy", "趴跪后入": "doggy", "狗爬": "doggy", "后人": "doggy", "后入位": "doggy",
    "桌上后入": "table_doggy", "站后入": "stand_doggy_wall", "撑墙后入": "stand_doggy_wall",
    "女上位": "cowgirl", "骑乘": "cowgirl", "女上": "cowgirl", "上坐": "cowgirl",
    "反向骑乘": "reverse_cowgirl", "背骑": "reverse_cowgirl",
    "抱起插入": "carry_insert", "抱插": "carry_insert",
    "肛交": "anal", "后庭": "anal", "菊花": "anal",
    "侧卧": "side_face", "侧位": "side_face",
    # 绝顶清算
    "射屁股": "cum_butt", "射在屁股上": "cum_butt", "射臀": "cum_butt", "颜射": "cum_face",
    "射脸": "cum_face", "射胸": "cum_chest", "内射": "creampie",
    # 亲吻
    "强吻": "kiss_force", "按墙强吻": "kiss_pin", "湿吻": "kiss_fondle", "舌吻": "kiss_fondle",
    # 导演结构性动作词（默认落到约定动作，避免漏识别）
    "前戏": "kiss_fondle", "破防": "kiss_pin", "脱衣": "undress",
    "第一个位": "missionary", "第一体位": "missionary", "换体位": "cowgirl", "体位": "missionary",
    # v4.0 导演调度原语别名
    "空镜": "env_establish", "环境空镜": "env_establish", "建立空镜": "env_establish",
    "走位封堵": "blocking_2s", "对峙": "blocking_2s", "壁咚对峙": "blocking_2s",
    "男正打": "srs_male", "正打": "srs_male", "男特写": "srs_male", "过肩正打": "srs_male",
    "女反打": "srs_female", "反打": "srs_female", "女特写": "srs_female", "反应特写": "srs_female",
    "道具特写": "prop_insert", "信物微距": "prop_insert", "道具微距": "prop_insert",
    "生理阻断": "cut_insert", "抓白微距": "cut_insert",
    "空间转移": "spatial_shift", "换场地": "spatial_shift",
    "尾声独处": "outro_solo", "结尾收束": "outro_solo", "余韵": "outro_solo",
    # v4.0 10大暧昧挑逗与诱惑肢体别名
    "划喉结": "trace_collar", "摸喉结": "trace_collar", "划领口": "trace_collar", "指尖挑逗": "trace_collar", "挑逗": "trace_collar",
    "贴耳低语": "ear_whisper_tease", "耳语": "ear_whisper_tease", "咬耳朵": "ear_whisper_tease", "吹气": "ear_whisper_tease",
    "滑肩带": "shoulder_strap_slide", "拨衣领": "shoulder_strap_slide", "半脱诱惑": "shoulder_strap_slide", "诱惑": "shoulder_strap_slide",
    "腿蹭腿": "leg_brush_tease", "桌下蹭腿": "leg_brush_tease", "腿部挑逗": "leg_brush_tease", "蹭腿": "leg_brush_tease",
    "埋颈": "neck_nuzzle_inhale", "闻脖子": "neck_nuzzle_inhale", "嗅颈": "neck_nuzzle_inhale",
    "扣腰拉近": "waist_pull_collision", "搂腰撞怀": "waist_pull_collision", "拉入怀": "waist_pull_collision",
    "摸嘴唇": "lip_thumb_wipe", "擦唇": "lip_thumb_wipe", "摩挲唇瓣": "lip_thumb_wipe",
    "拽领带": "tie_pull_seduce", "拉领带": "tie_pull_seduce", "勾领带": "tie_pull_seduce",
    "后仰倚桌": "back_arch_lean", "展露曲线": "back_arch_lean", "后仰诱惑": "back_arch_lean",
    "十指紧扣": "finger_interlock_pin", "十指扣死": "finger_interlock_pin", "按压十指": "finger_interlock_pin",
    # v4.0 14大权力对峙与情绪肢体别名
    "捏下巴": "chin_lift", "抬下巴": "chin_lift", "掐下巴": "chin_lift",
    "扣手腕": "wrist_pin", "抓手腕": "wrist_pin", "按手腕": "wrist_pin",
    "松领带": "loosen_tie", "扯领带": "loosen_tie", "解袖扣": "loosen_tie",
    "壁咚": "wall_caging", "单手撑墙": "wall_caging", "撑墙封堵": "wall_caging",
    "扣后颈": "nape_grip", "按后颈": "nape_grip", "抓后颈": "nape_grip",
    "抵胸推拒": "chest_push", "推开": "chest_push", "推胸口": "chest_push",
    "护胸后退": "step_back_guard", "退到墙角": "step_back_guard", "后退抵桌": "step_back_guard",
    "偏头躲避": "turn_evade", "躲开": "turn_evade", "侧头抗拒": "turn_evade",
    "攥衣角": "clutch_fabric", "抓衣角": "clutch_fabric", "握拳隐忍": "clutch_fabric",
    "揪衣领": "grab_lapel", "抓衣领质问": "grab_lapel",
    "无力滑落": "collapse_sob", "掩面哭泣": "collapse_sob", "崩溃哭泣": "collapse_sob",
    "拍信物": "present_item", "甩证据": "present_item", "递房卡": "present_item",
    "揉眉心": "rub_temple", "扶额": "rub_temple", "叹气": "rub_temple",
    "整理衣领": "fix_attire", "挽头发": "fix_attire", "整理衣服": "fix_attire",
}


def load_matrix():
    with open(MATRIX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve(query):
    """把一句中文动作描述解析成 (pose_id, matrix_entry)"""
    m = load_matrix()
    q = query.strip()
    # 1) 精确别名
    if q in ALIAS:
        pid = ALIAS[q]
        return pid, m.get(pid)
    # 2) 模糊包含
    for alias, pid in ALIAS.items():
        if alias in q:
            return pid, m.get(pid)
    # 3) 直接 id / 中英文名
    for pid, it in m.items():
        if pid == q:
            return pid, it
        if it.get("nameZh") == q or it.get("nameEn", "").lower() == q.lower():
            return pid, it
    return None, None


def render_prompt(pid, entry, dur=10.0, aspect="9:16"):
    """Format a matrix entry with the current shared Ref2VA schema."""
    from whale_core import single_shot_prompt, dialogue_needed_seconds
    if not 0 < dur <= 12.25:
        raise ValueError("Single-shot duration must be within 0..12.25 seconds")
    line = entry.get("lineZh") or ""
    if dialogue_needed_seconds(line) > dur + 0.021:
        raise ValueError("Dialogue exceeds the single-shot duration")
    normalized_aspect = _validated_aspect(aspect)
    framing = entry.get("framingEn") or entry.get("framingZh") or "medium close-up"
    # Canvas geometry must not replace the matrix's subject count or shot scale.
    framing += f"; canvas aspect ratio {normalized_aspect}, preserving the specified shot scale and subject arrangement"
    camera_motion = "continuous subtle camera movement"
    beats = entry.get("beatsEn") or entry.get("beatsZh") or []
    if isinstance(beats, str):
        beats = [beats]
    shot = {"pose": pid, "size": "mcu", "text_en": "; ".join(beats)}
    prompt = single_shot_prompt(shot, 0, 1, dur, framing, camera_motion,
                                lines=line, scene=entry.get("sceneEn") or "current room", aspect=normalized_aspect)
    sfx = entry.get("sfxEn") or []
    if isinstance(sfx, str):
        sfx = [sfx]
    if sfx:
        prompt = prompt.replace("overall_soundscape: ", "overall_soundscape: " + ", ".join(sfx) + "; ", 1)
    return prompt


def resolve_scene(text, aspect="9:16"):
    """整段床戏剧本 -> 按顺序自动拆解出每个动作的提示词"""
    m = load_matrix()
    # 按常见标点/换行切分动作片段
    segs = re.split(r'[，。；;、\n]+', text)
    results = []
    for seg in segs:
        seg = seg.strip()
        if not seg:
            continue
        pid, entry = resolve(seg)
        if pid and entry:
            results.append((seg, pid, render_prompt(pid, entry, aspect=aspect)))
        else:
            results.append((seg, None, f"[!] 无法识别动作：{seg}（请查 --list 确认）"))
    return results


def _validated_aspect(value):
    aliases = {
        "9:16": "9:16", "portrait": "9:16", "竖屏": "9:16", "竖": "9:16",
        "9:16 (portrait widescreen)": "9:16",
        "16:9": "16:9", "landscape": "16:9", "widescreen": "16:9",
        "wide": "16:9", "横屏": "16:9", "横": "16:9", "16:9 (widescreen)": "16:9",
        "1:1": "1:1", "square": "1:1", "方屏": "1:1", "1:1 (square)": "1:1",
    }
    key = str(value).strip().lower()
    if key not in aliases:
        raise argparse.ArgumentTypeError("画幅必须是 9:16、16:9、1:1 或对应画幅别名")
    return aliases[key]


def main(argv=None):
    parser = argparse.ArgumentParser(description="吞鲸宝典动作矩阵提示词解析")
    parser.add_argument("query", nargs="?", help="动作名称或矩阵编号")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="列出全部动作")
    mode.add_argument("--scene", metavar="TEXT", help="按顺序解析动作片段")
    parser.add_argument("--aspect", type=_validated_aspect, default="9:16", help="9:16 / 16:9 / 1:1")
    args = parser.parse_args(argv)
    if args.query and (args.list or args.scene is not None):
        parser.error("动作名称不能与 --list 或 --scene 同时使用")
    if not args.list and args.scene is None and not args.query:
        parser.error("请提供动作名称、--scene 或 --list")
    try:
        if args.list:
            matrix = load_matrix()
            print(f"吞鲸宝典 · 可实时响应的 {len(matrix)} 套动作清单：")
            for pid, entry in matrix.items():
                print(f"  {pid:20s} | {entry.get('nameZh',''):12s} | {entry.get('nameEn','')}")
            return 0
        if args.scene is not None:
            if not args.scene.strip():
                parser.error("--scene 不能为空")
            results = resolve_scene(args.scene, aspect=args.aspect)
            failed = not results
            print("=" * 60)
            print("吞鲸宝典 · 整段动作自动拆解")
            print(f"剧本片段：{args.scene}")
            print("=" * 60)
            for segment, pid, prompt in results:
                if pid:
                    print(f"\n▶ 动作「{segment}」")
                else:
                    failed = True
                print(prompt)
            return 1 if failed else 0
        pid, entry = resolve(args.query)
        if not entry:
            print(f"[!] 未命中动作「{args.query}」，请用 --list 查看可用动作或换个说法。", file=sys.stderr)
            return 1
        print("=" * 60)
        print("吞鲸宝典 · 实时响应")
        print(f"需求「{args.query}」→ 命中吞鲸标准动作 [{pid}]")
        print("=" * 60)
        print(render_prompt(pid, entry, aspect=args.aspect))
        return 0
    except (OSError, ValueError) as exc:
        print(f"解析失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
