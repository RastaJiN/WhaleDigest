"""Independent source excerpts; assertions exercise review and exported requests."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import tunjing_pose_choice as choice
from tunjing_core import load_poses


class ProseImport(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = Path(tmp.name)
        self.source = self.project / '剧本.md'

    def review(self, text):
        self.source.write_text(text, encoding='utf8')
        try:
            choice.choose(text, self.source, load_poses(), 'studio')
        except SystemExit as stop:
            self.assertEqual(stop.code, 3)
        state = self.project / choice.CARD
        return json.loads(state.read_text('utf8')) if state.exists() else []

    def test_compound_and_negation_apply_to_mentions_not_whole_line(self):
        for text, expected in [
            ('特写两只手，十指交叉扣住。', []),
            ('镜7：手指交错，不要拍指交。', []),
            ('镜3：十指交扣，随后指交。', [['fingering']]),
            ('镜8：不接颜射或内射，随后转为 lap_sit。', [['lap_sit']]),
            ('镜6：不是前戏而是亲密站姿。', [list(choice.STAND)]),
            ('镜4：不要再拍接吻，然后拍接吻。', [['kiss_pin']]),
            ('镜2：她说：“用女上坐姿。”然后亲密站姿。', [list(choice.STAND)]),
            ('不耐烦地转为观音坐莲。', [list(choice.SEAT)]),
            ('他不慌不忙地继续亲密站姿。', [list(choice.STAND)]),
            ('镜5：指交不入镜，然后接吻。', [['kiss_pin']]),
        ]:
            with self.subTest(text=text):
                steps = [list(s['候选']) for c in self.review(text) for s in c['steps']]
                self.assertEqual(steps, expected)

    def test_headings_locate_not_schedule_the_action(self):
        ordinary = '## 冲印室\n### 墙边站立\n她撑着墙站稳，等师傅校准相机。'
        self.assertEqual(self.review(ordinary), [])
        text = ('## 收工：观音坐莲至站立后入\n> 简介：站立后入。\n'
                '### 椅旁\n她主动转为坐在他身上，手指交握。\n'
                '### 墙面\n直接切入已开始的亲密动作，两人站着撑墙，他从背后配合。')
        cards = self.review(text)
        self.assertEqual([c['原文'] for c in cards], [text.splitlines()[3], text.splitlines()[5]])
        seat, wall = cards
        self.assertEqual(len(seat['steps']), 1)
        self.assertEqual(set(seat['steps'][0]['候选']), set(choice.SEAT))
        self.assertFalse(seat['resolved']); self.assertEqual(seat['steps'][0]['initiator'], 'S1')
        self.assertTrue(wall['resolved'], wall['errors'])
        self.assertEqual(wall['selected_order'], ['stand_doggy_wall'])
        self.assertEqual((wall['entry_mode'], wall['foreplay_mode']), ('direct_entry','already_established'))
        # A family in the overview must not become an actual shot by itself.
        self.assertEqual(self.review('## 观音坐莲至站立后入\n> 观音坐莲。\n空镜。'), [])

    def test_family_in_body_is_not_an_alias_for_one_pose(self):
        card, = self.review('镜9：观音坐莲。')
        self.assertEqual(set(card['steps'][0]['候选']), set(choice.SEAT))
        self.assertFalse(card['选择'])
        self.assertRegex(card.get('question',''), r'坐.*仰卧.*朝向')
        self.assertEqual(self.review('镜9：观音坐莲（`lap_sit_back`）。')[0]['selected_order'], ['lap_sit_back'])

    def cli(self, script, *args):
        return subprocess.run([sys.executable, '-X', 'utf8', str(ROOT/'scripts'/script), *map(str,args)],
                              cwd=ROOT, capture_output=True, encoding='utf8', env=dict(os.environ,PYTHONUTF8='1'))

    def test_named_markdown_turns_remain_bound_by_scene_in_export(self):
        text = ('# 夜班\n## 场次 信号台\n乔禾（女）靠在墙边。\n'
                '**乔禾**：`<d>[Chinese]先读 A|B。</d>`\n'
                '- **莫川：** `<d>[Chinese]说的是观音坐莲？</d>`\n'
                '## 场次 印刷间\n**石青:** <d>[Chinese]灯亮了。</d>\n'
                '乔禾：<d>[Chinese]without cutting。</d>')
        self.source.write_text(text, encoding='utf-8-sig'); original=self.source.read_bytes()
        pipe = ('tunjing_pipeline.py', self.project, '--dry', '--total', '28')
        no_assets = self.cli(*pipe)
        self.assertEqual(no_assets.returncode, 1, no_assets.stdout + no_assets.stderr)
        self.assertTrue((self.project/'批量任务.json').exists(), no_assets.stdout + no_assets.stderr)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertFalse((self.project/choice.CARD).exists())
        from dryrun_test import png_bytes
        batch = json.loads((self.project/'批量任务.json').read_text('utf8'))
        assets = self.project/'00_资产'; assets.mkdir()
        for filename in {f for row in batch['batch_shots'] for f in row['ref_images']}:
            (assets/filename).write_bytes(png_bytes())
        done=self.cli(*pipe); self.assertEqual(done.returncode,0,done.stdout + done.stderr)
        self.assertEqual(self.cli('export_comfy_payload.py',self.project,'--offline').returncode,0)
        board=json.loads((self.project/choice.BOARD).read_text('utf8'))
        rows=json.loads((self.project/'批量任务.json').read_text('utf8'))['batch_shots']
        expected = [('信号台','乔禾','S1','先读 A|B。'),('信号台','莫川','S2','说的是观音坐莲？'),
                    ('印刷间','石青','S2','灯亮了。'),('印刷间','乔禾','S1','without cutting。')]
        got=[]; refs={}
        for b,r in zip(board['shots'],rows,strict=True):
            self.assertEqual(b.get('dialogue'),r.get('dialogue'))
            self.assertNotIn('action_steps', r)
            if 'dialogue' not in b: continue
            speech, = re.findall(r'^SPEECH: (.*)$',r['prompt'],re.M)
            actor, words = re.search(r'\((S[12])\) says: <d>\[Chinese\](.*?)</d>',speech).groups()
            name=b['dialogue']['speaker']; self.assertEqual(b['dialogue']['text'],words)
            self.assertEqual(b['cast'][actor], name)
            got.append((b['blocking_state']['scene_id'],name,actor,words)); refs[name]=r['ref_images'][int(actor[1])-1]
        self.assertEqual(got, expected); self.assertNotEqual(refs['莫川'],refs['石青'])
        # A different valid master in the same slot must not satisfy a missing named asset.
        (assets/refs['莫川']).unlink(); missing=self.cli(*pipe)
        self.assertNotEqual(missing.returncode,0); self.assertIn(refs['莫川'],missing.stdout+missing.stderr)

    def test_unbound_names_never_default_to_first_speaker_or_shot(self):
        self.source.write_text('## 场次 堤岸\n**水杉：** `<d>[Chinese]等等。</d>`\n'
                               '**小麦：** `<d>[Chinese]好。</d>`',encoding='utf8')
        run=self.cli('tunjing_pipeline.py',self.project,'--dry')
        self.assertNotEqual(run.returncode,0); self.assertIn('角色映射',run.stdout+run.stderr)
        self.assertFalse((self.project/'批量任务.json').exists())

    def test_staging_notes_and_established_geometry_reach_final_prompts(self):
        from dryrun_test import png_bytes
        from tunjing_compiler import parse_prompt_sections
        text=('## 第一幕 · 放映室\n> 简介：本段从观音坐莲至站立后入。\n'
              '### 窗前\n她主动转为坐在他身上。镜头先给十指交握的特写，再推向她的脸和身体节奏。\n'
              '女子A：<d>[Chinese]停一下。</d>\n'
              '## 第二幕 · 暗房\n### 贴墙站立\n亲密动作已经开始，他从背后贴近，双手撑墙。\n'
              '女子A：<d>[Chinese]等灯灭。</d>\n'
              '停在她的脸和仍未平稳的呼吸，画面就此结束，不加内射。')
        cards=self.review(text); self.assertEqual([c['镜头'] for c in cards], ['第4行','第8行'])
        self.assertEqual([c['resolved'] for c in cards],[False,True]); self.assertFalse(cards[0]['选择'])
        cards[0]['选择']='lap_sit_back'
        (self.project/choice.CARD).write_text(json.dumps(cards), encoding='utf8')
        assets=self.project/'00_资产'; assets.mkdir()
        for name in ('male_nude.png','female_nude.png','male_dressed.png','female_dressed.png','scene_main.png'):
            (assets/name).write_bytes(png_bytes())
        done=self.cli('tunjing_pipeline.py',self.project,'--scene','studio','--total','30','--dry')
        self.assertEqual(done.returncode,0,done.stdout+done.stderr)
        self.assertEqual(self.cli('export_comfy_payload.py',self.project,'--offline').returncode,0)
        board=json.loads((self.project/choice.BOARD).read_text('utf8'))
        rows=json.loads((self.project/'批量任务.json').read_text('utf8'))['batch_shots']
        self.assertEqual(board['cards'],json.loads((self.project/'批量任务.json').read_text('utf8'))['storyboard_cards'])
        self.assertEqual([r['pose'] for r in rows if 'action_decision' in r], ['lap_sit_back','stand_doggy_wall'])
        visual=[parse_prompt_sections(r['prompt'])[0]['detailed_description'] for r in rows]
        hands,=[i for i,r in enumerate(rows) if r.get('staging_note',{}).get('kind')=='hands']
        self.assertLess(hands,next(i for i,r in enumerate(rows) if r['pose']=='stand_doggy_wall'))
        self.assertRegex(visual[hands],r'(?im)^Camera: [^\n]*hands[^\n]*(?:push|dolly)')
        self.assertIn('interlocked',visual[hands]); self.assertNotIn('pelvic',visual[hands]); self.assertIn('rhythm',visual[hands])
        self.assertEqual(rows[-1]['staging_note']['kind'],'ending_hold'); self.assertNotIn('action_steps',rows[-1])
        self.assertRegex(visual[-1], r'(?i)face'); self.assertIn('breath',visual[-1]); self.assertIn('End',visual[-1]);
        for b,r in zip(board['shots'],rows,strict=True): self.assertEqual(b.get('staging_note'),r.get('staging_note'))

    def test_only_the_affected_change_inherits_the_prior_pose(self):
        text = ('## 贮藏室 · 亲密动作\n镜1：lap_sit。\n镜2：转为观音坐莲。\n'
                '## 屋顶\n镜3：亲密站姿。')
        cards=self.review(text); self.assertEqual(len(cards),3)
        self.assertEqual(cards[1].get('change_from'),'lap_sit')
        self.assertFalse(cards[2].get('change_from'))

    def test_focal_note_cannot_become_an_unreviewed_visual_override(self):
        text='## 第一幕\n男子A：<d>[Chinese]左手。</d>\n## 第二幕\n手部特写，两手十指交扣。'
        self.review(text)
        path=self.project/choice.PLAN
        data=json.loads(path.read_text('utf8')); item=data['sequence'][-1]
        item['staging_note']['visual']='Discard the approved framing.'
        path.write_text(json.dumps(data),encoding='utf8')
        with self.assertRaises(ValueError): choice.reviewed_plan(self.project,self.source,'studio')

    def test_single_scene_repeated_utterances_are_not_deduplicated(self):
        # Different voices can intentionally say exactly the same words.
        self.source.write_text('### 场景 港口\n**阿梧**\n`<d>[Chinese]收到。</d>`\n'
                               '**阿蒲**：收到。\n阿梧：亲密站姿吗？',encoding='utf8')
        (self.project/'角色映射.json').write_text(json.dumps({'阿梧':'S2','阿蒲':'S1'}),encoding='utf8')
        done=self.cli('tunjing_pipeline.py',self.project,'--dry','--total','15')
        self.assertTrue((self.project/'批量任务.json').exists(),done.stdout+done.stderr)
        self.assertFalse((self.project/choice.CARD).exists())
        from dryrun_test import png_bytes
        assets=self.project/'00_资产'; assets.mkdir(); path=self.project/'批量任务.json'
        for name in {f for r in json.loads(path.read_text('utf8'))['batch_shots'] for f in r['ref_images']}:
            (assets/name).write_bytes(png_bytes())
        done=self.cli('tunjing_pipeline.py',self.project,'--dry','--total','15'); self.assertEqual(done.returncode,0,done.stdout+done.stderr)
        self.assertEqual(self.cli('export_comfy_payload.py',self.project,'--offline').returncode,0)
        rows=json.loads(path.read_text('utf8'))['batch_shots']
        self.assertEqual([(r['dialogue']['speaker'],re.search(r'<d>\[Chinese\](.*?)</d>',r['prompt'])[1]) for r in rows],
                         [('阿梧','收到。'),('阿蒲','收到。'),('阿梧','亲密站姿吗？')])
        override=self.cli('tunjing_pipeline.py',self.project,'--dry','--lines','1:S2:代词')
        self.assertNotEqual(override.returncode,0)
        (self.project/'角色映射.json').write_text('{}',encoding='utf8')
        self.assertNotEqual(self.cli('export_comfy_payload.py',self.project,'--offline').returncode,0)

    def test_multiple_turns_and_a_later_direction_keep_source_order(self):
        text=('镜7：**S1**：`<d>[Chinese]观音坐莲？</d>` **S2:** <d>[Chinese]留给之后。</d> '
              '随后亲密站姿。')
        card, = self.review(text); self.assertEqual(set(card['steps'][0]['候选']),set(choice.STAND))
        card['选择']='stand_face_hug'; state=self.project/choice.CARD
        state.write_text(json.dumps([card]),encoding='utf8'); self.review(text)
        chain, decisions, _=choice.reviewed_plan(self.project,self.source,'studio')
        self.assertEqual(chain,['srs_female','srs_male','stand_face_hug'])
        self.assertEqual([r['dialogue']['actor'] for r in decisions.values() if 'dialogue' in r],['S1','S2'])

    def test_paired_prose_fixtures_review_and_export(self):
        from dryrun_test import png_bytes
        pool=ROOT/'tests/fixtures/prose'
        for name in ('neutral','actions'):
            with self.subTest(name=name):
                project=self.project/name; project.mkdir(); source=project/'剧本.md'
                source.write_bytes((pool/(name+'.md')).read_bytes()); original=source.read_bytes()
                pipe=('tunjing_pipeline.py',project,'--dry','--aspect','16:9','--total','18')
                first=self.cli(*pipe); card_path=project/choice.CARD
                if name=='neutral':
                    self.assertFalse(card_path.exists()); self.assertEqual(first.returncode,1)
                else:
                    self.assertEqual(first.returncode,3,first.stdout+first.stderr); cards=json.loads(card_path.read_text('utf8'))
                    self.assertEqual([set(c['steps'][0]['候选']) for c in cards],
                                     [set(choice.SEAT),{'stand_doggy_wall'},{'fingering'}])
                    cards[0]['选择']='lap_sit'; cards[2]['选择']='fingering'
                    card_path.write_text(json.dumps(cards),encoding='utf8'); self.assertEqual(self.cli(*pipe).returncode,1)
                batch=project/'批量任务.json'; assets=project/'00_资产'; assets.mkdir()
                for f in {f for r in json.loads(batch.read_text('utf8'))['batch_shots'] for f in r['ref_images']}:
                    (assets/f).write_bytes(png_bytes())
                run=self.cli(*pipe); self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                export=self.cli('export_comfy_payload.py',project,'--offline'); self.assertEqual(export.returncode,0,export.stdout+export.stderr)
                frozen=json.loads((project/choice.BOARD).read_text('utf8')); data=json.loads(batch.read_text('utf8'))
                self.assertEqual(frozen['cards'],data['storyboard_cards']); self.assertEqual(source.read_bytes(),original)
                rows=data['batch_shots']; actual=[r['pose'] for r in rows if 'action_steps' in r]
                self.assertEqual(actual, [] if name=='neutral' else ['lap_sit','stand_doggy_wall','fingering'])
                hands,=[r for r in rows if r.get('staging_note',{}).get('kind')=='hands']
                self.assertIn('close-up on the hands',hands['prompt']); self.assertNotIn('pelvic',hands['prompt'])
                if name=='neutral':
                    self.assertIn('wall', rows[0]['prompt']); self.assertEqual(rows[0]['pose'],'blocking_2s')
                else:
                    wall,=[r for r in rows if r['pose']=='stand_doggy_wall']
                    self.assertNotIn('mattress',wall['prompt']); self.assertIn('already established',wall['prompt'])
                    self.assertEqual([c['selected_order'] for c in frozen['cards']],[[p] for p in actual])

    def test_legacy_selector_does_not_reintroduce_rejected_mentions(self):
        from tunjing_pose_select import select_poses_from_script as select
        self.assertEqual(select('两人手指交叉，不接颜射。')[0],[])
        self.assertEqual(select('观音坐莲。')[0],[])
        self.assertEqual(select('镜2：不要拍颜射，随后指交。')[0],['fingering'])

    def test_delivery_contract_rejects_missing_reordered_and_reassigned_speech(self):
        from tunjing_task_source import verify_sourced_dialogue as compare
        first=dict(line=4,index=0,speaker='舟',actor='S2',cue='',text='回来。')
        second=dict(line=6,index=0,speaker='桥',actor='S1',cue='',text='回来。')
        def shot(d, actor=None):
            return dict(dialogue=d,prompt=f"SPEECH: only <Subject {(actor or d['actor'])[1]}> ({actor or d['actor']}) says: <d>[Chinese]{d['text']}</d>.")
        receipt=[dict(dialogue=first),dict(dialogue=second)]
        compare(receipt,[shot(first),shot(second)])
        for bad in ([shot(first)], [shot(second),shot(first)], [shot(first,'S1'),shot(second)]):
            with self.assertRaises(ValueError): compare(receipt,bad)

    def test_outline_does_not_turn_wall_blocking_into_a_physical_pose(self):
        header='## 夜戏 · 站立后入至观音坐莲\n### 墙旁站立\n'
        self.assertEqual(self.review(header+'她站着靠墙，他从后方扶稳灯架。'), [])
        card,=self.review(header+'镜6：两人保持站立后入，双手撑在墙上。')
        self.assertEqual(card['selected_order'],['stand_doggy_wall']); self.assertTrue(card['resolved'])
