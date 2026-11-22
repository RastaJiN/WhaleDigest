"""Exercise the serialized scene -> selected batch boundary; no renderer."""
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from test_scene_blocking import build, put, sc
import tunjing_pose_choice as choice
from tunjing_task_source import TaskSourceError, execution_board_path, load_task_source


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')


class ShotFactContract(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.batch = self.root / '批量任务.json'

    def reviewed(self, text=None):
        source = self.root / '剧本.md'
        text = text or ('## 场次 A\n乔禾（女）值班。\n'
                        '**乔禾**：`<d>[Chinese]先读 A|B。</d>`\n'
                        '**莫川：** `<d>[Chinese]收到了。</d>`')
        source.write_text(text, encoding='utf8')
        poses = sc.load_poses()
        with redirect_stdout(io.StringIO()):
            choice.choose(text, source, poses, 'office')
            chain, decisions, cards = choice.reviewed_plan(self.root, source, 'office')
            shots, actual = sc.build_scene(chain, 12, poses, decisions=decisions)
            review = dict(cards=cards, review_inputs={n: choice.file_hash(self.root / n)
                                                      for n in (choice.PLAN, choice.CARD)})
            sc.save_project_artifacts(self.root, shots, actual, 12, chain=chain, review=review,
                                      scene='office', script_path=source)
        return load_task_source(self.root)[1]

    def mutations_rejected(self, original, changes, index=0):
        """One drift at a time; all original prompt bytes must survive the mutation."""
        for path, replacement in changes:
            with self.subTest(field=path):
                batch = deepcopy(original)
                obj = batch['batch_shots'][index]
                for part in path[:-1]:
                    obj = obj[part]
                self.assertNotEqual(obj[path[-1]], replacement)
                obj[path[-1]] = replacement
                self.assertEqual([s['prompt'] for s in batch['batch_shots']],
                                 [s['prompt'] for s in original['batch_shots']])
                write_json(self.batch, batch)
                with self.assertRaises(TaskSourceError):
                    load_task_source(self.root)
        write_json(self.batch, original)

    def test_reviewed_rows_keep_the_shot_they_were_compiled_from(self):
        put(self.root, [{'id': 'A', 'from': 1, 'world': {'S1': 'seated'},
                         'props': {'letter': 'S2'}, 'shots': {
                             '1': {'action': '<Subject 1> stands up.',
                                   'end': {'world': {'S1': 'standing'}}}}}])
        batch = self.reviewed()
        row = batch['batch_shots'][0]
        self.assertEqual(row['dialogue']['text'], '先读 A|B。')
        self.assertIn('<d>[Chinese]先读 A|B。</d>', row['prompt'])
        self.mutations_rejected(batch, [
            (('id',), 'shot_9'), (('shot_id',), 'shot_09'),
            (('source_line',), 9), (('source_scene',), 'B'),
            (('blocking_state', 'source_shot'), 2),
            (('blocking_state', 'start', 'props', 'letter'), 'S1'),
            (('blocking_state', 'end', 'world', 'S1'), 'seated'),
            (('blocking_state', 'action'), 'Hold.'),
            (('cast', 'S1'), '莫川'), (('dialogue', 'actor'), 'S2'),
            (('dialogue', 'speaker'), '莫川'), (('dialogue', 'cue'), 'VO'),
            (('dialogue', 'text'), '另一句。'), (('camera_motion',), 'slow_push'),
            (('shot_size',), 'wide'), (('frames',), 39), (('duration',), 1.63),
        ])

    def test_ordered_inputs_are_checked_against_the_execution_board(self):
        put(self.root, [{'id': 'A', 'from': 1, 'world': {'S1': 'seated'}}])
        board, _ = build(self.root, ['srs_female', 'env_establish'], lines='1:S2(VO):等等。')
        batch = load_task_source(self.root)[1]
        first = batch['batch_shots'][0]
        self.assertEqual(first['references'], ['f1', 's1', 's1'])
        self.assertIn('voice S2', first['prompt'])
        self.assertEqual(execution_board_path(self.root), board)
        self.mutations_rejected(batch, [
            (('ref_images',), list(reversed(first['ref_images']))),
            (('references',), ['s1', 'f1', 's1']), (('tier',), 'B_solo_male'),
            (('audio_fx_mode',), 'normal'), (('shot_id',), 'shot_08'),
            (('blocking_state', 'source_shot'), 2),
            (('blocking_state', 'start', 'world', 'S1'), 'standing'),
            (('blocking_state', 'end', 'world', 'S1'), 'standing'),
        ])
        # Reading the board for Gate 3 must not take a less strict path.
        batch['batch_shots'].reverse()
        write_json(self.batch, batch)
        with self.assertRaises(TaskSourceError):
            execution_board_path(self.root)

    def test_adopted_speech_comes_from_board_not_the_visible_listener(self):
        adopted = put(self.root, [{'id': 'A', 'from': 1, 'world': {'S1': 'seated'}}])
        _, rows = build(self.root, ['srs_female', 'env_establish'], lines='1:S2(VO):等等。')
        batch = load_task_source(self.root)[1]
        self.assertEqual((self.root / '分镜.md').read_bytes(), adopted)
        speech, = [s for s in rows[0]['prompt'].splitlines() if s.startswith('SPEECH:')]
        for before, after in [('voice S2', 'voice S1'), ('等等。', '走吧。'), (speech, '')]:
            with self.subTest(replacement=after):
                changed = deepcopy(batch)
                changed['batch_shots'][0]['prompt'] = rows[0]['prompt'].replace(before, after)
                write_json(self.batch, changed)
                with self.assertRaises(TaskSourceError):
                    load_task_source(self.root)
        changed = deepcopy(batch)
        changed['batch_shots'][1]['prompt'] += '\n' + speech
        write_json(self.batch, changed)
        with self.assertRaises(TaskSourceError):
            load_task_source(self.root)

    def test_adopted_row_cannot_change_recorded_camera_pose_or_timing(self):
        put(self.root, [{'id': 'A', 'from': 1, 'shots': {'1': {'pose': 'srs_male'}}}])
        build(self.root, ['srs_male'])
        batch = load_task_source(self.root)[1]
        self.mutations_rejected(batch, [(('pose',), 'env_establish'), (('shot_size',), 'wide'),
                                        (('camera_motion',), 'static_front'), (('frames',), 73),
                                        (('duration',), 3.04)])

    def test_action_changes_do_not_pass_by_rehashing_the_batch_and_json_snapshot(self):
        batch = self.reviewed('镜8：direct_entry；foreplay=none；main_pose=lap_sit。')
        original = batch['batch_shots'][0]['prompt']
        # Leave the adopted card and the execution board intact. Replacing the two
        # export copies together must not redefine the approved action or camera.
        snap = self.root / choice.BOARD
        board = json.loads(snap.read_text('utf8'))
        for shot in (batch['batch_shots'][0], board['shots'][0]):
            shot['action_decision']['initiator'] = shot['action_steps'][0]['initiator'] = 'S2'
        write_json(snap, board)
        batch['pose_input_hashes'][snap.name] = choice.file_hash(snap)
        write_json(self.batch, batch)
        self.assertEqual(batch['batch_shots'][0]['prompt'], original)
        with self.assertRaises(TaskSourceError):
            load_task_source(self.root)

    def test_alternate_batch_cannot_discard_bound_adopted_inputs(self):
        put(self.root, [{'id': 'A', 'from': 1}])
        build(self.root, ['srs_female'])
        batch = load_task_source(self.root)[1]
        stripped = self.root / 'old.json'
        for key in ('blocking_input_hashes', 'execution_board'):
            batch.pop(key)
        write_json(stripped, batch)
        write_json(self.root / '.tunjing_project.json', {'active_batch': stripped.name})
        with self.assertRaises(TaskSourceError):
            load_task_source(self.root)

    def test_different_named_master_in_the_same_slot_is_not_the_confirmed_image(self):
        batch = self.reviewed()
        self.mutations_rejected(batch, [(('ref_images', 0), 'other_valid_master.png'),
                                        (('references', 0), 'm1')])


if __name__ == '__main__':
    unittest.main()
