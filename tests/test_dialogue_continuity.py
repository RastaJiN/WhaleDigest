"""Offline acceptance: check the final prompts and the actual batch, not rendered pixels."""
import contextlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import tunjing_scene as scene
from tunjing_compiler import lint_tunjing_prompt
from tunjing_core import single_shot_prompt
from tunjing_dialogue import build_blocking_lock


def make_prompt(pose, speaker, *, side='left', line='单据呢？', vo=False, audio=False):
    size = 'cu' if pose.startswith('srs_') else 'mcu'
    tier = scene.resolve_slot_refs(size, pose, is_nude_state=False)[0]
    return single_shot_prompt({'pose': pose, 'size': size, 'female_screen_side': side,
                               'blocking': '隔门', 'text_en': 'a measured glance', 'text': '看一眼'},
                              0, 1, 5.88, 'medium close-up framed from hips to chest', 'eye-level tripod',
                              speaker=speaker, lines=line, scene='doorway', tier=tier,
                              voiceover=vo, has_audio_refs=audio)


def speech_of(prompt):
    return [s.strip() for s in prompt.splitlines() if s.startswith('SPEECH:')]


class DialogueContinuity(unittest.TestCase):
    def test_two_shot_one_mouth_both_speaker_orders(self):
        for actor, other in ((1, 2), (2, 1)):
            with self.subTest(actor=actor):
                p = make_prompt('blocking_2s', f'S{actor}')
                self.assertFalse(lint_tunjing_prompt(p)[0], lint_tunjing_prompt(p)[0])
                s, = speech_of(p)
                self.assertEqual(s.count('<d>'), 1)
                self.assertIn(f'<Subject {actor}>', s.split('<d>')[0])
                self.assertNotIn(f'<Subject {other}>', s.split('<d>')[0])
                self.assertRegex(s.split('</d>')[1], fr'<Subject {other}>.*(?:silent|closed)')
                self.assertNotIn('from hips to chest', p.split('Camera: ', 1)[1].splitlines()[0])
                self.assertIn('door', p.split('COMPOSITION LOCK:')[1].lower())

    def test_reverse_closeups_keep_side_gaze_and_reference_isolation(self):
        for side in ('left', 'right'):
            for actor, pose in ((1, 'srs_female'), (2, 'srs_male')):
                with self.subTest(side=side, actor=actor):
                    other = 3 - actor
                    pos = side if actor == 1 else ('right' if side == 'left' else 'left')
                    gaze = 'right' if pos == 'left' else 'left'
                    p = make_prompt(pose, f'S{actor}', side=side, audio=True)
                    self.assertFalse(lint_tunjing_prompt(p)[0], lint_tunjing_prompt(p)[0])
                    self.assertNotIn(f'<Subject {other}>', p)
                    self.assertNotIn(f'<Audio {other}>', p)
                    lock = p.split('COMPOSITION LOCK:')[1].split('\n')[0]
                    self.assertRegex(lock, fr'<Subject {actor}>[^.;]*screen[- ]{pos}')
                    self.assertRegex(lock, fr'(?:gaze|look)\w*[^.;]{{0,50}}screen[- ]{gaze}')

    def test_single_subject_does_not_speak_for_an_absent_actor(self):
        with self.assertRaises(ValueError):
            make_prompt('srs_male', 'S1')

    def test_voiceover_and_silent_shots(self):
        p = make_prompt('blocking_2s', 'S1', vo=True)
        self.assertFalse(lint_tunjing_prompt(p)[0], lint_tunjing_prompt(p)[0])
        s, = speech_of(p)
        self.assertIn('voiceover', s)
        self.assertRegex(s.lower(), r'(?:both|all visible).*lips.*closed')
        quiet = make_prompt('blocking_2s', '', line='')
        self.assertFalse(speech_of(quiet))
        self.assertFalse(lint_tunjing_prompt(quiet)[0])

    def test_reaction_shot_accepts_offcamera_voice_without_an_extra_face(self):
        for pose, actor in [('srs_female', 2), ('srs_male', 1)]:
            with self.subTest(pose=pose):
                prompt = make_prompt(pose, f'S{actor}', vo=True)
                self.assertEqual(lint_tunjing_prompt(prompt)[0], [])
                speech, = speech_of(prompt)
                self.assertIn('voiceover', speech)
                self.assertIn(f'S{actor}', speech)
                self.assertNotIn(f'<Subject {actor}>', prompt)
                self.assertIn('lips remain closed', speech)

    def test_single_shot_editor_uses_the_visible_speaker(self):
        from tunjing_storyboard import build_prompt
        for pose, actor in [('srs_male', 2), ('srs_female', 1)]:
            with self.subTest(pose=pose):
                prompt = build_prompt([pose], dur=5.88, lines='确认。', scene='office')
                self.assertEqual(lint_tunjing_prompt(prompt)[0], [])
                speech, = speech_of(prompt)
                self.assertIn(f'<Subject {actor}>', speech)
                self.assertNotIn(f'<Subject {3 - actor}>', prompt)

    def test_ambiguous_entries_are_rejected_instead_of_guessing(self):
        for speaker in ('Subject 10', 'female and male', '某人'):
            with self.subTest(speaker=speaker), self.assertRaises(ValueError):
                make_prompt('blocking_2s', speaker)
        with self.assertRaises(ValueError):
            scene.prepare_dialogue_shots([{'pose':'blocking_2s','size':'mcu'}], '1:S1:第一句|1:S2:第二句', 6)

    def test_gate_rejects_a_second_voice_in_one_request(self):
        p = make_prompt('blocking_2s', 'S1')
        s, = speech_of(p)
        self.assertTrue(lint_tunjing_prompt(p.replace(s, s+'\nSPEECH: <Subject 2> (S2) says: <d>[Chinese]同一句。</d>.'))[0])
        self.assertTrue(lint_tunjing_prompt(p.replace(s, 'SPEECH: <Subject 1> and <Subject 2> say: <d>[Chinese]你好。</d>.'))[0])
        self.assertTrue(lint_tunjing_prompt(p.replace(s, s.split('</d>')[0]+'</d>. Both voices speak in unison.'))[0])

    def test_staging_does_not_invent_a_table(self):
        for scene_name, word in [('两人隔桌','table'), ('隔门','door'), ('贴墙','wall'), ('并排','side by side')]:
            with self.subTest(scene_name=scene_name):
                self.assertIn(word, build_blocking_lock(scene_name, '')[1])
        self.assertNotIn('table', build_blocking_lock('neutral courtyard', '')[1].lower())

    def test_shorthand_and_ledger_survive_batch_export(self):
        for aspect in ('9:16','16:9','1:1'):
            for side in ('left','right'):
                with self.subTest(aspect=aspect, side=side), tempfile.TemporaryDirectory() as temp:
                    project = Path(temp)
                    (project/'.tunjing_axis.json').write_text(json.dumps({'female_screen_side':side}), encoding='utf-8')
                    ids = ['env_establish','blocking_2s','srs_male','srs_female']
                    shots, sec = scene.build_scene(ids, 24, scene.load_poses())
                    with contextlib.redirect_stdout(io.StringIO()):
                        _, md, batch = scene.save_project_artifacts(temp, shots, sec, 24, scene='doorway', aspect=aspect,
                                                                    lines='男：单据呢？\n女：就在这里。')
                    rows = json.loads(Path(batch).read_text(encoding='utf-8'))['batch_shots']
                    doc = Path(md).read_text(encoding='utf-8')
                    spoken = []
                    for row in rows:
                        prompt = row['prompt']
                        self.assertIn(prompt, doc)
                        self.assertFalse(lint_tunjing_prompt(prompt)[0], lint_tunjing_prompt(prompt)[0])
                        if row['pose'] == 'blocking_2s':
                            self.assertRegex(prompt, fr'<Subject 1>[^.;\n]{{0,40}}screen[- ]{side}')
                        for sl in speech_of(prompt):
                            self.assertNotEqual(row['pose'], 'env_establish')
                            spoken.append((re.search(r'<Subject ([12])>', sl)[1], re.search(r'<d>\[Chinese\](.*?)</d>', sl)[1]))
                    self.assertEqual(spoken, [('2','单据呢？'),('1','就在这里。')])

if __name__ == '__main__':
    unittest.main()
