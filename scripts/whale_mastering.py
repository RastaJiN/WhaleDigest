#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
吞鲸宝典 v4.7.0 · 母带音画精修与声学特效缝合引擎 (WhaleDigest v4.7.0 Audio-Visual Mastering Engine)

核心特性：
1. 首部 2 帧“起势微顿帧”自动修剪 (`--trim-head-frames 2`，即 0.083s)：切除扩散模型从参考图刚起势的微僵硬帧，保留最流畅的中后段动量。
2. EBU R128 广播级响度统一 (`loudnorm=I=-16:TP=-1.5:LRA=11`)：彻底解决各镜头独立生成导致的台词/喘息音量忽大忽小。
3. 声学特效自动挂载（Phone Bandpass & Inner Monologue Reverb）：
   - 自动读取 `批量任务.json` 中每镜的 `audio_fx_mode`（或根据台词标注自动识别）：
   - `phone`（电话/听筒/免提对白）：自动注入 `highpass=f=300,lowpass=f=3400,acompressor=threshold=-18dB:ratio=3` 真实电话滤波音质；
   - `inner_os`（内心独白/心声）：自动注入 `aecho=0.8:0.88:45:0.28` 轻空间混响；
   - `normal`（同期实录干声）：保持纯净同期声场。
4. 切点爆音消除与呼吸微淡化：对每镜首尾音频施加 0.08s 微淡入 (`afade`)，彻底消灭硬切处的波形阶跃爆音，最终无损合并为全集母带 MP4！
"""

import os
import sys
import glob
import json
import re
import subprocess
import argparse
import tempfile
from fractions import Fraction
from whale_task_source import load_task_source
from whale_media import find_clip, probe_media


def load_shot_audio_fx_map(project_dir):
    """从 批量任务.json 读取每个镜头的声学特效模式 (`normal` / `phone` / `inner_os`)"""
    bj_path = os.path.join(project_dir, "批量任务.json")
    fx_map = {}
    try:
        _, data, _ = load_task_source(project_dir)
        for idx, s in enumerate(data.get("batch_shots") or data.get("shots") or [], 1):
            mode = s.get("audio_fx_mode", "normal")
            prompt_txt = s.get("prompt", "")
            if mode == "normal" and "off-screen voiceover" in prompt_txt:
                mode = "inner_os"
            fx_map[f"shot_{idx:02d}"] = mode
            fx_map[f"shot_{idx}"] = mode
            fx_map[f"EP001_SHOT_{idx:03d}"] = mode
            if s.get("shot_id"):
                fx_map[s["shot_id"]] = mode
            if s.get("filename_prefix"):
                fx_map[s.get("filename_prefix")] = mode
    except Exception:
        pass
    return fx_map


def build_audio_filter_chain(fx_mode="normal", normalize_audio=True):
    """
    构建 FFmpeg 音频滤镜链：
    - phone: 300Hz–3400Hz 带通滤波 + 听筒动态压缩
    - inner_os: 45ms 轻空间混响 (aecho)
    - EBU R128 (-16 LUFS) 响度标准化 + 0.08s 首部消爆音微淡入
    """
    filters = []
    if fx_mode == "phone":
        filters.append("highpass=f=300,lowpass=f=3400,acompressor=threshold=-18dB:ratio=3:attack=5:release=50")
    elif fx_mode == "inner_os":
        filters.append("aecho=0.8:0.88:45:0.28")

    if normalize_audio:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    filters.append("afade=t=in:st=0:d=0.08")
    return ",".join(filters)


def process_single_clip(in_mp4, out_mp4, trim_head_frames=2, fps=24.0, normalize_audio=True, fx_mode="normal"):
    """
    对单个镜头执行：
    1) 切掉开头 trim_head_frames 帧（默认 2 帧 = 0.0833 秒）
    2) 挂载电话带通滤波 (300-3400Hz) 或内心独白轻混响
    3) 音频响度标准化 (-16 LUFS) + 首部 0.08s 微淡化防爆音
    """
    temporary = None
    try:
        media = probe_media(in_mp4)
        trim_frames = max(0, int(trim_head_frames))
        video = next(s for s in media["streams"] if s.get("codec_type") == "video")
        rate = float(Fraction(video.get("avg_frame_rate") or video.get("r_frame_rate") or str(fps)))
        ss_sec = trim_frames / rate
        duration = float(video.get("duration") or media.get("format", {}).get("duration", 0))
        remaining = duration - ss_sec
        if remaining <= 0:
            raise ValueError("Head trim removes the entire clip")
        fd, temporary = tempfile.mkstemp(suffix=".mp4", dir=os.path.dirname(os.path.abspath(out_mp4)))
        os.close(fd)
        has_audio = any(x.get("codec_type") == "audio" for x in media["streams"])
        cmd = ["ffmpeg", "-y", "-i", in_mp4]
        if not has_audio:
            # Give every clip the same stream layout so concat retains later dialogue.
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        cmd += ["-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0",
                "-vf", f"trim=start_frame={trim_frames},setpts=PTS-STARTPTS",
                "-fps_mode", "passthrough",
                "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p",
                "-af", (f"atrim=start={ss_sec if has_audio else 0},asetpts=PTS-STARTPTS,"
                        + build_audio_filter_chain(fx_mode, normalize_audio)
                        + f",apad=whole_dur={remaining},atrim=duration={remaining}"),
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2"]
        cmd.append(temporary)
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode:
            print("[X] 单镜精修失败: " + result.stderr)
            return False
        probe_media(temporary)
        os.replace(temporary, out_mp4)
        return True
    except (OSError, ValueError) as exc:
        print(f"[X] 单镜精修失败: {exc}")
        return False
    finally:
        if temporary and os.path.exists(temporary):
            os.remove(temporary)


def master_episode(project_dir, trim_head_frames=2, out_name="全集精修母带_Mastered.mp4"):
    in_dir = os.path.join(project_dir, "02_成片输出")
    if not os.path.isdir(in_dir):
        print(f"[i] 目录 {in_dir} 尚未生成切片（请先在 ComfyUI 渲染出片后运行本脚本）。")
        return False

    try:
        _, batch, _ = load_task_source(project_dir)
        selected = batch.get("batch_shots") or batch.get("shots") or []
        main_clips = [find_clip([in_dir], shot.get("filename_prefix") or shot.get("shot_id") or shot.get("id") or f"shot_{i}") for i, shot in enumerate(selected, 1)]
    except (OSError, ValueError) as exc:
        print(f"[X] 无法读取当前任务: {exc}")
        return False
    if not main_clips or any(clip is None for clip in main_clips):
        print("[X] 当前任务的主版本镜头缺失，已停止母带合成。")
        return False

    fx_map = load_shot_audio_fx_map(project_dir)
    work_dir = os.path.join(project_dir, "04_母带精修缓存")
    os.makedirs(work_dir, exist_ok=True)

    processed_list = []
    print(f"[▶] 正在对 {len(main_clips)} 个镜头执行【首部 {trim_head_frames} 帧微修剪 + 电话/独白声学滤波 + EBU R128 (-16 LUFS) 响度统一】...")
    for index, (shot, c) in enumerate(zip(selected, main_clips), 1):
        bn = os.path.basename(c)
        # Resolve effects from task identity; ComfyUI appends output counters/suffixes.
        identity = shot.get("filename_prefix") or shot.get("shot_id") or f"shot_{index:02d}"
        fx_mode = fx_map.get(identity, "normal")
        out_c = os.path.join(work_dir, f"norm_{bn}")
        if process_single_clip(c, out_c, trim_head_frames=trim_head_frames, fx_mode=fx_mode):
            processed_list.append(out_c)
        else:
            return False

    # Stream-copy concatenation requires one stable canvas and frame rate.
    try:
        from whale_scene import normalize_aspect
        aspect = normalize_aspect(batch.get("aspect", "9:16"))
        aw, ah = map(int, aspect.split(":"))
        expected_ratio = aw / ah
        formats = []
        for clip in processed_list:
            stream = next(s for s in probe_media(clip)["streams"] if s.get("codec_type") == "video")
            width, height = int(stream["width"]), int(stream["height"])
            rate = Fraction(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1")
            if not width or not height or rate <= 0:
                raise ValueError("Invalid video dimensions or frame rate: " + clip)
            if abs(width / height / expected_ratio - 1) > .01:
                raise ValueError(f"Video canvas {width}x{height} does not match batch aspect {aspect}: {clip}")
            formats.append((width, height, rate))
        if len(set(formats)) != 1:
            raise ValueError("Standardized clips have inconsistent dimensions or frame rates")
    except (OSError, ValueError, KeyError, StopIteration, ZeroDivisionError) as exc:
        print(f"[X] 母带流规格不一致: {exc}")
        return False

    concat_txt = os.path.join(work_dir, "concat_list.txt")
    with open(concat_txt, "w", encoding="utf-8") as f:
        for p in processed_list:
            safe_p = os.path.abspath(p).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{safe_p}'\n")

    final_out = os.path.join(project_dir, out_name)
    temporary_final = final_out + ".partial.mp4"
    cmd_concat = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_txt, "-c", "copy", temporary_final
    ]
    try:
        result = subprocess.run(cmd_concat, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode:
            print("[X] 母带合成失败: " + result.stderr)
            return False
        probe_media(temporary_final)
        os.replace(temporary_final, final_out)
    except (OSError, ValueError) as exc:
        print(f"[X] 母带合成失败: {exc}")
        return False
    if os.path.exists(final_out):
        print(f"[✓] 母带精修合成完毕: {final_out} (大小: {os.path.getsize(final_out)/1024/1024:.2f} MB)")
        return True
    return False


def main():
    ap = argparse.ArgumentParser(description="吞鲸 v4.7.0 母带音画精修与声学特效缝合引擎")
    ap.add_argument("project_dir", help="项目目录路径")
    ap.add_argument("--trim-head-frames", type=int, default=2, help="每镜切除首部起势微顿帧数（默认2帧=0.08s，设0则不切）")
    ap.add_argument("--out-name", default="全集精修母带_Mastered.mp4", help="输出母带文件名")
    args = ap.parse_args()

    return 0 if master_episode(args.project_dir, trim_head_frames=args.trim_head_frames, out_name=args.out_name) else 1


if __name__ == "__main__":
    sys.exit(main())
