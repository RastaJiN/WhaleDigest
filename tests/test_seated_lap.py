import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from whale_pose_select import select_poses_from_script


class SeatedLap(unittest.TestCase):
    def test_final_chair_prompts(self):
        import json, subprocess, tempfile
        for pid, posture, cam, movement in [
            ('lap_sit', 'straddles his lap face-to-face', 'arc_subtle', 'lateral dolly arc'),
            ('lap_sit_back', 'sits back-to him in his lap', 'ots_depth', 'over-the-shoulder'),
            ('cowgirl', 'lies on his back', 'low_upward', 'low-angle upward'),
            ('cowgirl_upright', 'torso upright', 'tilt_up_desire', 'vertical tilt-up'),
        ]:
            with self.subTest(pid=pid), tempfile.TemporaryDirectory() as d:
                subprocess.run([sys.executable, '-X', 'utf8', str(ROOT/'scripts/whale_scene.py'),
                                '--out-dir', d, '--chain', pid, '--total', '5', '--scene', '椅子'],
                               check=True, capture_output=True)
                shot = json.loads((Path(d)/'批量任务.json').read_text('utf-8-sig'))['batch_shots'][0]
                prompt = shot['prompt']
                self.assertEqual((shot['pose'], shot['camera_motion']), (pid, cam))
                self.assertIn(movement, next(l for l in prompt.splitlines() if l.startswith('Camera:')))
                self.assertIn(posture, prompt)
                self.assertIn('chair seat', prompt)
                self.assertNotRegex(prompt.lower(), r'\b(?:bed|mattress|bedsheets?)\b')
                self.assertNotRegex(prompt.lower(), r'first.person|\bpov\b')
                if pid.startswith('lap_sit'):
                    self.assertNotRegex(prompt.lower(), r'first.person|\bpov\b|supine|lies on his back|lying on his back')

    def test_spatial_facts_and_action_boundaries(self):
        front = '男人坐在椅子上，她面朝他跨坐在他的大腿上'
        back = '男人坐在椅子上，她背对他坐在他腿上'
        for text, ids in [(front + '（女上位）', ['lap_sit']),
                          ('女上位：' + back, ['lap_sit_back']),
                          (front + '，随后换成女上位', ['lap_sit', 'cowgirl']),
                          ('先女上位，随后' + back, ['cowgirl', 'lap_sit_back']),
                          ('`cowgirl_upright`：' + front, ['cowgirl_upright']),
                          ('她坐在椅子上，女上位', ['cowgirl'])]:
            with self.subTest(text=text):
                self.assertEqual(select_poses_from_script(text)[0], ids)
