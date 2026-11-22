"""Offline regression at the exported batch boundary."""
from pathlib import Path
import re
import tempfile
import unittest

from test_scene_blocking import build, put


class VisibilitySequence(unittest.TestCase):
    def test_reaction_voice_does_not_change_visible_cast(self):
        ids = ['blocking_2s', 'srs_female', 'srs_male', 'blocking_2s', 'env_establish']
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            put(root, [{'id': 'A', 'from': 1, 'world': {'S1': 'seated', 'S2': 'at the doorway'}}])
            _, rows = build(root, ids, lines='2:S2(VO):等等。')
        self.assertEqual([r['pose'] for r in rows], ids)
        female, male, scene = 'female_dressed.png', 'male_dressed.png', 'scene_main.png'
        for i, cast in enumerate(({1, 2}, {1}, {2}, {1, 2}, set())):
            with self.subTest(shot=i + 1):
                row = rows[i]
                self.assertEqual(row['ref_images'], [female if 1 in cast else scene,
                                                     male if 2 in cast else scene, scene])
                visual = '\n'.join(s for s in row['prompt'].splitlines() if not s.startswith('SPEECH:'))
                for actor, mark in [(1, 'seated'), (2, 'at the doorway')]:
                    self.assertEqual(f'<Subject {actor}>' in visual, actor in cast)
                    self.assertEqual(f'<Picture {actor}>' in visual, actor in cast)
                    self.assertEqual(mark in visual, actor in cast)
                if not cast:
                    self.assertNotRegex(visual.lower(), r'anatomical|performer|both faces')
                speech = re.findall(r'^SPEECH:.*$', row['prompt'], re.M)
                if i == 1:
                    self.assertEqual(len(speech), 1)
                    self.assertRegex(speech[0], r'S2.*off-screen voiceover.*<d>\[Chinese\]等等。</d>.*lips remain closed')
                    self.assertNotRegex(visual, r'\bS2\b|<Audio 2>|等等')
                else:
                    self.assertEqual(speech, [])
