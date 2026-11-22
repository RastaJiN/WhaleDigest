"""Storyboard-owned two-person staging. The model only receives its visible projection."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

ACTORS = ('S1', 'S2')
TWO = 'blocking_2s'
REVERSE = {'srs_female': 'S1', 'outro_solo': 'S1', 'srs_male': 'S2'}
EMPTY = {'env_establish', 'empty_cut', 'corridor_cut'}
DIALOGUE = {TWO, *REVERSE}
EXEC_BOARD = '分镜-执行.md'


def neutral_action(pose):
    if pose == TWO:
        return 'Both performers hold their established conversation marks.'
    return 'The visible performer holds the established mark.'


def project_file(root, name):
    root = Path(root).resolve()
    p = Path(name)
    if p.is_absolute() or p.drive or '..' in p.parts or p.suffix.lower() != '.md':
        raise ValueError(f'采用稿必须是项目内的 Markdown 文件：{name}')
    path = (root / p).resolve()
    if not path.is_relative_to(root): raise ValueError('采用稿不能在项目外')
    return path


def input_hashes(root, script_path, board_name, adopted):
    names = {board_name, '分镜.md'}
    if script_path is not None:
        script = Path(script_path).resolve()
        if not script.is_relative_to(root.resolve()): raise ValueError('剧本须位于项目目录内')
        names.add(script.relative_to(root.resolve()).as_posix())
    else:
        names.add('剧本.md')
    return {name: (hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
            for name in sorted(names) for p in [project_file(root, name)]}


def verify_inputs(root, batch):
    board_name = batch.get('execution_board', '分镜.md')
    if board_name not in ('分镜.md', EXEC_BOARD): raise ValueError('未知的执行分镜路径')
    if 'blocking_input_hashes' not in batch:
        if 'execution_board' in batch: raise ValueError('缺少采用分镜的输入记录')
        return
    expected = batch['blocking_input_hashes']
    if not isinstance(expected, dict) or not {'分镜.md', board_name}.issubset(expected):
        raise ValueError('分镜来源不完整')
    for name, digest in expected.items():
        path = project_file(root, name)
        if name in ('分镜.md', board_name) and not path.is_file(): raise ValueError(f'分镜缺失：{name}')
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if actual != digest: raise ValueError(f'采用稿已变更：{name}；请重新编译并验收')

RELATIONS = {
    'conversation': 'Both faces remain readable at conversational distance',
    'within_reach': 'The object can pass between the two people within reach',
    'shared_view': 'Both people have a clear view of the same item',
    'side_by_side': 'Their shoulders are alongside each other, facing the same direction',
    'across_table': 'They face each other across the established table',
    'across_door': 'They address each other from opposite sides of the established doorway',
    'by_wall': 'The established wall is a spatial landmark',
}
_MARK = '<!-- tunjing:generated-board sha256='
_FENCE = re.compile(r'(?ms)^```(tunjing-space|tunjing-blocking)[ \t]*\n(.*?)^```[ \t]*$')
_HEADING = re.compile(r'^#{1,6}\s+(?:场[次景]\s*[:：]?\s*|SCENE\s+)([\w.-]+)|^#{1,6}\s+第([一二三四五六七八九十百零〇\d]+)场', re.I)


def marker(body):
    digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
    return _MARK + digest + ' -->\n' + body


def untouched_board(text):
    first, _, body = text.partition('\n')
    return first.startswith(_MARK) and marker(body) == text


def _object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f'调度记录中的键重复：{key}')
        obj[key] = value
    return obj


def _block(text, kind):
    matches = [m for m in _FENCE.finditer(text) if m[1] == kind]
    if len(matches) != len(re.findall(r'(?m)^```' + re.escape(kind) + r'\b', text)) or len(matches) > 1:
        raise ValueError(f'{kind} 区块重复或未闭合')
    if matches:
        value = json.loads(matches[0][2], object_pairs_hook=_object)
        if not isinstance(value, dict):
            raise ValueError(f'{kind} 须为 JSON 对象')
        return value
    return None


def _keys(data, allowed, where):
    if not isinstance(data, dict) or set(data) - set(allowed):
        raise ValueError(f'{where}：调度字段不合法：{data!r}')


def _english(s, where, *, actors=False):
    if not isinstance(s, str) or not s.strip() or not s.isascii() or not s.isprintable():
        raise ValueError(f'{where}：送模动作/状态请写单行英文；中文说明请写在正文')
    tail = re.sub(r'<Subject [12]>', '', s) if actors else s
    if '<' in tail or '>' in tail or '```' in tail:
        raise ValueError(f'{where}：动作或状态不能带提示词结构标签')
    return s.strip()


def _side(s, where):
    if s not in ACTORS:
        raise ValueError(f'{where}：screen_left 必须是 S1 或 S2')
    return s


def _entity_state(data, where):
    _keys(data, ('world', 'props', 'gaze'), where)
    result = {k: {} for k in ('world', 'props', 'gaze')}
    for field, mapping in data.items():
        if not isinstance(mapping, dict):
            raise ValueError(f'{where}：{field} 应为对象')
        for k, v in mapping.items():
            if field == 'props':
                if not re.fullmatch(r'[A-Za-z][A-Za-z0-9 -]{0,63}', k) or v not in (*ACTORS, 'unheld'):
                    raise ValueError(f'{where}：道具应映射到 S1、S2 或 unheld')
            else:
                _side(k, where)
                _english(v, where)
            result[field][k] = v
    return result


def _overlay(primary, secondary, where):
    out = deepcopy(primary)
    for key, val in secondary.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _overlay(out[key], val, where)
        elif key in out and out[key] != val:
            raise ValueError(f'{where}：剧本与分镜冲突（{key}: {out[key]} / {val}），退回分镜')
        else:
            out[key] = deepcopy(val)
    return out


_SIDE_WORDS = {'男左女右': 'S2', '女左男右': 'S1', 'S1画左、S2画右': 'S1', 'S2画左、S1画右': 'S2'}
_PLACE_WORDS = {'坐着': 'seated', '站着': 'standing', '在门口': 'at the doorway', '在窗边': 'by the window', '在桌旁': 'by the table'}
_ROLE_WORDS = {'S1': 'S1', '女子A': 'S1', 'S2': 'S2', '男子A': 'S2'}
_DIRECTIVE = re.compile(r'^\s*(?:[-*]\s*)?(画面站位|站位待定|站位|场面调度|空间事实|空间)\s*[:：]\s*(.*?)\s*$')
_SHOT_HEADING = re.compile(r'^#{1,6}\s+SHOT[ _-]*(\d+)(?=$|[\s·:：\[])', re.I)


def _direction(match, where):
    field, value = match.groups()
    value = value.rstrip('。；;').strip()
    if field == '站位待定' and value:
        return {'question': value}
    side = _SIDE_WORDS.get(re.sub(r'\s+', '', value))
    if side and field not in ('空间', '空间事实'):
        return {'screen_left': side}
    world = {}
    for item in re.split(r'[，、,；;]', value):
        actor = re.fullmatch(r'(S1|S2|女子A|男子A)\s*(坐着|站着|在门口|在窗边|在桌旁)', item.strip())
        if not actor:
            raise ValueError(f'{where}：不能确定「{field}：{value}」，请在采用稿写明角色和位置，或使用结构化调度区块')
        world = _overlay(world, {_ROLE_WORDS[actor[1]]: _PLACE_WORDS[actor[2]]}, where)
    return {'world': world}


def _stage_lines(text):
    # Only standalone directions belong to the director. Examples, quotes,
    # inline dialogue and Markdown comments are not staging instructions.
    text = re.sub(r'<!--.*?(?:-->|\Z)|<d>.*?(?:</d>|\Z)', '', text, flags=re.S | re.I)
    fence = None
    for raw in text.splitlines():
        line = raw.strip()
        mark = re.match(r'^(`{3,}|~{3,})', line)
        if fence:
            if re.fullmatch(re.escape(fence[0]) + '{' + str(len(fence)) + ',}', line):
                fence = None
        elif mark:
            fence = mark[1]
        elif line and not line.startswith('>'):
            yield line


def _plain_board(text, default_scene, shot_count):
    """Read only scene/shot headings and named directions, not prose as a whole."""
    scenes: list[dict] = []
    seen_numbers: set[int] = set()
    scene: dict | None = None
    number: int | None = None
    for line in _stage_lines(text):
        heading = _HEADING.match(line)
        if heading:
            scene = {'id': heading[1] or heading[2]}
            scenes.append(scene)
            number = None
            continue
        shot = _SHOT_HEADING.match(line)
        field = _DIRECTIVE.match(line)
        if not (shot or field):
            continue
        if scene is None:
            scene = {'id': default_scene}
            scenes.append(scene)
        if shot:
            number = int(shot[1])
            if not 1 <= number <= shot_count or (seen_numbers and number <= max(seen_numbers)):
                raise ValueError(f'{scene["id"]}：镜号 {number} 重复、倒序或不在本次分镜范围内')
            seen_numbers.add(number)
            scene.setdefault('from', number)
            continue
        where = f'{scene["id"]} SHOT-{number}' if number else scene['id']
        delta = _direction(field, where)
        if number is None or number == scene.get('from'):
            scene.update(_overlay(scene, delta, where))
        else:
            changes: dict = scene.setdefault('shots', {})
            if 'world' in delta:
                delta = {'start': delta}
            previous = changes.get(str(number), {})
            if not isinstance(previous, dict):
                raise ValueError(f'{where}：镜头调度必须是对象')
            changes[str(number)] = _overlay(previous, delta, where)
    if not scenes:
        return None
    if len(scenes) == 1:
        scenes[0].setdefault('from', 1)
    if any('from' not in scene for scene in scenes):
        raise ValueError('多场分镜须在每个场次标题下标出该场的首个 SHOT 镜号')
    return {'scenes': scenes}


def _script_facts(text, default_scene, *, prose_scenes=False):
    structured = _block(text, 'tunjing-space') or {}
    # Only scene-local stage directions count. Quoted speech is never a spatial instruction.
    current = default_scene
    found, implicit = {}, {}
    if prose_scenes:
        if __package__:
            from .tunjing_prose import source_rows
        else:
            from tunjing_prose import source_rows
        lines = ((r['scene'] or default_scene,r['clean']) for r in source_rows(text))
    else:
        lines = ((None,line) for line in _stage_lines(text))
    for sid,line in lines:
        if sid: current = sid
        heading = _HEADING.match(line)
        if heading:
            current = heading[1] or heading[2]
            found.setdefault(current, {})
            continue
        if '<d>' in line or re.match(r'^\s*(?:男|女|S[12]|甲|乙)[^：:\n]{0,15}[:：]', line):
            continue
        dirline = _DIRECTIVE.match(line)
        if dirline:
            data = found.setdefault(current, {})
            found[current] = _overlay(data, _direction(dirline, current), current)
        elif re.search(r'递(?:出|给|过|交)|交到.{0,6}手', line):
            implicit.setdefault(current, set()).add('within_reach')
        elif re.search(r'(?:一起|共同|并肩)(?:看|读|查看)', line):
            implicit.setdefault(current, set()).add('shared_view')
    for sid, spec in structured.items():
        _keys(spec, ('world','props','gaze','screen_left','relation','question'), str(sid))
        found[sid] = _overlay(found.get(sid, {}), spec, sid)
    return found, implicit


def _equivalent_layout(scene_key):
    # A reproducible tie-break ONLY between equivalent camera layouts. No sex, voice,
    # reference order or previous scene is consulted. A director can replace it.
    return ACTORS[hashlib.sha256(scene_key.encode('utf-8')).digest()[0] % 2]


def prepare(shots, *, scene_name, project=None, script_path=None, scene_id=None, board_text=None):
    """Plan on ORIGINAL shot indices, before dialogue splitting. Return adopted board flag."""
    root = Path(project) if project is not None else None
    if script_path is None and root is not None and (root/'剧本.md').is_file():
        script_path = root/'剧本.md'
    if root is not None and script_path is not None and not Path(script_path).resolve().is_relative_to(root.resolve()):
        raise ValueError('剧本须位于项目目录内')
    script = Path(script_path).read_text(encoding='utf-8-sig') if script_path else ''
    if board_text is None and root is not None and (root/'分镜.md').is_file():
        board_text = (root/'分镜.md').read_text(encoding='utf-8-sig')
    adopted = board_text is not None and not untouched_board(board_text)
    board = _block(board_text or '', 'tunjing-blocking') if adopted else None
    # Never mutate an adopted board. Both source formats go through the same
    # scene validation, conflict detection and projection.
    if board is not None:
        _keys(board, ('scenes',), '分镜')
    default = scene_id or scene_name or 'scene'
    imported = all(s.get('source_scene') for s in shots) and bool(shots)
    facts, implicit = _script_facts(script, default, prose_scenes=imported)
    if adopted and board is None:
        ids = list(dict.fromkeys([*facts, *implicit]))
        board = _plain_board(board_text, scene_id or (ids[0] if len(ids) == 1 else default), len(shots))
    if board is None and imported:
        # Start a fresh blocking ledger at each source scene boundary, not at
        # each speaking turn or phase. Do not override an adopted board.
        scenes = []
        for n, shot in enumerate(shots,1):
            sid = shot['source_scene']
            if not scenes or scenes[-1]['id'] != sid:
                scenes.append({'id':sid,'from':n})
        board = {'scenes':scenes}
    if board is None:
        ids = list(dict.fromkeys([*facts, *implicit]))
        if len(ids) > 1 and scene_id is None:
            raise ValueError('剧本含多个场次；请在分镜标每场起始镜号，不能整集共用一个站位')
        sid = scene_id or (ids[0] if ids else default)
        if scene_id is not None and facts and scene_id not in facts:
            raise ValueError(f'剧本中没有指定场次：{scene_id}')
        scenes = [{'id':sid, 'from':1}]
    else:
        scenes = board.get('scenes')
        if not isinstance(scenes, list) or not scenes:
            raise ValueError('分镜 scenes 必须是非空数组')
    seen, starts = set(), []
    for spec in scenes:
        _keys(spec, ('id','from','location','world','props','gaze','relation','screen_left','camera_side','shots','question','legacy_axis'), '场次')
        sid, n = spec.get('id'), spec.get('from')
        if not isinstance(sid, str) or not sid.strip() or sid in seen or type(n) is not int or not 1 <= n <= len(shots) or n <= (starts[-1] if starts else 0):
            raise ValueError(f'场次重复或起镜无效：{sid!r}, {n!r}')
        seen.add(sid); starts.append(n)
    if starts[0] != 1:
        raise ValueError('首个场次须从第 1 镜开始')
    if board is not None and set(facts) - seen:
        raise ValueError(f'剧本场次与分镜未对齐：{sorted(set(facts)-seen)}')
    for spec, first, stop in zip(scenes, starts, starts[1:]+[len(shots)+1]):
        sid = spec['id']; sf = facts.get(sid, {})
        scene = _overlay(sf, {k:v for k,v in spec.items() if k not in ('shots','question')}, sid)
        if sf.get('question') or spec.get('question'):
            raise ValueError(f'{sid} 镜 {first} 待主创裁决：{sf.get("question") or spec["question"]}')
        edits = spec.get('shots', {})
        if not isinstance(edits, dict) or any(str(n) not in {str(i) for i in range(first,stop)} for n in edits):
            raise ValueError(f'{sid}：分镜调度引用了不属于本场的镜号')
        location = scene.get('location', scene_name if len(scenes)==1 else 'established location')
        if not isinstance(location,str) or not location.strip(): raise ValueError(f'{sid}：地点不能为空')
        state = _entity_state({k:scene[k] for k in ('world','props','gaze') if k in scene},sid)
        left = scene.get('screen_left'); src = '剧本明示' if sf.get('screen_left') else '分镜明示'
        if 'legacy_axis' in spec and type(spec['legacy_axis']) is not bool:
            raise ValueError(f'{sid}：legacy_axis 只能为 true/false')
        if spec.get('legacy_axis') and left is None:
            if root is None: raise ValueError(f'{sid}：旧站位需指定项目目录')
            data = json.loads((root/'.tunjing_axis.json').read_text(encoding='utf-8-sig'))
            v = data.get('female_screen_side')
            if v not in ('left','right'): raise ValueError(f'{sid}：指定沿用的旧站位无效')
            left = 'S1' if v=='left' else 'S2'; src='分镜指定沿用'
        if left is None:
            # A legacy axis ledger is only a compatibility input when there is no
            # authored script/board decision; it never overrides a new scene.
            legacy = root / '.tunjing_axis.json' if root is not None else None
            if legacy is not None and legacy.is_file() and not adopted and not scene_id and not facts and not implicit:
                data = json.loads(legacy.read_text(encoding='utf-8-sig'))
                value = data.get('female_screen_side')
                if value in ('left', 'right'):
                    left = 'S1' if value == 'left' else 'S2'; src = '旧版轴线兼容'
        if left is None: left=_equivalent_layout(sid); src='分镜补定'
        _side(left,sid)
        suggestions = implicit.get(sid,set())
        relation = scene.get('relation', next(iter(suggestions)) if len(suggestions)==1 else 'conversation')
        if len(suggestions)>1 and 'relation' not in scene and not edits:
            raise ValueError(f'{sid}：有不同时刻的动作要求，请在分镜按镜注明关系')
        camera = scene.get('camera_side', 'the established camera side'); _english(camera,sid)
        for number in range(first,stop):
            shot = shots[number-1]; edit = edits.get(str(number), {}); where=f'{sid} SHOT-{number:02d}'
            if imported and adopted and shot.get('cast') and shot['source_scene'] != sid:
                raise ValueError(f'{where}：命名对白的剧本与采用分镜场次不符')
            _keys(edit, ('start','end','action','screen_left','camera_side','reframe','relation','question','pose'), where)
            if edit.get('question'): raise ValueError(f'{where} 待主创裁决：{edit["question"]}')
            if edit.get('pose', shot['pose']) != shot['pose']:
                raise ValueError(f'{where}：调度镜号与分镜原语不符，请重新对齐')
            if number==first: initial_source=src
            else: initial_source='同场继承'
            old_left = left; old_camera=camera
            action = _english(edit['action'],where,actors=True) if 'action' in edit else ''
            move = _english(edit['reframe'],where) if 'reframe' in edit else ''
            if 'screen_left' in edit: left=_side(edit['screen_left'],where)
            if 'camera_side' in edit: camera=_english(edit['camera_side'],where)
            # A first-shot assertion must also agree with any independent explicit upstream assertion.
            if number==first and 'screen_left' in edit and 'screen_left' in scene and old_left != left and not (action or move):
                raise ValueError(f'{where}：起始画面与场次设定冲突')
            if old_camera!=camera and not move or (number>first and old_left!=left and not (move or action)):
                raise ValueError(f'{where}：换边必须记下镜内走位或摄影机越轴的交代')
            if 'start' in edit:
                state=_overlay(state,_entity_state(edit['start'],where),where)
            start=deepcopy(state)
            if 'end' in edit:
                end=_entity_state(edit['end'],where)
                if any(state[k].get(a)!=v for k in end for a,v in end[k].items()) and not action:
                    raise ValueError(f'{where}：末态变化缺少能解释它的分镜动作或走位')
                for key in end: state[key].update(end[key])
            relation=edit.get('relation',relation)
            if relation not in RELATIONS: raise ValueError(f'{where}：未知关系 {relation!r}')
            shot['blocking_state'] = {'scene_id':sid, 'source_shot':number,'source':('分镜明示' if 'screen_left' in edit or move else initial_source), 'screen_left':left, 'prior_left':old_left, 'camera_side':camera, 'reframe':move, 'relation':relation, 'location':location, 'action':action, 'start':start,'end':deepcopy(state),'adopted':adopted}
    return adopted


def visible_notes(plan, visible):
    """Only project the world facts of performers visible in this frame."""
    text = []
    for field in ('world','gaze','props'):
        for k,v in plan['start'][field].items():
            if field=='props':
                if v in visible: text.append(f'<Subject {v[1]}> holds the {k}.')
            elif k in visible:
                text.append(f'<Subject {k[1]}> is {v}.' if field=='world' else f'<Subject {k[1]}> looks {v}.')
    return ' '.join(text)


def board_note(plan):
    st=lambda x: json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return (f"- 调度：场 {plan['scene_id']}｜{plan['source']}｜画左 {plan['screen_left']}｜{plan['camera_side']}｜{plan['relation']}\n"
            f"- 空间承接：{st(plan['start'])} → {plan['action'] or plan['reframe'] or '原位'} → {st(plan['end'])}")
