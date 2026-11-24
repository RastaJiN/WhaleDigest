#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WhaleDigest · 体位真源与翻车体位转换器 (Pose Truth & Safe Fallback Guard)
1. 剧本/分镜期：强制校验 adult_drama 肉戏镜头必须命中 94 条真源 (whale_poses_matrix.json)
2. 擦屁股/修片期：提供高危/易穿模体位 -> 安全可落地体位转换映射
"""
import json
from pathlib import Path

POSES_FILE = Path(__file__).resolve().parent.parent / "references" / "whale_poses_matrix.json"

# 实片验证过的高危/易翻车体位或写法 -> 安全可落地体位转换表
SAFE_POSE_FALLBACKS = {
    "standing_carry": ("missionary", "悬空抱操在 H3 极易断肢穿模，降级为 missionary（传教士）或 cowgirl（女上）+ 近景情绪反馈"),
    "standing_fuck": ("doggy", "站立后入易出现腿部畸变，建议转为 doggy（跪姿后入）或 pov_insert（第一视角插入特写）"),
    "69_standing": ("sixty_nine", "站立69必崩，转为标准卧姿 sixty_nine"),
    "acrobatic": ("cowgirl", "高难度杂技体位拆解为 cowgirl + breast_rub 递进"),
    "reverse_standing": ("reverse_cowgirl", "站立背入转为坐/跪姿 reverse_cowgirl"),
}


def load_poses_matrix():
    if not POSES_FILE.exists():
        return {}
    return json.loads(POSES_FILE.read_text(encoding="utf-8"))


def suggest_safe_pose(pose_id: str):
    key = (pose_id or "").strip().lower()
    if key in SAFE_POSE_FALLBACKS:
        target, reason = SAFE_POSE_FALLBACKS[key]
        return {"fallback": target, "reason": reason}
    return None


def validate_pose_entry(pose_id: str, project_mode: str = "standard_drama"):
    """
    校验体位是否在 94 条真源内；正剧模式下禁止出现肉戏体位。
    返回 (ok: bool, errors: list[str], warnings: list[str])
    """
    errors, warnings = [], []
    is_adult = (project_mode or "").lower() in {"adult_drama", "erotic", "nsfw", "adult"}
    pid = (pose_id or "").strip()

    if not is_adult:
        if pid:
            errors.append(f"正剧模式 ({project_mode}) 禁止挂载肉戏体位: {pid}")
        return (len(errors) == 0, errors, warnings)

    if not pid:
        return (True, errors, warnings)

    fb = suggest_safe_pose(pid)
    if fb:
        errors.append(f"高危翻车体位 '{pid}' 被拦截 -> 请转换为 '{fb['fallback']}' ({fb['reason']})")
        return (False, errors, warnings)

    matrix = load_poses_matrix()
    if matrix and pid not in matrix:
        errors.append(f"体位 '{pid}' 不在 94 条真源 (whale_poses_matrix.json) 中，禁止模型自造体位")

    return (len(errors) == 0, errors, warnings)
