#!/usr/bin/env python3
"""逐条审阅本机已有的配乐；与 H3 签字、生成服务无关。"""
import argparse
from contextlib import contextmanager
from fractions import Fraction
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PLAN = "后期单.json"
LEDGER = ".tunjing-post-music.json"
TICKETS = "tunjing-local-music-approvals-v1"
FIELDS = ("id", "file", "start_ms", "end_ms", "gain_db")
DOMAIN = b"tunjing-local-music-cue-v1\0"
NOTICE = "仅采用本机已有配乐；不是 H3 签字，也不授权外部生成或付费。"
MAX_MS = 24 * 60 * 60 * 1000
ID = re.compile(r"MUSIC-[A-Z0-9][A-Z0-9_-]{0,47}")
DIGEST = re.compile(r"[0-9a-f]{64}")
DEVICE = re.compile(r"(?:CON|AUX|NUL|PRN|CONIN\$|CONOUT\$|(?:LPT|COM)[0-9]+)(?:\..*)?", re.I)
AUDIO = {".wav": "wav", ".flac": "flac", ".mp3": "mp3", ".ogg": "ogg"}
VIDEO = {".mp4": "mov", ".mov": "mov"}
FORMAT = "aformat=sample_rates=48000:channel_layouts=stereo:sample_fmts=fltp"


def _link(path):
    st = path.lstat()
    return (stat.S_ISLNK(st.st_mode) or
            bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT) or
            st.st_nlink != 1)


def _local(root, name):
    # Use the same portable spelling on Windows and POSIX. Reject drive-relative paths and ADS too.
    if not isinstance(name, str) or re.search(r'[\\:<>"|?*\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]', name):
        raise ValueError(f"须使用项目相对路径：{name!r}")
    parts = name.split("/")
    if any(p in ("", ".", "..") or p.endswith((".", " ")) or
           DEVICE.fullmatch(p) for p in parts):
        raise ValueError(f"不安全的项目路径：{name!r}")
    path = root
    for p in parts:
        path = path / p
        if _link(path):
            raise ValueError(f"不接受符号链接或重解析点：{name!r}")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"不是项目内文件：{name!r}")
    return resolved


def _unique(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise ValueError(f"JSON 字段重复：{k!r}")
        obj[k] = v
    return obj


def _json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique)


def _plan(root):
    plan = _json(_local(root, PLAN))
    if not isinstance(plan, dict) or plan.get("schema") != "tunjing-post-v1":
        raise ValueError(f"{PLAN} 须声明 schema=tunjing-post-v1")
    return plan


def _audio_hash(path, copy_to=None):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
            if copy_to is not None:
                copy_to.write(block)
    return h.digest()


def _fingerprint(spec, audio_digest):
    payload = json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(DOMAIN + payload.encode("utf-8") + b"\0" + audio_digest).hexdigest()


def _run(cmd):
    try:
        result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8",
                                errors="replace", env={k: v for k, v in os.environ.items() if k != "FFREPORT"})
    except FileNotFoundError as exc:
        raise ValueError(f"需要本机 PATH 中的 {cmd[0]}") from exc
    if result.returncode or result.stderr.strip():
        raise ValueError(f"{cmd[0]} 失败：{result.stderr.strip()[-900:]}")
    return result.stdout


def _input(path, formats):
    try:
        demuxer = formats[path.suffix.lower()]
    except KeyError:
        raise ValueError(f"不支持的本机媒体格式：{path.name}") from None
    # No manifests, protocols, autodetected demuxers or user filter strings.
    local_only = ["-enable_drefs", "0", "-use_absolute_path", "0"] if demuxer == "mov" else []
    return ["-protocol_whitelist", "file", "-f", demuxer, *local_only, "-i", str(path)]


def _layout(channels):
    # FFmpeg's default mono-to-stereo matrix attenuates both sides by 3 dB.
    return ("pan=stereo|c0=c0|c1=c0," if channels == 1 else "") + FORMAT


def _window(ms, channels=None):
    return f"{_layout(channels)},atrim=end_sample={ms * 48},asetpts=N/SR/TB"


def _check_audio(path, ms):
    # Measure actually decoded samples, not a container duration (which can describe another stream).
    progress = _run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", *_input(path, AUDIO), "-map", "0:a:0",
                     "-af", _window(ms), "-progress", "pipe:1", "-nostats", "-f", "null", "-"])
    times = re.findall(r"^out_time_us=(\d+)$", progress, re.M)
    if not times or int(times[-1]) != ms * 1000:
        raise ValueError(f"实解音轨不足 {ms} ms，不补齐、不循环")


def _duration(ms):
    if type(ms) is not int or not 0 < ms <= MAX_MS:
        raise ValueError(f"duration_ms 须为 1..{MAX_MS} 的整数")


def _specs(items, duration_ms):
    _duration(duration_ms)
    if not isinstance(items, list) or len(items) > 32:
        raise ValueError("music 须为数组，至多 32 条")
    seen = set()
    specs = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict) or item.keys() != set(FIELDS):
            raise ValueError(f"music[{idx}] 须且只可包含 {', '.join(FIELDS)}")
        ident, a, b, gain = (item[k] for k in ("id", "start_ms", "end_ms", "gain_db"))
        if not isinstance(ident, str) or not ID.fullmatch(ident) or ident in seen:
            raise ValueError(f"music[{idx}] ID 无效或重复：{ident!r}")
        if type(a) is not int or type(b) is not int or not 0 <= a < b <= duration_ms:
            raise ValueError(f"{ident} 需要 0 ≤ start_ms < end_ms ≤ {duration_ms} 的整数时窗")
        if type(gain) not in (int, float) or not math.isfinite(gain) or not -60 <= gain <= 6:
            raise ValueError(f"{ident} gain_db 须为 [-60, +6] 的有限数")
        seen.add(ident)
        specs.append(dict(item))
    return specs


def _inspect(root, items, duration_ms):
    cues = []
    for spec in _specs(items, duration_ms):
        try:
            path = _local(root, spec["file"])
            _check_audio(path, spec["end_ms"] - spec["start_ms"])
            sha = _fingerprint(spec, _audio_hash(path))
        except (OSError, ValueError) as exc:
            raise ValueError(f"{spec['id']}：{exc}") from exc
        cues.append({**spec, "sha256": sha, "_root": str(root)})
    return cues


def _receipts(root):
    if not os.path.lexists(root / LEDGER):
        return {}
    data = _json(_local(root, LEDGER))
    if (not isinstance(data, dict) or data.keys() != {"schema", "confirmed"} or
            data["schema"] != TICKETS or not isinstance(data["confirmed"], dict) or
            any(not ID.fullmatch(k) or not isinstance(v, str) or not DIGEST.fullmatch(v)
                for k, v in data["confirmed"].items())):
        raise ValueError(f"{LEDGER} 不是有效的本机配乐票据，不读取、不覆盖")
    return data["confirmed"]


def prepare_music(root: Path, items: list, duration_ms: int, *, require_confirmed=True) -> list:
    """Check these cues against the supplied picture length; never write or confirm anything."""
    root = Path(root).resolve(strict=True)
    cues = _inspect(root, items, duration_ms)
    saved = _receipts(root) if cues else {}
    missing = []
    for cue in cues:
        cue["confirmed"] = saved.get(cue["id"]) == cue["sha256"]
        if not cue["confirmed"]:
            missing.append(cue["id"])
    if require_confirmed and missing:
        raise ValueError("以下配乐未确认或已过期，请重新 preview：" + ", ".join(missing))
    return cues


@contextmanager
def _writer(root):
    # Serialize read/merge/replace, not just the final rename. Never take over a stale lock.
    lock = root / ".tunjing-post-music.lock"
    deadline = time.monotonic() + 5
    while True:
        try:
            lock.mkdir(mode=0o700)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ValueError(f"另有配乐确认正在写入或遗留锁 {lock.name}，未更改票据") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.rmdir()


def _confirm(root, ident, sha):
    if not ID.fullmatch(ident) or not DIGEST.fullmatch(sha):
        raise ValueError("请指定一个配乐 ID 和预览中完整的 64 位小写 SHA256")
    with _writer(root):
        saved = _receipts(root)
        cues = _inspect(root, _plan(root).get("music", []), MAX_MS)
        current = {c["id"]: c["sha256"] for c in cues}
        if current.get(ident) != sha:
            raise ValueError(f"{ident} 不存在或 SHA256 与当前条目不符；请重新 preview")
        keep = {k: v for k, v in saved.items() if current.get(k) == v}
        keep[ident] = sha
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, prefix=".music-", delete=False) as f:
            tmp = Path(f.name)
        try:
            tmp.write_text(json.dumps({"schema": TICKETS, "confirmed": keep}, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
            os.replace(tmp, root / LEDGER)
        finally:
            tmp.unlink(missing_ok=True)
    print(f"已确认 {ident}  SHA256={sha}。{NOTICE}")


def _preview(root):
    items = prepare_music(root, _plan(root).get("music", []), MAX_MS, require_confirmed=False)
    for spec in items:
        print(f"{spec['id']}  {spec['file']}  [{spec['start_ms']}, {spec['end_ms']}) ms  "
              f"{spec['gain_db']} dB  {'已确认' if spec['confirmed'] else '待确认'}  SHA256={spec['sha256']}")
    if not items:
        print("无配乐条目。")
    print(NOTICE)
    print("请听取素材、核对时段与增益；仅在用户明确选定后执行 confirm PROJECT --id 条目ID --sha256 看过的完整指纹。")


def _probe(path, formats):
    raw = _run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", *_input(path, formats)])
    return json.loads(raw)["streams"]


def _streams(path, duration_ms):
    streams = _probe(path, VIDEO)
    video = [s for s in streams if s["codec_type"] == "video" and not s["disposition"].get("attached_pic")]
    audio = [s for s in streams if s["codec_type"] == "audio"]
    if len(video) != 1 or len(audio) > 1 or len(streams) != len(video) + len(audio):
        raise ValueError("只接受一条画面、零或一条原声的已合成素材；不静默丢弃附加轨")
    v = video[0]
    if Fraction(v.get("start_time", "0")) != 0 or round(Fraction(v.get("duration", "0")) * 1000) != duration_ms:
        raise ValueError("实际画面时长与 duration_ms 不符，或画面不从零开始；不会裁剪或移动画面")
    return v, (audio[0] if audio else None)


def _stage(cues, duration_ms, work):
    """Match the current order/ledger; FFmpeg only opens snapshots of the exact verified bytes."""
    if not isinstance(cues, list) or any(not isinstance(c, dict) or not isinstance(c.get("_root"), str)
                                        or not set(FIELDS).issubset(c) for c in cues):
        raise ValueError("cues 须来自 prepare_music")
    if not cues:
        return []
    root = Path(cues[0]["_root"]).resolve(strict=True)
    specs = _specs([{k: cue[k] for k in FIELDS} for cue in cues], duration_ms)
    current = {s["id"]: s for s in _specs(_plan(root).get("music", []), duration_ms)}
    saved = _receipts(root)
    staged = []
    for i, (spec, cue) in enumerate(zip(specs, cues)):
        ident = spec["id"]
        if (cue["_root"] != str(root) or current.get(ident) != spec or ident not in saved
                or saved[ident] != cue.get("sha256")):
            raise ValueError(f"{ident} 清单或配乐确认已变更或未确认，请重新 preview")
        try:
            path = _local(root, spec["file"])
            dest = work / f"cue-{i}{path.suffix.lower()}"
            with dest.open("xb") as f:
                sha = _fingerprint(spec, _audio_hash(path, f))
            if sha != saved[ident]:
                raise ValueError("音频字节已变更，旧票据过期")
            staged.append((spec, dest))
        except (OSError, ValueError) as exc:
            raise ValueError(f"{ident}：{exc}") from exc
    return staged


def _mix(source, output, staged, duration_ms, original):
    n = duration_ms * 48
    inputs = _input(source, VIDEO)
    base = (f"[0:a:0]aresample=48000:async=1:first_pts=0,{_layout(original['channels'])},apad=whole_len={n}" if original
            else f"anullsrc=r=48000:cl=stereo,{FORMAT}")
    filters = [f"{base},atrim=end_sample={n},asetpts=N/SR/TB[a0]"]
    for i, (spec, path) in enumerate(staged, 1):
        inputs.extend(_input(path, AUDIO))
        start = spec["start_ms"]
        stream = next((s for s in _probe(path, AUDIO) if s["codec_type"] == "audio"), None)
        if not stream:
            raise ValueError(f"{spec['id']} 无音轨")
        filters.append(f"[{i}:a:0]{_window(spec['end_ms'] - start, stream['channels'])},volume={spec['gain_db']}dB,"
                       f"adelay={start * 48}S:all=1[a{i}]")
    count = len(filters)
    labels = "".join(f"[a{i}]" for i in range(count))
    filters.append(f"{labels}amix=inputs={count}:duration=first:normalize=0:dropout_transition=0[out]")
    # A lossless audio stream avoids transform-codec pre-echo outside the cue window.
    _run(["ffmpeg", "-nostdin", "-n", "-v", "error", "-xerror", "-copyts", *inputs,
          "-filter_complex", ";".join(filters), "-map", "0:V:0", "-map", "[out]", "-c:v", "copy",
          "-c:a", "alac", "-sample_fmt", "s32p", "-avoid_negative_ts", "disabled", str(output)])


def mix_music(source: Path, target: Path, cues, duration_ms: int) -> Path:
    """Mix verified local cues into a NEW MP4; never overwrite an existing path."""
    _duration(duration_ms)
    source = Path(source).resolve(strict=True)
    target = Path(target).absolute()
    if not source.is_file() or target.suffix.lower() != ".mp4" or not target.parent.is_dir():
        raise ValueError("需要本机视频文件，以及已有目录中的新 .mp4 目标")
    if os.path.lexists(target):
        raise ValueError(f"不覆盖已有文件或链接：{target}")
    video, original = _streams(source, duration_ms)
    with tempfile.TemporaryDirectory(prefix=".tunjing-mix-", dir=target.parent) as tmp:
        work = Path(tmp)
        staged = _stage(cues, duration_ms, work)
        out = work / "mixed.mp4"
        _mix(source, out, staged, duration_ms, original)
        result, audio = _streams(out, duration_ms)
        if (any(result.get(k) != video.get(k) for k in ("codec_name", "width", "height", "nb_frames")) or
                not audio or (audio.get("sample_rate"), audio.get("channels")) != ("48000", 2) or
                Fraction(audio["duration_ts"]) * Fraction(audio["time_base"]) != Fraction(duration_ms, 1000)):
            raise ValueError("未交付：输出画面或音轨不符合规格")
        # Same filesystem; publish atomically without clobbering an intervening creator's file.
        try:
            (os.rename if os.name == "nt" else os.link)(out, target)
        except FileExistsError:
            raise ValueError(f"不覆盖刚出现的目标：{target}") from None
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preview").add_argument("project", type=Path)
    confirm = sub.add_parser("confirm", allow_abbrev=False)
    confirm.add_argument("project", type=Path)
    confirm.add_argument("--id", action="append", required=True)
    confirm.add_argument("--sha256", action="append", required=True)
    args = parser.parse_args(argv)
    try:
        root = args.project.resolve(strict=True)
        if args.command == "preview":
            _preview(root)
        elif len(args.id) == len(args.sha256) == 1:
            _confirm(root, args.id[0], args.sha256[0])
        else:
            raise ValueError("每次确认仅能选择一个 ID 和一个完整 SHA256")
        return 0
    except (OSError, ValueError) as exc:
        print(f"配乐：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
