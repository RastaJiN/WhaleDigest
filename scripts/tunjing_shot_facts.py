"""Reconcile the machine-written execution board, not the director's prose."""
import json
import re

if __package__:
    from . import tunjing_blocking as blocking
else:
    import tunjing_blocking as blocking

_HEADER = '<!-- tunjing:execution-inputs '
_INPUTS = '- 执行输入：'
_SHOT = re.compile(r'^### SHOT-(\d+) \[Track: Ref2V\]$', re.M)


def header(sources, pose_inputs):
    # The execution board cannot include its own file hash. Everything upstream
    # (including the finalized JSON snapshot, if reviewed) already has a hash.
    return _HEADER + json.dumps([sources, pose_inputs], ensure_ascii=False, sort_keys=True) + ' -->'


def slot_prefix(tier, zone, images):
    return f'- 槽位分级: `{tier}` (空间锚点 `{zone}`: `{images}` | '


def input_note(source_shot, references, audio_fx_mode, actor, explicit_voiceover):
    # These input facts are not on the pre-existing slot and blocking lines.
    facts = dict(source_shot=source_shot, references=references, audio_fx_mode=audio_fx_mode)
    if actor:
        facts['actor'] = actor
        if explicit_voiceover:
            facts['voiceover'] = True
    return _INPUTS + json.dumps(facts, ensure_ascii=False)


def _check_speech(lines, row, inputs, where):
    # Read only machine fields. The voice ID lives before the quoted words;
    # the listener's Picture slot and words like “画外音” inside a line are irrelevant.
    quotes = [s for s in lines if s.startswith('- 台词: ')]
    speech = [s for s in row['prompt'].splitlines() if s.startswith('SPEECH:')]
    actor = inputs.get('actor')
    if not actor and not quotes and not speech and 'dialogue' not in row:
        return
    if not actor or len(quotes) != 1 or len(speech) != 1:
        raise ValueError(f'{where}：执行分镜与 SPEECH 台词数不符')
    name, sep, words = quotes[0][len('- 台词: '):].partition('：<d>[Chinese]')
    head, tag, rest = speech[0].partition('<d>[Chinese]')
    if (not sep or not tag or not words.endswith('</d>') or rest.partition('</d>')[0] != words[:-4]
            or re.findall(r'\((?:voice )?(S[12])\)', head) != [actor]
            or (inputs.get('voiceover') and 'off-screen voiceover' not in head)):
        raise ValueError(f'{where}：SPEECH 的声源或台词与执行分镜不符')
    if 'dialogue' in row:
        d = row['dialogue']
        if (not isinstance(d, dict) or (d.get('actor'), d.get('speaker'), d.get('part_text', d.get('text')))
                != (actor, name, words[:-4])):
            raise ValueError(f'{where}：dialogue 与执行分镜不符')


def _read_board(path):
    return path.read_text(encoding='utf-8-sig') if path.is_file() else ''


def _seal(text):
    first, _, body = text.partition('\n')
    return body.partition('\n')[0] if first.startswith('<!-- tunjing:generated-board sha256=') and body.startswith(_HEADER) else None


def verify(root, batch):
    name = batch.get('execution_board', '分镜.md')
    text = _read_board(blocking.project_file(root, name))
    seal = _seal(text)
    if not seal and name == '分镜.md' and not blocking.untouched_board(text):
        if _seal(_read_board(blocking.project_file(root, blocking.EXEC_BOARD))):
            raise ValueError('项目已有绑定的执行分镜；不能改用未绑定批次')
    if seal:
        hashes = batch.get('blocking_input_hashes', {})
        sources = {k: v for k, v in hashes.items() if k != name}
        if (name != batch.get('execution_board') or name not in hashes or
                not blocking.untouched_board(text) or seal != header(sources, batch.get('pose_input_hashes'))):
            raise ValueError('执行分镜的采用稿或已决快照绑定不符；请重新编译')
    elif not ((name == blocking.EXEC_BOARD or batch.get('pose_input_hashes')) and blocking.untouched_board(text)):
        return  # No machine-owned shot facts. Do not parse a human or legacy board.

    chunks = _SHOT.split(text)[1:]
    rows = batch.get('batch_shots')
    if not isinstance(rows, list) or len(chunks) != 2 * len(rows):
        raise ValueError('执行分镜与批量任务的镜数不符')
    for n, (label, body, row) in enumerate(zip(chunks[::2], chunks[1::2], rows), 1):
        where = f'SHOT-{n:02d}'
        if (not isinstance(row, dict) or label != f'{n:02d}' or
                row.get('id') != f'shot_{n}' or row.get('shot_id') != f'shot_{n:02d}'):
            raise ValueError(f'{where}：执行分镜与批量任务的镜号或顺序不符')
        lines = body.splitlines()
        try:
            plan = row['blocking_state']
            if '\n' + blocking.board_note(plan) + '\n' not in body:
                raise ValueError(f'{where}：调度或空间承接与执行分镜不符')
            slots = slot_prefix(row['tier'], row['spatial_zone'], row['ref_images'])
            if not isinstance(row['ref_images'], list) or not any(line.startswith(slots) for line in lines):
                raise ValueError(f'{where}：入画槽位或有序 ref_images 与执行分镜不符')
            for label, field, suffix in (('景别', 'shot_size', ' — '), ('机位', 'camera_motion', ' — '),
                                         ('姿势', 'pose', '` (')):
                prefix = f'- {label}: ' + ('`' if field == 'pose' else '') + row[field] + suffix
                if not any(line.startswith(prefix) for line in lines):
                    raise ValueError(f'{where}：{field} 与执行分镜不符')
            if not any(line.startswith(f"- 时长: {row['duration']}s (") and
                       line.endswith(f" | H3帧数: {row['frames']}帧") for line in lines):
                raise ValueError(f'{where}：时长或帧数与执行分镜不符')
            if seal:
                notes = [s[len(_INPUTS):] for s in lines if s.startswith(_INPUTS)]
                if len(notes) != 1:
                    raise ValueError(f'{where}：执行输入记录缺失或重复')
                inputs = json.loads(notes[0])
                if (type(plan['source_shot']) is not int or plan['source_shot'] != inputs['source_shot'] or
                        any(row[k] != inputs[k] for k in ('references', 'audio_fx_mode'))):
                    raise ValueError(f'{where}：来源镜号、references 或 audio_fx_mode 与执行分镜不符')
                _check_speech(lines, row, inputs, where)
        except (KeyError, TypeError) as exc:
            raise ValueError(f'{where}：执行分镜的批次字段缺失或无效：{exc}') from exc
