"""Source-shot decisions, made before the scene assembler is invoked."""
import hashlib
import json
import re
from pathlib import Path

if __package__:
    from . import whale_prose as prose
else:
    import whale_prose as prose


def source_hash(text, scene=''):
    return hashlib.sha256((text + '\0' + scene).encode('utf-8')).hexdigest()

SEAT = {'cowgirl_upright':'男方仰卧；女方面向他，上身直立', 'lap_sit': '男方坐稳，腿部承托；面对面', 'lap_sit_back': '男方坐稳，腿部承托；女方背向男方', 'cowgirl': '男方仰卧，由床面承托；面对面', 'reverse_cowgirl': '本矩阵：男方坐在边缘承托；女方背靠他、同向'}
STAND = {'stand_face_hug': '双脚着地，相互扶持；面对面', 'stand_doggy_wall': '双脚着地，手撑墙面；同向', 'stand_bend_doggy': '双脚着地，女方俯身；同向'}
GENERATED = '\n## 吞鲸体位推进\n\n以下为本集按场景自动识别'


SOLO = set('finger_masturbate solo_masturbate lying_dildo dildo_masturbate pillow_hump toy_tease'.split())
FORE = set('bj squat_bj prone_bj tip_lick deepthroat head_thrust facefuck sixty_nine ball_lick penis_slap cunnilingus sofa_cunni handjob titjob undress breast_rub nipple_lick kiss_fondle kiss_pin kiss_force kiss_her ass_rub footjob facesit fingering thigh_grind mirror_ear_whisper clit_tease mirror_whisper'.split())
# These legacy selector hints describe furniture, camera or ordinary blocking.
CONTEXT_ONLY = {'手指','床边','正面','地板','背对他','撑墙','撑桌','69','第一人称','POV','喷水'}


def candidate_index(poses):
    from whale_pose_select import POSE_KEYWORD_MAP
    from whale_solo import PROP_ACTIONS
    index = {}
    for pid, p in sorted(poses.items()):
        category = p['category']
        role = ('solo_action' if pid in SOLO else 'staging' if category == 'staging' else
                'foreplay' if pid in FORE or category == 'tease' or category.startswith('前戏') else 'main_pose')
        aliases = {pid, p['nameZh'], p['nameEn']}
        aliases.update(k for k,v in {**POSE_KEYWORD_MAP, **PROP_ACTIONS}.items() if v == pid and k not in CONTEXT_ONLY)
        index[pid] = dict(id=pid, nameZh=p['nameZh'], category=category, role=role, aliases=sorted(aliases-{''}))
        if pid in SEAT or pid in STAND:
            index[pid]['blocking'] = (SEAT if pid in SEAT else STAND)[pid]
    return index


GROUPS = {'女上坐姿': ('main_pose', SEAT), '观音坐莲': ('main_pose', SEAT), '亲密站姿': ('main_pose', STAND),
          '站立体位': ('main_pose', STAND), '站姿': ('main_pose', STAND),
          '前戏': ('foreplay', None), '挑逗': ('foreplay', None), '单人动作': ('solo_action', None),
          '主姿势': ('main_pose', None), '主体位': ('main_pose', None)}


CARD = '分镜体位选择.json'
PLAN = '.whale_pose_plan.json'
BOARD = '已决分镜.json'
ROLES = ('foreplay', 'main_pose', 'solo_action')
ABSENT = ('none', 'not_in_shot', 'already_established')
ENTRY = ('linear', 'direct_entry', 'nonlinear')
_APPENDIX = re.compile(re.escape(GENERATED) + r'[^\n]*\n(?:[ \t]*\n)?(?:- `[a-z0-9_]+` [^\n]*(?:\n|$))*')


def authored_text(text):
    """Remove the machine-owned list, never the authored shots following it."""
    text = text.lstrip('\ufeff')
    match = _APPENDIX.search(text)
    if not match:
        return text
    before, after = text[:match.start()], text[match.end():]
    separator = '\n' if before and after and not before.endswith('\n') and not after.startswith('\n') else ''
    return before + separator + after


ROLE_NAMES = {**{k:k for k in ROLES}, '主体位':'main_pose', '主姿势':'main_pose', '前戏':'foreplay', '单人动作':'solo_action'}
ASSIGN = re.compile(r'('+'|'.join(ROLE_NAMES)+r')\s*=\s*`?([a-zA-Z_][a-zA-Z0-9_]*)`?')
INTIMATE = re.compile(r'亲密(?:动作|姿态|姿势|镜头|接触|缠绵|站|戏)|缠绵|交合|做爱|性爱|床戏|性体位|体位(?:未定|待定|不明)|intimate\s+(?:pose|contact|action)',re.I)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def prompt_hash(prompt):
    if not isinstance(prompt, str):
        raise ValueError('Expected a compiled prompt string')
    return hashlib.sha256(prompt.encode('utf8')).hexdigest()


def write_json(path,value):
    data=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf8')
    if not path.exists() or path.read_bytes()!=data:
        temp=path.with_suffix(path.suffix+'.tmp'); temp.write_bytes(data); temp.replace(path)


def _lexicon(index):
    names={}
    for pid,row in index.items():
        for alias in row['aliases']: names.setdefault(alias,[]).append(pid)
    def token(s):
        return (r'(?<![A-Za-z0-9_])' if s[0].isascii() and s[0].isalnum() else '') + re.escape(s) + (r'(?![A-Za-z0-9_])' if s[-1].isascii() and s[-1].isalnum() else '')
    terms=sorted(names.keys() | GROUPS.keys(),key=lambda s:(-len(s),s))
    pools={role:[p for p in index if index[p]['role']==role] for role in ROLES}
    return names,re.compile('|'.join(map(token,terms))),pools


# A spoken cue or a production label is not itself a physical action. Match
# only that cue/label, never the rest of the shot: later actions still count.
_VERBAL_TEASE = re.compile(r'(?:言语|口头|言辞|对白|语气)(?:上的|上|的)?\s*挑逗')
_ORDINARY_SOLO_HEADING = re.compile(
    r'单人动作(?=\s*[:：]\s*(?:(?:他|她|男子A?|女子A?|S[12])\s*)?'
    r'(?:(?:站着|坐着|低头|抬手|独自|正在|正|慢慢)\s*)*'
    r'(?:看(?:手?表|书|手机|窗外)|整理(?:衣领|文件|桌面)|喝水|开门|关门|看向(?:门口|窗外))'
    r'(?:$|[\s，,。；;！!？?]|随后|然后|接着|再|并))', re.I)


def _parse(action,poses,index,lexicon,context=()):
    names,pattern,pools=lexicon
    events,errors,modes,presence=[],[],[],[]
    def mask(m): return ' '*len(m[0])
    source_action = prose.visible_text(action)
    established = prose.ESTABLISHED.search(source_action) and prose.INTIMACY.search(source_action)
    action = _VERBAL_TEASE.sub(mask, action)
    action = _ORDINARY_SOLO_HEADING.sub(mask, action)
    # These constructions name something NOT visible or an ordinary movement.
    action = re.sub(r'(?:非|并非|没有|并无|无|不是|不含|不拍)\s*亲密(?:站姿|站立|动作|姿势|接触|戏)?|(?:先后|随后|然后)入(?:场|座|内|室|门)', mask, action)
    def assign(m):
        role,pid=ROLE_NAMES[m[1]],m[2]
        if role=='foreplay' and pid in ABSENT: presence.append(pid)
        else: events.append((m.start(),role,pools[role],pid))
        return mask(m)
    # Read absence/entry declarations before masking negated visible acts.
    # Assignments are collected below, after exclusion scope is known.
    order_re=r'(?:order|顺序)\s*=\s*([a-z_0-9]+(?:\s*>\s*[a-z_0-9]+)*)'
    orders=re.findall(order_re,action); action=re.sub(order_re,mask,action)
    for expr,val in ((r'(?:entry_mode\s*=\s*)?direct[_ -]entry|直接切入|直入','direct_entry'),
                     (r'(?:entry_mode\s*=\s*)?nonlinear|非线性(?:切入)?','nonlinear'),(r'entry_mode\s*=\s*linear','linear')):
        if re.search(expr,action): modes.append(val); action=re.sub(expr,mask,action)
    for expr,val in ((r'(?:没有|无|跳过)前戏','none'),(r'前戏(?:不在本镜|不入镜|镜外)','not_in_shot'),
                     (r'前戏(?:已经|已)(?:建立|完成)','already_established')):
        if re.search(expr,action): presence.append(val); action=re.sub(expr,mask,action)
    action=ASSIGN.sub(assign,prose.pose_text(action,pattern))
    if established:
        if not modes and prose.CUT_IN.search(source_action): modes.append('direct_entry')
        if not presence: presence.append('already_established')
    if len(set(modes))>1 or len(set(presence))>1 or len(orders)>1: errors.append('conflicting entry, foreplay or order directives')
    for clause in re.finditer(r'(?:(?!然后|随后|接着|换成|转为|再|→|➔|[；;。]).)+',action):
        text=clause[0]; hits=list(pattern.finditer(text))
        specific={index[p]['role'] for h in hits for p in names.get(h[0],[]) if h[0] not in GROUPS}
        for hit in hits:
            word=hit[0]; pos=clause.start()+hit.start()
            if word in GROUPS:
                role,pool=GROUPS[word]
                if word=='站姿' and not re.search('亲密|体位|交合|缠绵',text): continue
                if role not in specific: events.append((pos,role,list(pool or pools[role]),''))
            else:
                options=names[word]; role=index[options[0]]['role']
                fixed=[p for p in options if word in (p,poses[p]['nameZh'],poses[p]['nameEn'])]
                events.append((pos,role,options,fixed[0] if len(fixed)==1 else ''))
        physical = prose.physical_evidence(text, context)
        if physical == 'rear_wall':
            # A shorthand by itself is a hint. Independent support, stance and
            # rear-direction evidence resolves it without asking the same thing.
            events=[(pos,role,opts,'stand_doggy_wall') if clause.start()<=pos<clause.end() and
                    opts==['stand_doggy_wall'] and not fixed else (pos,role,opts,fixed)
                    for pos,role,opts,fixed in events]
        if physical and not any(role == 'main_pose' and clause.start() <= pos < clause.end() for pos,role,_,_ in events):
            pool, fixed = (list(SEAT), '') if physical == 'seat' else (['stand_doggy_wall'], 'stand_doggy_wall')
            events.append((clause.start(), 'main_pose', pool, fixed))
        if not hits and not any(clause.start()<=ev[0]<clause.end() for ev in events):
            lap=re.search(r'(?:她|女[人方子]?)[^。；]{0,10}?(?:跨坐|坐)(?:在|到|上)?(?:他|男[人方子]?)(?:的)?(?:大腿|腿|膝|怀)',text)
            if lap or INTIMATE.search(text) or re.search(r'(?:站姿|站立|立姿|站着).{0,8}(?:亲密|体位)|亲密.{0,5}(?:站着|立姿)',text):
                pool=SEAT if lap else STAND if re.search('站立|站着|站姿|立姿',text) else pools['main_pose']
                events.append((clause.start(),'main_pose',list(pool),''))
    return [e[1:] for e in sorted(events,key=lambda e:e[0])],(modes or [None])[0],(presence or [None])[0],(orders or [None])[0],errors


# Pose-specific physical invariants; NA leaves unspecified facts to the recipe.
SEATED = {p: ('same_direction' if p in ('lap_sit_back','reverse_cowgirl') else 'face_to_face',
              'seated_lap' if p in ('lap_sit','lap_sit_back','reverse_cowgirl') else 'supine', 'S2') for p in SEAT}
FIELDS = {'initiator': ('S1','S2','both'), 'pace': ('slow','steady','fast'),
          'facing': ('same_direction','face_to_face','away'), 'support': ('seated_lap','supine','floor','wall','table'),
          'load': ('S1','S2','shared')}


def _card(label,line,digest,events,entry,presence,order_text,errors,prior,index,poses,project,leader=None):
    from whale_local_recipe import resolve
    from whale_scene import plan_shot
    from whale_solo import PROP_IDS
    steps=[]; previous=prior.get('steps',[])
    for i,(role,options,fixed) in enumerate(events):
        old=previous[i] if i<len(previous) and isinstance(previous[i],dict) else {}
        pick=old.get('选择','')
        if len(events)==1 and prior.get('选择',pick)!=pick:
            old_value=(prior.get('selected_order') or [''])[0]
            top=prior.get('选择','')
            if pick in ('',old_value): pick=top
            elif top not in ('',old_value): errors.append('conflicting step and card selections')
        if fixed and pick and pick!=fixed: errors.append(f'{role}: selection contradicts source {fixed}')
        pick=fixed or pick
        if not isinstance(pick,str): errors.append(f'{role}: expected a pose ID'); pick=''
        step=dict(role=role, 候选={p:index[p] for p in options}, 选择=pick)
        # An authored main_pose=none is metadata (e.g. a solo-only shot), not
        # a local recipe. It cannot be used to skip a required main-pose choice.
        allowed_absence = ((role == 'foreplay' and pick in ABSENT) or
                           (role == 'solo_action' and pick == 'none') or
                           (role == 'main_pose' and pick == fixed == 'none'))
        if pick and pick not in options and not allowed_absence:
            try:
                if pick in index or pick in ABSENT or role=='solo_action': raise ValueError('incompatible role or candidate')
                recipe=resolve([pick],index,project)[pick]
                rh=source_hash(json.dumps(recipe,ensure_ascii=False))
                if old.get('recipe_hash',rh)!=rh:
                    step['选择']=''; errors.append(f'{pick}: recipe changed; choose again')
                else: step.update(recipe_hash=rh, visual=recipe[0], framing=dict(size=recipe[1],cam=recipe[2]))
            except (ValueError,OSError) as exc:
                errors.append(f'{role}: {pick}: {exc}'); step['选择']=''
        steps.append(step)
    # A source-level absence describes this shot. Skipping an optional step
    # on the review card, in contrast, need not exclude another selected step.
    absent_roles = {role for role, _, fixed in events if fixed == 'none' and role in ('main_pose', 'solo_action')}
    for role in sorted(absent_roles):
        if any(s['role'] == role and s['选择'] and s['选择'] not in ABSENT for s in steps):
            errors.append(f'{role}=none contradicts a visible {role} in this shot')
    order=prior.get('transitions_order',list(range(len(steps))))
    if order_text:
        remaining=list(range(len(steps))); prescribed=[]
        for token in map(str.strip,order_text.split('>')):
            matching=[i for i in remaining if token in (steps[i]['role'],steps[i]['选择'],str(i))]
            if not matching: break
            i=matching[0]; remaining.remove(i); prescribed.append(i)
        if remaining or len(prescribed)!=len(order_text.split('>')): errors.append('order must cover each declared step once')
        if prior and order!=prescribed: errors.append('transitions_order contradicts source order')
        order=prescribed
    valid_order=isinstance(order,list) and all(type(i) is int for i in order) and sorted(order)==list(range(len(steps)))
    if not valid_order: errors.append('transitions_order must be a permutation of the step indices')
    ordered=order if valid_order else []
    entry_value=prior.get('entry_mode',entry or 'linear')
    if entry_value not in ENTRY or entry and entry!=entry_value: errors.append('invalid or contradictory entry_mode')
    fore=[s for s in steps if s['role']=='foreplay']
    visible_fore=[s for s in fore if s['选择'] and s['选择'] not in ABSENT]
    absent=[s['选择'] for s in fore if s['选择'] in ABSENT]
    mode=prior.get('foreplay_mode',presence or 'undecided')
    if isinstance(prior.get('foreplay'),str): mode=prior['foreplay']
    if mode=='undecided': mode=presence or ('in_shot' if visible_fore else (absent or ['undecided' if fore else 'none'])[0])
    if ((presence and presence!=mode) or mode not in (*ABSENT,'in_shot','undecided') or
            (mode in ABSENT and visible_fore) or any(v!=mode for v in absent) or (mode=='in_shot' and not fore)):
        errors.append('foreplay presence contradicts the selected foreplay steps')
    for s in fore:
        if not s['选择'] and mode in ABSENT: s['选择']=mode
    active=[i for i in ordered if steps[i]['选择'] and steps[i]['选择'] not in ABSENT]
    selected=[steps[i]['选择'] for i in active]
    if entry_value=='direct_entry' and active and steps[active[0]]['role']=='foreplay': errors.append('direct_entry cannot start with a visible foreplay step')
    end,exit_actor=prior.get('scene_end','none'),prior.get('exit','NA')
    if end not in ('none','hold','exit') or exit_actor not in ('NA','none','S1','S2','both') or (end=='exit')!=(exit_actor in ('S1','S2','both')):
        errors.append('scene_end=exit requires an exiting subject, and vice versa')
    if not active and end!='none': errors.append('ending requires a visible step')
    changed_order=prior.get('selected_order',selected)!=selected
    for i,step in enumerate(steps):
        old=previous[i] if i<len(previous) and isinstance(previous[i],dict) else {}
        pid=step['选择']; locks: dict[str,str]=dict(zip(('facing','support','load'),SEATED.get(pid,())))
        if leader and step['role']=='main_pose' and len(steps)==1: locks['initiator']=leader
        if pid in STAND: locks.update(facing='face_to_face' if pid=='stand_face_hug' else 'same_direction',support='wall' if pid=='stand_doggy_wall' else 'floor')
        for field,choices in FIELDS.items():
            val=old.get(field,'NA')
            if val in ('NA','none') and field in locks: val=locks[field]
            if val not in (*choices,'NA','none') or field in locks and locks[field]!=val: errors.append(f'{field} contradicts {pid}: {val!r}')
            if pid in ABSENT and val not in ('NA','none'): errors.append(f'{field} on absent action')
            if pid in SOLO and field in ('initiator','load') and val not in ('NA','none','S1'): errors.append(f'{field} not visible in solo action {pid}')
            step[field]=val
        pos=active.index(i) if i in active else -1
        for field,value in [('pre',selected[pos-1] if pos>0 else 'NA'),('post',pid if pos>0 else 'NA')]:
            saved=old.get(field,'NA')
            if not changed_order and saved not in ('NA',value): errors.append(f'{field} contradicts ordered endpoints')
            step[field]=value if changed_order or saved=='NA' else saved
        transition=old.get('transition','NA')
        if transition in ('none','NA') and pos>0: transition='cut'
        if pos<=0 and changed_order and transition=='cut' and old.get('pre','NA')!='NA': transition='NA'
        if transition not in (('one_take','cut') if pos>0 else ('NA','none')): errors.append('transition needs two active endpoints')
        step['transition']=transition
        if pid in poses:
            p=poses[pid]
            # Do not replay the matrix's introductory beat or its default leader/tempo over a decision.
            directed=any(step[k] not in ('NA','none') for k in FIELDS) or mode=='already_established' or entry_value!='linear'
            visual=(p['nameEn'] if directed else (p.get('beatsEn') or [p['nameEn']])[0]).rstrip('.')
            # Concrete, established geometry, not a reprise of the recipe's entry beat.
            if pid=='stand_doggy_wall' and directed:
                visual = 'Both remain standing, S1 braced against the wall with S2 behind her'
            if pid in SEATED:
                if step['support']=='seated_lap':
                    visual = ('S2 sits upright with feet planted; S1 straddles his lap face-to-face' if step['facing']=='face_to_face'
                              else 'S2 sits upright and supports S1 on his lap; both face the same direction')
                else:
                    visual = 'S2 lies on his back; S1 straddles him facing him' + (', torso upright' if pid=='cowgirl_upright' else '')
            size,cam=('mcu','static_side') if pid in PROP_IDS else plan_shot(pid,poses)[0]
            step['framing']=dict(size=size,cam=cam)
            step['visual']=visual
    if active and steps[active[-1]]['选择'] in SOLO and exit_actor in ('both','S2'): errors.append('exit actor is not visible')
    roles={k:[steps[i]['选择'] for i in active if steps[i]['role']==k] or [mode if k=='foreplay' else 'none'] for k in ROLES}
    return {'镜头':label,'原文':line,'键':source_hash(label,digest),'source_hash':digest,
            'scene_mode':'solo' if all(s['role']=='solo_action' or s['选择'] in ABSENT for s in steps) else 'intimate',
            'entry_mode':entry_value,'foreplay_mode':mode,**roles,'steps':steps,'transitions_order':order,'selected_order':selected,
            '选择':steps[0]['选择'] if len(steps)==1 else selected,'scene_end':end,'exit':exit_actor,
            'resolved':all(s['选择'] for s in steps) and not errors,'errors':errors}


def projection(card):
    """The executable card: no candidates or unreviewed prose enter prompt assembly."""
    if not card['resolved'] or card['errors']: raise ValueError('Pending action card')
    keys=('镜头','键','source_hash','scene_mode','entry_mode','foreplay_mode',*ROLES,'transitions_order','selected_order','scene_end','exit')
    return {k:card[k] for k in (*keys,'context','source_scene','change_from') if k in card} | {'steps':[{k:v for k,v in s.items() if k!='候选'} for s in card['steps']]}


def flatten(cards):
    rows=[]
    for c in cards:
        selected=[i for i in c['transitions_order'] if c['steps'][i]['选择'] not in ABSENT]
        for pos,i in enumerate(selected):
            row=dict(c['steps'][i], source_shot=c['镜头'],source_hash=c['source_hash'],step_index=i,order_index=pos,
                     entry_mode=c['entry_mode'],foreplay_mode=c['foreplay_mode'],scene_mode=c['scene_mode'],
                     scene_end=c['scene_end'] if pos==len(selected)-1 else 'none',exit=c['exit'] if pos==len(selected)-1 else 'NA')
            if pos==0 and c.get('change_from'): row['change_from']=c['change_from']
            rows.append(row)
    return rows


def choose(text,source,poses,scene,scene_id=None):
    source=Path(source); root=source.parent; state=root/CARD
    index=candidate_index(poses); lexicon=_lexicon(index)
    old=json.loads(state.read_text('utf-8-sig')) if state.exists() else []
    previous={c['键']:c for c in old}
    cards=[]; sequence=[]; explicit=[]
    authored=authored_text(text)
    alias_path = root/'角色映射.json'
    aliases = json.loads(alias_path.read_text('utf-8-sig')) if alias_path.exists() else {}
    if not isinstance(aliases,dict): raise ValueError('角色映射须为 JSON 对象')
    active_scene, last_pose = None, None
    for row in prose.screenplay(authored, aliases):
        n,line = row['line'],row['raw']
        shot, action = prose.action_body(row)
        label=shot[0] if shot else f'第{n}行'
        if row.get('fragment'): label+=f"·片段{row['fragment']+1}"
        turns = row['turns']
        base = dict(line=n, source_scene=row['scene'] or scene_id or scene, cast=row['cast'])
        if 'fragment' in row: base['fragment']=row['fragment']
        if base['source_scene'] != active_scene:
            active_scene, last_pose = base['source_scene'], None
        items = []
        stage = []
        notes = prose.focal_notes(action, row['cast'])
        if re.search(r'(?:^|[：:，, ])(?:纯)?空镜|空间建立空镜|\benv_establish\b',action):
            items.append({'staging':'env_establish'})
            if 'env_establish' in action or '空间建立空镜' in action: explicit.append('env_establish')
        else:
            events,entry,presence,order_text,errors = _parse(action,poses,index,lexicon,row['context'])
            intimacy=[e for e in events if e[0]!='staging']; stage=[e[2] for e in events if e[0]=='staging' and e[2]]
            if intimacy:
                scope = '\0'.join([scene, scene_id or '', *row['context'], json.dumps(row['cast'],sort_keys=True)])
                digest=source_hash(line,scope); key=source_hash(label,digest)
                prior=previous.get(key,{})
                if prior.get('source_hash')!=digest or prior.get('原文')!=line: prior={}
                if stage: errors.append('separate staging and intimate action into distinct source shots')
                leader = prose.initiator(action,{name:slot for slot,name in row['cast'].items()})
                card=_card(label,line,digest,intimacy,entry,presence,order_text,errors,prior,index,poses,root,leader)
                card.update(context=row['context'],source_scene=base['source_scene'])
                if any(not s['选择'] and set(s['候选'])==set(SEAT) for s in card['steps']):
                    card['question']='请确认承托者坐稳还是仰卧，以及上方人物的朝向（面对面或同向）；若均不符可用本场配方。'
                if last_pose and any(e[0]=='main_pose' for e in intimacy) and re.search('转为|转到|改为|改变位置|换成|换位',action):
                    card['change_from'] = last_pose
                if card['main_pose'] != ['none']: last_pose = card['main_pose'][-1]
                items.append({'card':len(cards)}); cards.append(card); explicit.extend(card['selected_order'])
            else:
                explicit.extend(stage)
                if not stage and shot and not notes and (not turns or re.search(r'[。；;，,]',action)):
                    stage=['blocking_2s']
                items.extend({'staging':pid} for pid in stage)
        # An established physical decision already contains its wall support.
        if any('card' in item for item in items): notes=[x for x in notes if x['staging_note']['kind']!='wall_blocking']
        items.extend(notes)
        for turn in turns:
            available = next((item for item in items if 'dialogue' not in item and item.get('staging') != 'env_establish'),None)
            if available is None:
                # 肉戏/亲密体位进行中，独立台词行不强制切回正反打 (srs_male/srs_female)，直接沿用当前已建立的 last_pose
                if last_pose and last_pose != 'none' and not stage:
                    available={'staging': last_pose}
                else:
                    available={'staging':'srs_female' if turn['actor']=='S1' else 'srs_male'}
                items.append(available)
            available['dialogue']=turn
        sequence.extend({**base,**item} for item in items)
    if cards or state.exists(): write_json(state,cards)
    if not all(c['resolved'] for c in cards):
        for card in cards:
            if not card['resolved'] and card.get('question'):
                print(' / '.join([*card.get('context',[]),card['镜头']])+ '：' + card['question'])
        print('分镜待确认，请填写选择后重跑：',state); raise SystemExit(3)
    if not sequence or not any('staging' in x or cards[x['card']]['selected_order'] for x in sequence):
        sequence.append({'staging':'blocking_2s','line':0})
    plan={'source':source.name,'source_hash':source_hash(authored),'scene':scene,'scene_id':scene_id,
          'card_sha256':file_hash(state),'sequence':sequence}
    plan['cast_sha256'] = file_hash(alias_path)
    if any('recipe_hash' in s for c in cards for s in c['steps']):
        plan['recipe_sha256'] = file_hash(root/'pose_recipes.json')
    write_json(root/PLAN,plan)
    return explicit


def reviewed_plan(project,source,scene,scene_id=None):
    """Check the receipt and hashes. Do not repeat pose selection at export."""
    root=Path(project); path=root/PLAN
    if not path.is_file(): raise ValueError('Missing pose review; rerun whale_pipeline.py')
    plan=json.loads(path.read_text('utf8')); source=Path(source) if source else root/'剧本.md'
    authored=authored_text(source.read_text('utf-8-sig'))
    if plan.get('cast_sha256') != file_hash(root/'角色映射.json'):
        raise ValueError('角色映射已变更，请重新确认分镜')
    if 'recipe_sha256' in plan and file_hash(root/'pose_recipes.json') != plan['recipe_sha256']:
        raise ValueError('Local pose recipe changed; rerun storyboard review')
    if (source.resolve().parent!=root.resolve() or source.name!=plan['source'] or scene!=plan['scene'] or scene_id!=plan['scene_id'] or
            source_hash(authored)!=plan['source_hash'] or file_hash(root/CARD)!=plan['card_sha256']):
        raise ValueError('Pose review is stale; source, scene or choices changed. Rerun whale_pipeline.py')
    cards=[projection(c) for c in json.loads((root/CARD).read_text('utf8'))] if (root/CARD).exists() else []
    chain=[]; decisions={}
    references = [item['card'] for item in plan['sequence'] if 'card' in item]
    if references != list(range(len(cards))):
        raise ValueError('Missing, reordered or duplicate reviewed card; rerun storyboard review')
    from whale_core import DRAMATIC_BODY_IDS
    staging = DRAMATIC_BODY_IDS | {'env_establish','srs_male','srs_female','blocking_2s','prop_insert','cut_insert','spatial_shift','outro_solo'}
    if 'cast_sha256' in plan:
        aliases=json.loads((root/'角色映射.json').read_text('utf-8-sig')) if plan['cast_sha256'] else {}
        body={(r['line'],r.get('fragment',0)):r for r in prose.screenplay(authored,aliases)}
        expected=[d for r in body.values() for d in r['turns']]
        if expected != [x['dialogue'] for x in plan['sequence'] if 'dialogue' in x]:
            raise ValueError('Dialogue in receipt differs from source')
        for item in plan['sequence']:
            if item == {'line':0,'staging':'blocking_2s'}: continue
            row=body.get((item['line'],item.get('fragment',0)))
            if not row or item.get('source_scene')!=(row['scene'] or scene_id or scene) or item.get('cast')!=row['cast']:
                raise ValueError('Incorrect source scene/cast in receipt')
            if 'dialogue' in item and item['dialogue'] not in row['turns']:
                raise ValueError('Dialogue on wrong source line')
            if 'staging_note' in item:
                note = {k:item[k] for k in ('staging','staging_note')}
                if note not in prose.focal_notes(prose.action_body(row)[1],row['cast']):
                    raise ValueError('Unreviewed staging note')
    for item in plan['sequence']:
        meta={k:item[k] for k in ('source_scene','cast','dialogue','staging_note') if k in item}
        if 'card' in item:
            for j,step in enumerate(flatten([cards[item['card']]])):
                if j: meta.pop('dialogue',None)
                decisions[len(chain)]=dict(step,source_line=item['line'],**meta); chain.append(step['选择'])
        else:
            if item.get('staging') not in staging and item.get('staging') not in {c.get('main_pose', [None])[-1] for c in cards}:
                raise ValueError('Unreviewed action in staging plan')
            decisions[len(chain)]={'staging':item['staging'],'line':item['line'],**meta}; chain.append(item['staging'])
    return chain,decisions,cards


def direction(row):
    parts=[]
    if row['order_index']==0:
        if row['foreplay_mode']=='already_established': parts.append('Open with the selected action already established')
        elif row['entry_mode']!='linear' or row['foreplay_mode']=='not_in_shot': parts.append('Open directly on the selected action')
    if row.get('change_from'):
        parts.append(f"After {row['change_from']}, continue in the new posture")
    if row['transition']=='one_take': parts.append(f"Move continuously from {row['pre']} into {row['post']} without a cut")
    if row['transition']=='cut': parts.append(f"Begin after a cut from {row['pre']} to {row['post']}")
    parts.extend(f'{k}: {row[k].replace("_"," ")}' for k in FIELDS if row[k] not in ('none','NA'))
    if row['scene_end']=='exit': parts.append('Both leave the frame at the end' if row['exit']=='both' else row['exit']+' leaves the frame at the end')
    if row['scene_end']=='hold': parts.append('Hold the final stance')
    return '. '.join(parts)


if __name__ == '__main__':
    from whale_pose_select import load_poses
    print(json.dumps(candidate_index(load_poses()), ensure_ascii=False, indent=2))
