import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
RECIPE = {"orientation":"Two standing subjects face each other.", "support":"Both keep their weight on planted feet.", "beats":["One raises a palm.", "The other mirrors the gesture."], "framing":{"size":"wide", "cam":"static_side"}}

def export(project, pid):
    return subprocess.run([sys.executable, str(ROOT/'scripts/tunjing_scene.py'), '--out-dir', str(project), '--chain',pid,'--total','5','--scene','studio'], capture_output=True, encoding='utf8', env={**os.environ,'PYTHONIOENCODING':'utf8'})

class LocalPose(unittest.TestCase):
    def test_resolution(self):
        sys.path.insert(0,str(ROOT/'scripts'))
        from tunjing_local_recipe import resolve
        from tunjing_pose_select import select_poses_from_script
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'pose_recipes.json'
            path.write_text('{',encoding='utf8')
            self.assertEqual(resolve(['blocking_2s'],{'blocking_2s':1},d),{})
            for recipe in [None, {}, dict(RECIPE,support=' '),dict(RECIPE,beats=['only']),dict(RECIPE,framing={})]:
                path.write_text(json.dumps({'standing_signal':recipe}),encoding='utf8')
                with self.assertRaises(ValueError): resolve(['standing_signal'],{},d)
        self.assertNotIn('stand_face_hug',select_poses_from_script('两人面对面站着，各自举手。','墙')[0])

    def test_export(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); (p/'pose_recipes.json').write_text(json.dumps({'standing_signal':RECIPE}),encoding='utf8')
            r=export(p,'standing_signal'); self.assertEqual(r.returncode,0,r.stderr)
            shot=json.loads((p/'批量任务.json').read_text('utf-8-sig'))['batch_shots'][0]
            for text in [RECIPE['orientation'],RECIPE['support'],*RECIPE['beats']]: self.assertIn(text,shot['prompt'])
            self.assertEqual((shot['custom_recipe'],shot['shot_size'],shot['camera_motion'],shot['wardrobe_state']),('standing_signal','wide','static_side','dressed'))
