"""Local screenplay syntax. Keep source spans/lines; never rewrite the input."""
import re
from collections.abc import Iterator
from typing import Any


def spaces(match):
    return re.sub(r'[^\n]', ' ', match[0])


# Consume the excluded phrase (including coordinated objects), not the line.
# A new instruction can follow even without a full stop. Keep offsets stable.
_NEGATIVE = re.compile(
    r'(?:禁止|严禁|不要|不得|不许|不能|不用|无需|没有|并非|并无|不是|(?:不|未)(?:再)?(?:安排|展示|描写|出现|加入|添加|接|拍|加|做|切|演|含))'
    r'(?:再)?(?:(?!随后|然后|接着|之后|而是|改为|改拍|改成|转为|换成|但|再|并(?=拍|切|转)|[，,。；;！？!?\n]).)*')
_HAND_COMPOUND = re.compile(r'指交(?:叉|错|叠|扣|握|织|缠)')
_NOT_SHOWN = re.compile(r'\s*(?:(?:不|未)(?:入镜|拍摄|出现|发生)|在镜外|仅[作做]对白提及)')


def visible_text(text):
    """Positive image instructions only; retain nouns qualified by negation."""
    return _NEGATIVE.sub(spaces, text)


def pose_text(text, pattern):
    text = _HAND_COMPOUND.sub(spaces, visible_text(text))
    # Bare negators govern the matched term, not unrelated descriptions like
    # “仍未平复的呼吸”. Postposed directions have the same local scope.
    def visible(m):
        before = text[:m.start()].rstrip(' `')
        after = text[m.end():].lstrip(' `')
        return spaces(m) if before.endswith(('不','未','无','非')) or _NOT_SHOWN.match(after) else m[0]
    return pattern.sub(visible, text)

# A section stack describes WHERE a body line belongs. An outline, quote,
# example or heading never schedules an action in its own right.
SHOT = re.compile(r'(?:镜头?|SHOT)[ _-]*\d+', re.I)
HEADING = re.compile(r'^\s*(#{1,6})\s+(.+?)\s*#*\s*$')
SCENE = re.compile(r'^(?:场[次景]\s*[:：]?\s*|SCENE\s+)([\w.-]+)|^第([一二三四五六七八九十百零〇\d]+)场', re.I)
PHASE = re.compile(r'^(?:阶段|第.{1,4}(?:阶段|节)|段落|节拍|phase\b|beat\b)', re.I)
D_TAG = re.compile(r'<d>(?:\[[^\]\n]+\])?(.*?)</d>', re.I)
QUOTED = re.compile(r"<d>.*?(?:</d>|\Z)|“[^”]*”|‘[^’]*’|「[^」]*」|『[^』]*』|\"[^\"\n]*\"|'[^'\n]*'",re.I)


def source_rows(text: str) -> Iterator[dict[str, Any]]:
    stack = []
    fence = ''
    overview = []
    for n, line in enumerate(re.sub(r'<!--.*?(?:-->|\Z)', spaces, text, flags=re.S).splitlines(), 1):
        raw = line.strip()
        mark = re.match(r'^(`{3,}|~{3,})', raw)
        if fence:
            if re.fullmatch(re.escape(fence[0]) + '{' + str(len(fence)) + ',}', raw):
                fence = ''
            continue
        if mark:
            fence = mark[1]; continue
        if raw.startswith('>'):
            if re.match(r'^>\s*(?:简介|概述|概要|梗概|总览|本段|本场|overview)',raw,re.I):
                overview.append(QUOTED.sub(spaces,raw.lstrip('> ')))
            continue
        if not raw or re.fullmatch(r'[-*_ ]{3,}', raw):
            continue
        h = HEADING.match(raw)
        if h and not SHOT.match(h[2]):
            level, title = len(h[1]), h[2].strip('* ')
            sid = SCENE.match(title)
            is_scene = bool(sid or re.match(r'^第.{1,4}幕|^ACT\b', title, re.I) or level <= 2 and not PHASE.match(title))
            anchor=next((i for i in reversed(range(len(stack))) if stack[i][2]), None)
            if not is_scene and anchor is not None and level<=stack[anchor][0]:
                stack=stack[:anchor+1]
            else:
                if is_scene and any(h[0]>=level for h in stack): overview=[]
                stack=[h for h in stack if h[0]<level]
            stack.append((level, title, (sid[1] or sid[2]) if sid else title if is_scene else ''))
            continue
        scene = next((i for i in reversed(range(len(stack))) if stack[i][2]), None)
        context = overview + [h[1] for h in stack[scene if scene is not None else 0:]]
        yield dict(line=n, raw=line, context=context, scene=stack[scene][2] if scene is not None else '',
                   clean=QUOTED.sub(lambda m: '~' + ' ' * (len(m[0])-1), raw))


ESTABLISHED = re.compile(r'(?:已经|早已|已)(?:经)?(?:开始|建立|进入|在进行)|正在进行|进行中')
CUT_IN = re.compile(r'直接(?:切入|切到|切至|进入)|切入|开场即')
SEAT_FAMILY = re.compile(r'观音坐莲|女上坐姿|女上位|坐怀|骑乘')
WALL = re.compile(r'(?:按|靠|贴|撑|扶|抵|顶|倚)(?:住|着|在|向)?墙|墙(?:边|面|旁)')
STANDING = re.compile(r'站(?:立|姿|着)|立姿')
REAR = re.compile(r'后入|从(?:身?后|背后)|后方')
ON_LAP = re.compile(r'(?:跨坐|坐)(?:在|到|上)(?:他|她|男[人方子]?|女[人方子]?|[\w·]{1,10}?)(?:的)?(?:大腿|腿|膝|怀|身上)')
INTIMACY = re.compile(r'亲密(?:动作|姿态|姿势|镜头|接触|场面|状态|缠绵|站|戏)|缠绵|交合|做爱|性爱|床戏|性体位')


def physical_evidence(clause, context):
    """Specialize an observed body action, never iterate an overview's A → B."""
    local = visible_text(context[-1]) if context else ''
    heads = ' '.join(visible_text(h) for h in context)
    if ON_LAP.search(clause) and (SEAT_FAMILY.search(heads + clause) or INTIMACY.search(clause)
                                  or re.search(r'跨坐|(?:大腿|腿|膝|怀)[上中里]?', clause)):
        return 'seat'
    if (REAR.search(clause) or STANDING.search(clause) and WALL.search(clause)) and (
            WALL.search(local + clause) and STANDING.search(local + clause) and REAR.search(heads + clause)
            and (INTIMACY.search(clause) or '后入' in clause or
                 '后入' in heads and re.search(r'(?:控制|维持|保持)(?:.{0,8})(?:体位|姿势|亲密接触)',clause))):
        return 'rear_wall'
    return None


def initiator(text, cast):
    actors = {'她':'S1', '女方':'S1', '他':'S2', '男方':'S2', 'S1':'S1', 'S2':'S2', **cast}
    lead = re.compile(r'(' + '|'.join(map(re.escape, sorted(actors, key=len, reverse=True))) +
                      r')(?:开始|持续|转而|亲自|从(?:身?后方?|背后))?\s*(?:主动|掌握(?:了)?(?:主动权|节奏)|主导|控制.{0,12}姿势)')
    hits = {actors[m[1]] for m in lead.finditer(visible_text(text))}
    return hits.pop() if len(hits) == 1 else None

_NAME = r'(?:[\w·-]{1,24}|Subject [12])'
_LABEL = re.compile(r'(' + _NAME + r')(?:\s*[（(]([^）)]*)[）)])?\s*[:：]\s*$')
_GENERIC = re.compile(r'(?:[男女](?:子A?|主|方|人)?|S[12]|Subject [12]|female|male|她|他)$',re.I)
_SAID = re.compile(r'(?:说道|问道|答道|回答|说|问)$')
_QUOTE_PAIRS = {'“':'”','「':'」','‘':'’','"':'"'}


def _label(prefix):
    # Strip Markdown from the label, never from the utterance.
    prefix = re.sub(r'\*\*|__|`', '', prefix).strip()
    prefix = SHOT.sub('', prefix, count=1) if SHOT.match(prefix) else prefix
    m = _LABEL.search(prefix)
    return (_SAID.sub('', m[1]), m[2] or '') if m else ('','')


def dialogue_on(line: str, names=()) -> list[dict[str, Any]]:
    turns = []
    end = 0
    for tag in D_TAG.finditer(line):
        name, cue = _label(line[end:tag.start()]); end = tag.end()
        turns.append(dict(speaker=name, cue=cue, text=tag[1]))
    if turns: return turns
    # Untagged but clearly delimited dialogue (bold cue or quoted sentence).
    plain = re.sub(r'^\s*(?:[-*]\s+)?(?:' + SHOT.pattern + r'\s*[:：])?\s*', '', line, flags=re.I)
    m = re.match(r'(\*\*|__)?(' + _NAME + r')(?:[（(]([^）)]*)[）)])?(?:\*\*|__)?\s*[:：](?:\*\*|__)?\s*(.+)$',plain)
    if m:
        words = m[4]; name = _SAID.sub('',m[2])
        close = _QUOTE_PAIRS.get(words[0]); quoted = close is not None and close in words[1:]
        if quoted or m[1] or name in names or _GENERIC.fullmatch(name) or _SAID.search(m[2]):
            if quoted and close is not None: words = words[1:words.index(close,1)]
            return [dict(speaker=name, cue=m[3] or '', text=words)]
    return []


def slot(name):
    from whale_core import resolve_speaker
    try: return 'S'+str(resolve_speaker({'她':'S1','他':'S2'}.get(name,name)))
    except ValueError: return None


SPEECH = re.compile(r'(?:^\s*(?:[-*]\s*)?(?:[男女](?:子A?|主|方)?|S[12]|甲|乙|台词|对白|旁白|画外音)(?:[（(][^）)]*[）)])?|(?:说道|问道|回答|说|问))\s*[:：]',re.I)


def action_body(row):
    clean = row['clean']
    shot = SHOT.search(clean)
    body = clean[shot.end():].lstrip(' ：:') if shot else clean
    spoken = SPEECH.search(body)
    if spoken:
        rest = body[spoken.end():].lstrip()
        body = body[:spoken.start()] + (rest[1:] if rest.startswith('~') else '')
    if row['turns'] and not D_TAG.search(row['raw']) and '~' not in clean: body = ''
    return shot, body.strip()


def screenplay(text, aliases=None) -> list[dict[str, Any]]:
    """Bind named turns in scene-local casts. No inference from name or turn order."""
    from collections import defaultdict
    rows = list(source_rows(text)); casts = defaultdict(set); known = dict(aliases or {})
    for name, value in known.items():
        if not isinstance(name,str) or value not in ('S1','S2') or slot(name) not in (None,value):
            raise ValueError('角色映射须为姓名到 S1/S2 的唯一映射')
    labels = set(known) | {d['speaker'] for r in rows for d in dialogue_on(r['raw'])}
    prev = None
    for row in rows:
        row['turns'] = dialogue_on(row['raw'],labels)
        for j,turn in enumerate(row['turns']):
            if not turn['speaker'] and prev and prev['scene']==row['scene']:
                turn['speaker'],turn['cue'] = _label(prev['raw'])
                title=re.fullmatch(r'\s*(?:\*\*|__)(' + _NAME + r')(?:\*\*|__)\s*',prev['raw'])
                if title: turn['speaker']=title[1]
            if not turn['speaker'] or not turn['text'].strip():
                raise ValueError(f"第 {row['line']} 行对白缺说话人或正文；不能猜测")
            is_offscreen = bool(re.match(r'^\s*\[(?:VO|OS)\]', row['raw'], re.I)) or (turn.get('cue') or '').strip().upper() in {'VO', 'OS', '旁白', '画外音', '语音'}
            if not is_offscreen:
                casts[row['scene']].add(slot(turn['speaker']) or turn['speaker'])
            turn.update(line=row['line'], index=j)
        prev = row

    def bind(name, value):
        if known.setdefault(name, value) != value:
            raise ValueError(f'角色映射冲突：{name}')
    for row in rows:
        # Annotated cast and relational pronouns are evidence; quoted speech is not.
        plain = row['clean'] if not row['turns'] else ''
        people = casts[row['scene']]
        for name in people:
            if slot(name): bind(name,slot(name)); continue
            token=re.escape(name)
            for decl in re.finditer(token + r'\s*[（(](女|男|S1|S2)(?:主角?|方)?[）)]', plain):
                bind(name,slot(decl[1]))
            if len(people)==2:
                for target in re.finditer(token + r'(?:看着|望着|看向|转向|面对|背对|扶住|牵住|拉住|贴到|靠向)(他|她)(?!们)', plain):
                    bind(name,'S1' if target[1]=='他' else 'S2')
    # A recurring anchored performer can identify the remaining slot in each
    # two-person exchange, including a scene whose other performer changes.
    for _ in range(len(casts)+1):
        before=len(known)
        for sid,names in casts.items():
            if len(names)>2: raise ValueError(f'{sid}：双人参考槽不能容纳 {len(names)} 个说话人，请分场')
            missing=names-known.keys(); used={known[n] for n in names-missing}
            if len(missing)==1 and len(used)==1:
                bind(next(iter(missing)),next(iter({'S1','S2'}-used)))
        if len(known)==before: break
    for sid,names in casts.items():
        if names-known.keys() or len({known[n] for n in names})!=len(names):
            raise ValueError(f'{sid}：请提供项目 角色映射.json（姓名到 S1/S2），不能按发言顺序猜测：{sorted(names)}')
    for row in rows:
        row['cast']={known[n]:n for n in sorted(casts[row['scene']])}
        for t in row['turns']:
            k_name = slot(t['speaker']) or t['speaker']
            t['actor'] = known.get(k_name, 'S1')
    return [part for r in rows for part in _segments(r)]


def _segments(row: dict[str, Any]) -> Iterator[dict[str, Any]]:
    # A closing quote/tag ends the utterance. A later instruction is not
    # simultaneous with this speaker (and may introduce another speaker).
    raw = row['raw']
    ends=[m.end() for m in D_TAG.finditer(raw)]
    if not ends and row['turns']:
        q=QUOTED.search(raw)
        if q and q[0][1:-1]==row['turns'][0]['text']: ends=[q.end()]
    if not ends:
        yield row; return
    start=0
    for i,end in enumerate(ends+[len(raw)]):
        if i<len(ends): end=len(raw)-len(raw[end:].lstrip('`*_'))
        fragment=raw[start:end].strip(); start=end
        if fragment.strip('，,；;。.!！?？'):
            yield dict(row, fragment=i, raw=fragment, turns=row['turns'][i:i+1],
                       clean=QUOTED.sub(lambda m:'~'+' '*(len(m[0])-1),fragment))

def named_references(shot, refs, nude):
    """A reference slot is scene-local, not a character ID."""
    from hashlib import sha256
    cast=shot.get('cast') or {}
    if not any(slot(name) is None for name in cast.values()): return refs
    bound=list(refs); state='nude' if nude else 'dressed'
    for i,role in enumerate(('S1','S2')):
        name=cast.get(role)
        if refs[i]!=refs[2] and name and not slot(name):
            key=sha256(name.encode('utf8')).hexdigest()[:12]
            bound[i]=f"{'female' if i==0 else 'male'}_{key}_{state}.png"
    scene_key=sha256(shot['source_scene'].encode('utf8')).hexdigest()[:12]
    for i,ref in enumerate(refs[:3]):
        if ref==refs[2]: bound[i]=f'scene_{scene_key}.png'
    return bound

_HANDS = re.compile(r'(?:手指|十指|两手|双手|手部|指节|(?:紧扣|交握|交扣|相扣)的手)')
_CAMERA = re.compile(r'镜头|画面|特写|近景|微距|对焦|聚焦')
_END = re.compile(r'结束|收尾|作结')
_HOLD = re.compile(r'(?:卡|定格|停留|停|保持)在|定格于')


def focal_notes(action, cast) -> list[dict[str, Any]]:
    """Coverage and terminal holds are staging, not additional action choices."""
    text = visible_text(action)
    hold = _HOLD.search(text)
    if _END.search(text) and hold:
        who = ''
        focus = text[hold.end():]
        for actor,name in cast.items():
            pronoun = '她' if actor=='S1' else '他'
            if re.search('(?:'+re.escape(name)+'|'+pronoun+r')(?:的)?(?:脸|面部)',focus): who=actor
        pose = {'S1':'srs_female','S2':'srs_male'}.get(who,'blocking_2s')
        visual = ('Hold on the face' if re.search('脸|面部',focus) else 'Hold the final frame')
        if '失神' in text or '失焦' in text: visual += ' with gaze unfocused'
        if '呼吸' in focus: visual += ' as breathing continues'
        if '脱力' in text: visual += ' and the body relaxes against its support'
        return [dict(staging=pose,staging_note=dict(kind='ending_hold',source=action,
                    visual=visual+'. End on this image.',cam='pull_reveal',size='face' if who else 'mcu'))]
    if any(_HANDS.search(c) and _CAMERA.search(c) for c in re.split('[。！？；;]',text)):
        linked = re.search(r'指交(?:握|扣|叉|错)|(?:紧扣|交握|交扣|相扣)的手',text)
        visual = ('Their fingers remain interlocked.' if linked else 'Keep the visible hand detail in focus.')
        to_face=bool(re.search(r'(?:手|指).{0,45}(?:面部|脸)',text))
        if to_face and re.search('身体节奏|身体律动',text):
            visual += ' Her shoulders carry the established body rhythm into the facial close-up.' if re.search('她|女方',text) else ' The established body rhythm remains visible as the framing rises.'
        push=bool(re.search(r'推进|慢推|推向|推近',text))
        return [dict(staging='cut_insert',staging_note=dict(kind='hands',source=action,visual=visual,
                    to_face=to_face,cam='push_tension' if push else ('tilt_up_desire' if to_face else 'handheld_breath'),size='cu'))]
    if WALL.search(text) and STANDING.search(text):
        return [dict(staging='blocking_2s',staging_note=dict(kind='wall_blocking',source=action,
                    visual='The performer remains standing beside the wall.',cam='arc_subtle',size='mcu'))]
    return []
