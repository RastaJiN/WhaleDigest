"""Opt-in local postproduction on a finished video; not a generation entry point."""
import argparse
from dataclasses import dataclass
from fractions import Fraction
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unicodedata

sys.dont_write_bytecode = True
from tunjing_prose import HEADING, dialogue_on

SCHEMA = 'tunjing-post-v1'
PLAN = '后期单.json'


def unique_keys(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError(f'JSON 重复键：{k}')
        result[k] = v
    return result


def fields(obj, label, required, optional=()):
    if not isinstance(obj, dict):
        raise ValueError(f'{label} 须为对象')
    missing = required - obj.keys()
    extra = obj.keys() - required - set(optional)
    if missing or extra:
        raise ValueError(f'{label} 字段错误：缺少 {sorted(missing)}；未知 {sorted(extra)}')


# Only complete dialogue records. A quoted prop, a production note or an
# embedded tag in a prompt is not a speaking turn. Never strip utterance text.
_SPEAKERS = set('s1 s2 女子a 男子a 女子 男子 女主 男主 女方 男方 女 男 她 他 甲 乙 旁白 画外音'.split())
_LABEL = r'(?P<who>[\w·-]+)(?:[（(][^()（）]*[）)])?'
_ROW = re.compile(r'(?:[-*] +)?(?:(?:\*\*|__)?' + _LABEL + r'(?:\*\*|__)?\s*[:：](?:\*\*|__)?\s*)?'
                  r'(?P<body>`?<d>(?:\[Chinese\])?[^<>]+</d>`?|“[^”]+”|「[^」]+」|[^`<>]+)')
_NON_SCRIPT = re.compile(r'动作注记|动作说明|动作|示例|范例|提示词|转写|梗概|大纲|草稿|舞台说明|prompt|transcript', re.I)


def body_lines(text):
    # Unlike shot planning, a new scene inside a notes section is still notes.
    excluded = 0
    note_block = False
    fence = ''
    text = re.sub(r'<!--.*?(?:-->|\Z)', lambda m: '\0' + '\n' * m[0].count('\n'), text, flags=re.S)
    for n, line in enumerate(text.splitlines(), 1):
        raw = line.strip()
        if fence:
            if re.fullmatch(re.escape(fence[0]) + '{' + str(len(fence)) + ',}', raw):
                fence = ''
            continue
        if line.startswith('    ') or line.startswith('\t'):
            continue
        mark = re.match(r'`{3,}|~{3,}', raw)
        if mark:
            fence = mark[0]
            continue
        h = HEADING.match(raw)
        if h:
            note_block = False
            level = len(h[1])
            if excluded >= level:
                excluded = 0
            if not excluded and _NON_SCRIPT.search(h[2]):
                excluded = level
        elif not raw:
            note_block = False
        elif not excluded and re.fullmatch(r'(?:[-*] +)?(?:动作注记|动作说明|舞台说明|提示词|转写)\s*[:：]?', raw):
            note_block = True
        elif not excluded and not note_block and not raw.startswith('>') and '\0' not in raw:
            yield n, raw


def dialogue_lines(root):
    text = (root / '剧本.md').read_text('utf-8-sig')
    speakers = _SPEAKERS.copy()
    cast = root / '角色映射.json'
    if cast.is_file():
        aliases = json.loads(cast.read_text('utf-8-sig'), object_pairs_hook=unique_keys)
        if not isinstance(aliases, dict) or any(v not in ('S1', 'S2') for v in aliases.values()):
            raise ValueError('角色映射.json 须为姓名到 S1/S2 的映射')
        speakers.update(k.casefold() for k in aliases)
    found = {}
    for n, raw in body_lines(text):
        m = _ROW.fullmatch(raw)
        if not m:
            continue
        who, body = m['who'], m['body']
        tagged = re.fullmatch(r'(`?)<d>(?:\[Chinese\])?([^<>]+)</d>\1', body)
        if (who and who.casefold() not in speakers) or (not who and not tagged):
            continue
        if tagged:
            words = tagged[2]
        else:
            # Strip only paired dialogue quotes. Ambiguous trailing action,
            # parentheticals or mixed formatting must be tagged at source.
            turns = dialogue_on(raw)
            if len(turns) != 1:
                continue
            words = turns[0]['text']
            if body not in (words, '“' + words + '”', '「' + words + '」'):
                continue
        if not re.search(r'[()（）\[\]【】]', words):
            found.setdefault(words, []).append(n)
    return found


def read_order(root, media):
    duration = media.duration_ms
    order = json.loads((root / PLAN).read_text('utf-8-sig'), object_pairs_hook=unique_keys)
    fields(order, PLAN, {'schema'}, ('subtitles', 'cards', 'music'))
    if order['schema'] != SCHEMA:
        raise ValueError(f'{PLAN} 的 schema 必须是 {SCHEMA}')
    for layer in ('subtitles', 'cards', 'music'):
        if not isinstance(order.setdefault(layer, []), list):
            raise ValueError(f'{layer} 须为数组')
    lines = dialogue_lines(root) if order['subtitles'] else {}
    sources = []
    for layer in ('subtitles', 'cards'):
        intervals = []
        for i, item in enumerate(order[layer]):
            label = f'{layer}[{i}]'
            required = {'start_ms', 'end_ms', 'text'}
            fields(item, label, required | {'kind'} if layer == 'cards' else required)
            if layer == 'cards' and item['kind'] != 'plain':
                raise ValueError(f'{label}.kind 只支持 plain 普通字卡，不支持复杂面板')
            a, b, s = item['start_ms'], item['end_ms'], item['text']
            if type(a) is not int or type(b) is not int or not 0 <= a < b <= duration:
                raise ValueError(f'{label} 须满足 0 ≤ start_ms < end_ms ≤ {duration}，且为整数毫秒')
            if (not isinstance(s, str) or not s.strip() or re.search(r'[{}\\<>]', s) or
                    any(unicodedata.category(c) in ('Cc', 'Cf', 'Cs', 'Zl', 'Zp') for c in s)):
                raise ValueError(f'{label}.text 须为单行纯文本，不能含 ASS/HTML 标记、反斜杠或控制字符')
            if len(s) > 3 * media.columns:
                raise ValueError(f'{label} 超过当前画幅三行安全区，请缩短字卡或重新选取完整短对白')
            origin = PLAN
            if layer == 'subtitles':
                if len(lines.get(s, [])) != 1:
                    raise ValueError(f'{label} 无法唯一核对到剧本.md 的完整对白原文（含标点）；请明确标注来源')
                origin = f'剧本.md:{lines[s][0]}'
            sources.append(f'{label} [{a}, {b}) ms ← {origin}：{s}')
            intervals.append((a, b, label))
        previous_end = 0
        for a, b, label in sorted(intervals):
            if a < previous_end:
                raise ValueError(f'{label} 与同层时段重叠')
            previous_end = b
    return order, sources


@dataclass(frozen=True)
class Media:
    width: int
    height: int
    duration_ms: int
    audio_tracks: int
    frames: int

    @property
    def font_size(self):
        return max(1, round(288 * .08 * min(self.width, self.height) / self.height))

    @property
    def columns(self):
        # Reserve 22% horizontal space, allowing even a run of wide glyphs.
        return max(1, int(self.width * .78 / (self.font_size * self.height / 288 * 1.15)))


def tool(cmd, cwd=None):
    env = {k: v for k, v in os.environ.items() if k != 'FFREPORT'}
    try:
        result = subprocess.run(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, encoding='utf8', errors='replace')
    except FileNotFoundError as exc:
        raise ValueError(f'需要本机 PATH 中的 {cmd[0]}') from exc
    if result.returncode or result.stderr.strip():
        raise ValueError(f'{cmd[0]} 失败：{result.stderr.strip()[-1200:]}')
    return result.stdout


# Local self-contained containers, never an FFmpeg playlist or concat script.
LOCAL = ['-protocol_whitelist', 'file', '-format_whitelist', 'mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi']


def ffmpeg(args, cwd=None):
    return tool(['ffmpeg', '-nostdin', '-n', '-hide_banner', '-v', 'error', '-xerror',
                 *LOCAL, *map(str, args)], cwd)


def probe(path):
    if not path.is_file():
        raise ValueError(f'找不到媒体文件：{path}')
    data = json.loads(tool(['ffprobe', '-v', 'error', *LOCAL, '-show_streams', '-show_format', '-of', 'json', str(path)]))
    streams = data.get('streams', [])
    videos = [s for s in streams if s['codec_type'] == 'video' and not s['disposition'].get('attached_pic')]
    if len(videos) != 1:
        raise ValueError(f'需要一条可播放的视频流：{path}')
    if any(s['codec_type'] not in ('video', 'audio') or s['disposition'].get('attached_pic') for s in streams):
        raise ValueError(f'包含未支持的附加轨（如内封字幕、封面图或数据轨），拒绝静默丢弃：{path}')
    video = videos[0]
    start = video.get('start_time')
    if start is not None and start != 'N/A' and abs(Fraction(start)) > Fraction(1, 1000):
        raise ValueError(f'视频流起点非零（{start}s），拒绝按错位时间轴叠加：{path}')
    seconds = video.get('duration')
    if not seconds and (tag := video.get('tags', {}).get('DURATION')):
        h, m, s = tag.split(':')
        seconds = int(h)*3600 + int(m)*60 + Fraction(s)
    if not seconds or seconds == 'N/A':
        raise ValueError(f'视频时长未知：{path}')
    width, height = video['width'], video['height']
    rotation = next((d['rotation'] for d in video.get('side_data_list', []) if 'rotation' in d), 0)
    if rotation % 90:
        raise ValueError(f'不支持非直角旋转，请先规范化输入：{path}')
    if rotation % 180:
        width, height = height, width
    # Header-only probing can accept a truncated MP4 with an intact index.
    try:
        progress = ffmpeg(['-i', path, '-map', '0:V:0', '-map', '0:a?', '-fps_mode', 'passthrough',
                           '-progress', 'pipe:1', '-nostats', '-f', 'null', '-'])
    except ValueError as exc:
        raise ValueError(f'{path.name} 解码失败：{exc}') from exc
    counts = re.findall(r'^frame=(\d+)$', progress, re.M)
    frames = int(counts[-1]) if counts else 0
    if not frames or (video.get('nb_frames', '').isdigit() and int(video['nb_frames']) != frames):
        raise ValueError(f'视频无帧或实际解码帧数与索引不符：{path}')
    return Media(width, height, round(Fraction(seconds) * 1000), sum(s['codec_type'] == 'audio' for s in streams), frames)


def stamp(ms):
    seconds, ms = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02},{ms:03}'


def picture(source, work, order, media):
    filters = []
    # libass force_style uses SSA alignment numbers (6 = top centre, not 8).
    for layer, align in [('subtitles', 2), ('cards', 6)]:
        if not order[layer]:
            continue
        # SRT packets pass milliseconds to libass (standalone ASS timestamps
        # would round to centiseconds). Only fixed ASCII filenames enter -vf.
        cues = sorted(order[layer], key=lambda c: c['start_ms'])
        records = []
        for i, c in enumerate(cues, 1):
            text = c['text']
            wrapped = '\n'.join(text[k:k+media.columns] for k in range(0, len(text), media.columns))
            records.append(f"{i}\n{stamp(c['start_ms'])} --> {stamp(c['end_ms'])}\n{wrapped}\n")
        (work / f'{layer}.srt').write_text('\n'.join(records), encoding='utf8')
        style = (f'Fontname=Microsoft YaHei,Fontsize={media.font_size},Alignment={align},MarginV=28,'
                 'MarginL=32,MarginR=32,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,'
                 'BorderStyle=1,Outline=1,Shadow=0')
        filters.append(f"subtitles={layer}.srt:force_style='{style}'")
    target = work / 'picture.mp4'
    video = (['-vf', ','.join(filters), '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
              '-fps_mode', 'passthrough'] if filters else ['-c:v', 'copy'])
    ffmpeg(['-i', source, '-map', '0:V:0', '-map', '0:a?', *video, '-c:a', 'copy', target], work)
    return target


def output_path(out):
    out = out.absolute()
    if os.path.lexists(out):
        raise ValueError(f'拒绝覆盖输入或已有目标：{out}')
    if out.suffix.lower() != '.mp4' or not out.parent.is_dir():
        raise ValueError('输出须为已有目录中的新 .mp4 文件')
    return out


def confirmed_music(root, items, media):
    if not items:
        return []
    if media.audio_tracks > 1:
        raise ValueError('配乐只支持无原声或一条原声；不自动丢弃多音轨')
    try:
        from tunjing_post_music import prepare_music
    except ImportError as exc:
        raise ValueError('缺少本机配乐确认模块，不能跳过 music 条目') from exc
    return prepare_music(root, items, media.duration_ms, require_confirmed=True)


def render(source, out, order, media, cues):
    if cues:
        try:
            from tunjing_post_music import mix_music
        except ImportError as exc:
            raise ValueError('缺少本机 mix_music，无法混音') from exc
    with tempfile.TemporaryDirectory(prefix='.tunjing-post-', dir=out.parent) as tmp:
        work = Path(tmp)
        target = picture(source, work, order, media)
        if cues:
            mixed = work / 'mixed.mp4'
            mix_music(target, mixed, cues, media.duration_ms)
            target = mixed
        actual = probe(target)
        tracks = 1 if cues else media.audio_tracks
        if ((actual.width, actual.height, actual.audio_tracks, actual.frames) != (media.width, media.height, tracks, media.frames)
                or abs(actual.duration_ms - media.duration_ms) > 2):
            raise ValueError(f'临时成片的尺寸、音轨或时长不符合输入：{actual}')

        # Both operations fail atomically if someone created out since preflight.
        try:
            (os.rename if os.name == 'nt' else os.link)(target, out)
        except FileExistsError:
            raise ValueError(f'拒绝覆盖刚出现的目标：{out}') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description='对已有成片核对或烧录独立字幕、普通字卡')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('check', 'render'):
        sub = commands.add_parser(name)
        sub.add_argument('project', type=Path)
        sub.add_argument('--input', required=True, type=Path)
        if name == 'render':
            sub.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        source = args.input.resolve()
        root = args.project.resolve()
        out = output_path(args.out) if args.command == 'render' else None
        media = probe(source)
        order, sources = read_order(root, media)
        cues = confirmed_music(root, order['music'], media)
        if out:
            render(source, out, order, media, cues)
        print(f'{media.width}×{media.height}，{media.duration_ms} ms；{PLAN}')
        for line in sources:
            print(line)
        for i, item in enumerate(order['music']):
            print(f"music[{i}] ← {item['file']}（{item['id']} 已确认）")
        if out:
            print(f'已交付：{out}')
    except (OSError, ValueError) as exc:
        print(f'后期失败：{exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
