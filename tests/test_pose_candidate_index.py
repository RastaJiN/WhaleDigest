import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import whale_pose_choice as choice


class CandidateTest(unittest.TestCase):
    def test_every_matrix_name_resolves_to_its_own_id(self):
        poses = json.loads((ROOT / 'references/whale_poses_matrix.json').read_text('utf8'))
        index = choice.candidate_index(poses)
        self.assertEqual(list(index), sorted(poses))
        text = '\n'.join(f"镜{i}：{item['nameZh']}。" for i,item in enumerate(poses.values()))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(choice.choose(text, Path(tmp)/'剧本.md', poses, ''), list(poses))
        for pid, row in index.items():
            self.assertIn(poses[pid]['nameZh'], row['aliases'])
            self.assertEqual(poses[pid]['category'], row['category'])

    def test_single_card_modes_and_order(self):
        from whale_pose_select import load_poses
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'剧本.md'
            state = source.with_name('分镜体位选择.json')
            text = '镜1：前戏，然后女上坐姿，再单人动作。'
            def run(): return choice.choose(text, source, load_poses(), '')
            with self.assertRaises(SystemExit): run()
            card, = json.loads(state.read_text('utf8'))
            steps = card['steps']
            self.assertEqual([s['role'] for s in steps], ['foreplay','main_pose','solo_action'])
            self.assertEqual(set(steps[1]['候选']), {'cowgirl','cowgirl_upright','reverse_cowgirl','lap_sit','lap_sit_back'})
            for s, pid in zip(steps, ['none','lap_sit','pillow_hump']): s['选择'] = pid
            card['transitions_order'] = [0,2,1]
            state.write_text(json.dumps([card]), encoding='utf8')
            self.assertEqual(run(), ['pillow_hump','lap_sit'])

    def test_directed_export_and_contradiction(self):
        from whale_pose_select import load_poses
        import subprocess, os
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder/'剧本.md'
            text = '镜1：lap_sit 然后 cowgirl_upright。'
            source.write_text(text, encoding='utf8')
            def choose(): return choice.choose(source.read_text('utf8'), source, load_poses(), '酒店客房')
            state = folder/'分镜体位选择.json'
            choose()
            card, = json.loads(state.read_text('utf8'))
            step = card['steps'][1]
            step.update(support='wall',initiator='S1',pace='slow',transition='one_take')
            card.update(scene_end='exit',exit='S1')
            def save(): state.write_text(json.dumps([card]),encoding='utf8')
            save()
            with self.assertRaises(SystemExit): choose()
            step['support']='supine'; save()
            cmd=[sys.executable,str(ROOT/'scripts/whale_pipeline.py'),str(source),'--dry','--total','60']
            run=subprocess.run(cmd,capture_output=True,env={**os.environ,'PYTHONUTF8':'1'})
            batch=folder/'批量任务.json'
            self.assertTrue(batch.exists(),run.stderr)
            shots=json.loads(batch.read_text('utf8'))['batch_shots']
            row=next(x for x in shots if x['pose']=='cowgirl_upright')
            frozen=json.loads((folder/'已决分镜.json').read_text('utf8'))['shots']
            dec=row['action_decision']
            self.assertEqual(next(x for x in frozen if x['pose']=='cowgirl_upright')['action_decision'], dec)
            self.assertEqual((dec['pre'],dec['post']),('lap_sit','cowgirl_upright'))
            self.assertIn('without a cut',row['prompt']); self.assertIn('S1 leaves the frame',row['prompt'])
            self.assertIn('pace: slow',row['prompt'])
            source.write_text(text.replace('镜1','镜2'),encoding='utf8'); choose()
            new,=json.loads(state.read_text('utf8')); self.assertEqual(new['exit'],'NA')
            self.assertEqual(new['steps'][1]['pace'],'NA')

    def test_ordinary_furnishings_and_dialogue(self):
        from whale_pose_select import load_poses
        with tempfile.TemporaryDirectory() as tmp:
            result = choice.choose('镜1：空镜，地板和床边。\n镜2：她用手指向门，站着说：“女上坐姿。”', Path(tmp)/'剧本.md', load_poses(), '')
            self.assertEqual(result, [])
