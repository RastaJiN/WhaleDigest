"""Exercise the real offline CLI and compare the two consumer artifacts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MotionExport(unittest.TestCase):
    def test_actor_is_not_speaker_or_camera(self):
        with tempfile.TemporaryDirectory() as tmp:
            shots = []
            for actor in (None, 'S1', 'S2'):
                out = Path(tmp) / str(actor)
                cmd = [sys.executable, 'scripts/whale_scene.py', '--chain', 'missionary', '--total', '8', '--lines', '1:S1:等等。', '--out-dir', str(out)]
                if actor:
                    cmd += ['--pace-overrides', json.dumps([dict(shot=1, actor=actor, pace=['fast', 'slow', 'steady'])])]
                subprocess.run(cmd, cwd=ROOT, env=dict(os.environ, PYTHONUTF8='1'), capture_output=True, check=True)
                rows = json.loads((out/'批量任务.json').read_text('utf8'))['batch_shots']
                prompt = rows[0]['prompt']
                self.assertIn(prompt, (out/'视频提示词.md').read_text('utf8'))
                if shots:
                    self.assertEqual(rows[1:], shots[0][1:])
                    self.assertEqual({k:v for k,v in rows[0].items() if k!='prompt'}, {k:v for k,v in shots[0][0].items() if k!='prompt'})
                shots.append(rows)
            baseline, a, b = [rows[0]['prompt'] for rows in shots]
            stale = baseline.split('At 0.00s: ')[1].split('\n')[0]
            self.assertNotIn('Man A', stale)
            self.assertNotIn('Woman A', stale)
            for n, text in enumerate((a,b), 1):
                pre, body = text.split('At 0.00s: ')
                action, post = body.split('\n', 1)
                self.assertEqual(pre, baseline.split('At 0.00s: ')[0])
                self.assertEqual(post, baseline.split('At 0.00s: ')[1].split('\n',1)[1])
                self.assertIn('<d>[Chinese]等等。</d>', post)
                self.assertIn(f'<Subject {3-n}> follows', action)
                for phase, speed in enumerate(('fast','slow','steady'),1):
                    self.assertIn(f'Phase {phase}: <Subject {n}> leads the weight shift at a {speed} tempo', action)
                self.assertLess(action.index('Phase 1'), action.index('Phase 2'))
                self.assertLess(action.index('Phase 2'), action.index('Phase 3'))
                for old in ('Man A', 'Body action:', 'piston strokes', 'held end-state'):
                    self.assertNotIn(old, action)
