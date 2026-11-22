from test_scene_blocking import build
from tunjing_pose_select import select_poses_from_script
from pathlib import Path
import tempfile
import unittest

CASES = dict(dildo_masturbate='假阳具自慰', pillow_hump='骑枕头', toy_tease='玩具挑逗', lying_dildo='仰卧假阳具自慰')

class SoloProps(unittest.TestCase):
    def test_selection(self):
        for pid, word in CASES.items():
            self.assertEqual(select_poses_from_script(word, '卧室')[0], [pid])
        self.assertEqual(select_poses_from_script('卧室有枕头和玩具')[0], [])

    def test_offline_export(self):
        import subprocess
        import sys
        import tunjing_scene as scene
        import tunjing_gatekeeper as gate
        from dryrun_test import png_bytes
        for aspect in ('9:16', '16:9', '1:1'):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                assets = root / '00_资产'
                assets.mkdir()
                for name in ('female_ref.png', 'male_ref.png', 'scene_main.png'):
                    (assets / name).write_bytes(png_bytes())
                (root / '剧本.md').write_text('## 第一幕\ndildo_masturbate\n## 第二幕\npillow_hump toy_tease\n## 第三幕\nlying_dildo\n', encoding='utf8')
                shots, actual = scene.build_scene(list(CASES), 24, scene.load_poses())
                scene.save_project_artifacts(tmp, shots, actual, 24, scene='bedroom', aspect=aspect)
                for step in range(1, 7):
                    self.assertTrue(gate.check_gate(tmp, step), (aspect, step))
                subprocess.run([sys.executable, '-X', 'utf8', str(Path(scene.__file__).with_name('export_comfy_payload.py')), tmp, '--offline'], check=True)

    def test_artifacts(self):
        for aspect in ('9:16','16:9','1:1'):
            with tempfile.TemporaryDirectory() as tmp:
                _, rows = build(Path(tmp), list(CASES), aspect=aspect)
                for row in rows:
                    self.assertEqual(row['ref_images'][1:], ['scene_main.png'] * 2)
                    self.assertNotIn('<Subject 2>', row['prompt'])
                    self.assertIn('support', row['prompt'])
