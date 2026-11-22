"""The script and adopted storyboard own staging. No live model or production files."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import whale_scene as sc
from whale_compiler import lint_whale_prompt


def fence(tag, content):
    return f'```{tag}\n{json.dumps(content, ensure_ascii=False, indent=2)}\n```\n'


def shots(*ids):
    # One actual storyboard shot per entry, not one per pose-matrix beat.
    poses = sc.load_poses()
    return [dict(sc.build_scene([p], 6, poses)[0][0]) for p in ids]


def build(root, ids, **kw):
    args = dict(scene='office', aspect='16:9')
    args.update(kw)
    with contextlib.redirect_stdout(io.StringIO()):
        board, _, batch = sc.save_project_artifacts(str(root), shots(*ids), 24, 24, **args)
    return Path(board), json.loads(Path(batch).read_text(encoding='utf-8'))['batch_shots']


def put(root, scenes):
    text = '# 采用分镜（导演批注原样保留）\n' + fence('tunjing-blocking', {'scenes': scenes})
    (root/'分镜.md').write_text(text, encoding='utf-8')
    return (root/'分镜.md').read_bytes()


class BlockingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_envelope_stays_with_giver_across_insert_and_reverse(self):
        root = self.root
        (root/'剧本.md').write_text('## 场次 A\n甲递出信封，乙没有接。乙原本坐着。\n' + fence('tunjing-space', {'A': {'world': {'S1': 'seated'}, 'props': {'envelope': 'S2'}}}), encoding='utf-8')
        # A=scene identifier. The actors are 甲=S2, 乙=S1.
        source = put(root, [{'id':'A', 'from':1, 'screen_left':'S2', 'relation':'within_reach', 'shots': {
            '1':{'action':'<Subject 2> offers the envelope; <Subject 1> leaves it in the giver\'s hand.'},
            '2':{'action':'The envelope remains in the same hand.'},
            '3':{'action':'<Subject 1> looks down at the offered envelope, then looks back toward the giver.'}}}])
        (root/'.whale_axis.json').write_text('{"female_screen_side":"left"}',encoding='utf-8')
        old_axis=(root/'.whale_axis.json').read_bytes()
        board, rows = build(root, ['blocking_2s','prop_insert','srs_female','srs_male'], lines='1:S2:给你。|3:S1:先留着。')
        self.assertEqual((root/'分镜.md').read_bytes(), source)
        self.assertEqual((root/'.whale_axis.json').read_bytes(), old_axis)
        self.assertNotEqual(board.name,'分镜.md')
        for r in rows:
            b=r['blocking_state']; self.assertEqual(b['scene_id'],'A'); self.assertEqual(b['screen_left'],'S2'); self.assertEqual(b['end']['props']['envelope'],'S2'); self.assertEqual(b['end']['world']['S1'],'seated')
            self.assertEqual(lint_whale_prompt(r['prompt'])[0],[])
        self.assertIn('offers the envelope',rows[0]['prompt']);self.assertIn('within reach',rows[0]['prompt'].lower()); self.assertIn('envelope',rows[2]['prompt']);self.assertNotIn('<Subject 2>',rows[2]['prompt']); self.assertIn('screen-left',rows[2]['prompt'])
        self.assertNotIn('steps forward 15 cm',rows[0]['prompt']);self.assertNotIn('industrial metal desk',rows[0]['prompt']);self.assertIn('分镜明示',board.read_text(encoding='utf8'))

    def test_new_scene_is_independent_not_a_gender_or_speech_default(self):
        dirs=set()
        def compare(first_left,lines):
            put(self.root,[{'id':'A','from':1,'screen_left':first_left,'world':{'S1':'seated'},'props':{'envelope':'S2'}},{'id':'B','from':2}]); _,rs=build(self.root,['blocking_2s','blocking_2s','srs_male'],lines=lines)
            b=rs[1]['blocking_state']; self.assertEqual(b['source'],'分镜补定');self.assertFalse(b['start']['props']);self.assertFalse(b['start']['world']);self.assertEqual(b['screen_left'],rs[2]['blocking_state']['screen_left']);return b['screen_left']
        self.assertEqual(compare('S1','1:S1:好。|2:S2:好。'),compare('S2','1:S2:好。|2:S1:好。'))
        for i in range(12):
            put(self.root,[{'id':f'F{i}','from':1}]);_,rs=build(self.root,['blocking_2s']);dirs.add(rs[0]['blocking_state']['screen_left'])
        self.assertEqual(dirs,{'S1','S2'})

    def test_script_direction_wins_over_stale_cache_and_quoted_lines(self):
        (self.root/'.whale_axis.json').write_text('{"female_screen_side":"left"}',encoding='utf8')
        (self.root/'剧本.md').write_text('## 场次 A\n站位：男左女右\n女主：<d>[Chinese]下次改成女左男右。</d>\n', encoding='utf8')
        board,rs=build(self.root,['blocking_2s']); self.assertEqual(rs[0]['blocking_state']['screen_left'],'S2'); self.assertEqual(rs[0]['blocking_state']['source'],'剧本明示');self.assertTrue(board.is_file())

    def test_script_board_conflict_or_plot_question_preserves_artifacts(self):
        (self.root/'剧本.md').write_text('## 场次 A\n'+fence('tunjing-space',{'A':{'world':{'S2':'at the door'}}}),encoding='utf8')
        for bad, fragment in [({'world':{'S2':'at the window'}},'冲突'), ({'question':'乙能看见信封内容吗？'},'乙能看见')]:
            with self.subTest(bad=bad):
                saved=put(self.root,[{'id':'A','from':1,**bad}]); (self.root/'批量任务.json').write_bytes(b'old')
                with self.assertRaisesRegex(ValueError,fragment): build(self.root,['blocking_2s'])
                self.assertEqual((self.root/'批量任务.json').read_bytes(),b'old');self.assertEqual((self.root/'分镜.md').read_bytes(),saved)

    def test_plain_storyboard_and_script_with_no_position_are_not_a_blocker(self):
        # No JSON, left/right or creator decision is needed for ordinary dialogue.
        (self.root/'剧本.md').write_text('## 场次 A\n两人交谈。',encoding='utf8')
        original = '# 采用稿\n## 场次 A\n### SHOT-01\n- 用途：对话\n### SHOT-02\n- 用途：反打\n'
        path = self.root/'分镜.md';path.write_text(original,encoding='utf8')
        board,rs=build(self.root,['blocking_2s','srs_female']);self.assertEqual(path.read_text(encoding='utf8'),original)
        self.assertNotEqual(board,path);self.assertEqual(rs[0]['blocking_state']['source'],'分镜补定')
        self.assertEqual(rs[0]['blocking_state']['screen_left'],rs[1]['blocking_state']['screen_left'])

    def test_plain_direction_is_role_local_and_not_dialogue_or_a_room_label(self):
        original = '# 采用分镜\n## 场次 A\n### SHOT-01\n- 站位：男左女右\n- 空间：S1坐着，S2在门口\n### SHOT-02\n- 用途：反应\n'
        (self.root/'分镜.md').write_text(original,encoding='utf8')
        _,rows=build(self.root,['blocking_2s','srs_female'],lines='1:S2:换个地方。')
        self.assertEqual(rows[0]['blocking_state']['screen_left'],'S2')
        self.assertEqual(rows[1]['blocking_state']['start']['world'],{'S1':'seated','S2':'at the doorway'})
        self.assertIn('seated',rows[1]['prompt']);self.assertNotIn('table', rows[0]['prompt'].lower())

    def test_modified_adopted_board_invalidates_previous_batch_and_dry_runner(self):
        from whale_task_source import load_task_source
        put(self.root,[{'id':'A','from':1,'screen_left':'S2'}]); b,rows=build(self.root,['blocking_2s','srs_female'])
        load_task_source(self.root)
        self.assertNotEqual(b.name,'分镜.md')
        (self.root/'分镜.md').write_text('# 新采用稿',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'变更|重新编译'):load_task_source(self.root)

    def test_camera_crossing_is_not_a_world_move(self):
        scenes=[{'id':'A','from':1,'screen_left':'S1','world':{'S2':'at the door'},'shots':{'2':{'screen_left':'S2'}}}];put(self.root,scenes)
        with self.assertRaisesRegex(ValueError,'换位|越轴|换边'): build(self.root,['blocking_2s','blocking_2s','srs_male'])
        scenes[0]['shots']['2']['reframe']='Visible camera arc to the opposite side.';put(self.root,scenes)
        _,rs=build(self.root,['blocking_2s','blocking_2s','srs_male']); self.assertEqual([r['blocking_state']['screen_left'] for r in rs],['S1','S2','S2']);self.assertEqual(rs[0]['blocking_state']['end'],rs[2]['blocking_state']['start']);self.assertIn('Visible camera arc',rs[1]['prompt'])

    def test_ledger_is_not_the_director_of_a_new_scene(self):
        (self.root/'series_bible.json').write_text('{"spatial_axis":{"female_screen_side":"left"}}',encoding='utf8');_,r1=build(self.root,['blocking_2s']);
        (self.root/'series_bible.json').write_text('{"spatial_axis":{"female_screen_side":"right"}}',encoding='utf8');_,r2=build(self.root,['blocking_2s']);self.assertEqual(r1[0]['blocking_state'],r2[0]['blocking_state']);self.assertEqual(r2[0]['blocking_state']['source'],'分镜补定')

    def test_actor_moves_only_through_an_authored_action(self):
        plan=[{'id':'A','from':1,'world':{'S1':'seated'},'shots':{'2':{'end':{'world':{'S1':'standing'}}}}}]; put(self.root,plan)
        with self.assertRaisesRegex(ValueError,'动作|走位'):build(self.root,['blocking_2s','srs_female','srs_female'])
        plan[0]['shots']['2']['action']='<Subject 1> rises from the seat.';put(self.root,plan)
        _,rs=build(self.root,['blocking_2s','srs_female','srs_female']);self.assertEqual(rs[1]['blocking_state']['start']['world']['S1'],'seated');self.assertEqual(rs[2]['blocking_state']['start']['world']['S1'],'standing')

if __name__=='__main__':
    unittest.main()
