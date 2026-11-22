"""Check the exact H3 prompt, not prose in an editor or the rendered result."""
import json
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
compiler = import_module('whale_compiler')

# Local independent requests: six H3 fields, with our own Camera/SPEECH lines.
BODY = '''subject_definitions:
<Subject 1> is the clerk from <Picture 1>.
<Subject 2> is the visitor from <Picture 2>.
<Subject 3> is the office from <Picture 3>.
summary: A receipt changes hands.
retention_analysis:
<Subject 1>: fully_preserved for identity from <Picture 1>.
<Subject 2>: fully_preserved for identity from <Picture 2>.
<Subject 3>: weak_reference for framing from <Picture 3>.
detailed_description:
Camera: Static medium shot.
[Shot 1] At the counter, the camera holds; <Subject 1> unfolds the receipt.
SPEECH: From 1.00s to 2.00s, only <Subject 1> (S1) asks: <d>[Chinese]单据呢？</d>. <Subject 2> listens.
overall_soundscape: A page rustles.
non_diegetic_music: N/A'''


class Ref2VAContract(unittest.TestCase):
    @staticmethod
    def batch(prompt):
        return {'schema': 'h3-drama-task', 'batch_shots': [{
            'shot_id': 'shot_01', 'prompt': prompt, 'frames': 90, 'duration': 3.75,
            'ref_images': ['actor_a.png', 'actor_b.png', 'office.png'],
        }]}

    def test_dry_export_gate_and_workflow_reject_same_invalid_quote(self):
        bad = BODY.replace('单据呢？', '<Audio 1>单据呢？')
        batch = self.batch(bad)
        gate = import_module('whale_gatekeeper')
        export = import_module('export_comfy_payload')
        runner = import_module('whale_runner')
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / '批量任务.json').write_text(json.dumps(batch, ensure_ascii=False), encoding='utf-8')
            for fn in (gate.audit_step_4, export.verify_batch_json):
                with self.subTest(entry=fn.__name__):
                    passed, message = fn(folder)
                    self.assertFalse(passed, message)
                    self.assertIn('台词内', message)
        wf = json.loads(Path(runner.DEFAULT_WF).read_text(encoding='utf-8'))
        with self.assertRaisesRegex(ValueError, '台词内'):
            runner.build_shot_workflow(wf, batch['batch_shots'][0], batch=batch)

    def test_workflow_binds_original_bytes_and_rejects_stale_or_missing_text_route(self):
        runner = import_module('whale_runner')
        batch = self.batch(BODY)
        shot = batch['batch_shots'][0]
        template = json.loads(Path(runner.DEFAULT_WF).read_text(encoding='utf-8'))
        result = runner.build_shot_workflow(template, shot, batch=batch)
        node, index = result['265']['inputs']['prompt']
        self.assertEqual(index, 0)
        self.assertEqual(result[node]['inputs']['text'].encode('utf-8'), BODY.encode('utf-8'))
        for case in ('missing_text_node', 'wrong_port', 'old_literal', 'first_image_swapped'):
            with self.subTest(case=case):
                wf = json.loads(json.dumps(template))
                if case == 'missing_text_node': del wf[node]
                elif case == 'wrong_port': wf['265']['inputs']['prompt'] = [node, 1]
                elif case == 'old_literal': wf['265']['inputs']['prompt'] = 'old scene'
                else: wf['265']['inputs']['ref_images.ref_image_0'] = ['49', 0]
                with self.assertRaises(ValueError):
                    runner.build_shot_workflow(wf, shot, batch=batch)

    def test_spatial_description_is_not_a_technical_overlay_instruction(self):
        # Vertical lines can be the actual grain of an oak wall, not guide marks.
        text = BODY.replace('unfolds the receipt.',
                'unfolds the receipt beside an oak panel with vertical lines in the wood.')
        e, w = compiler.lint_whale_prompt(text)
        self.assertEqual([], e)
        self.assertTrue(w)

    def test_media_and_subject_labels_are_not_spoken_words(self):
        for label in ('<Picture 1>', '<Audio 2>', '<Video 1>', '<Subject 2>'):
            with self.subTest(label=label):
                bad = BODY.replace('单据呢？', '单据' + label + '呢？')
                errors, _ = compiler.lint_whale_prompt(bad)
                self.assertIn('台词内', ' '.join(errors))
                self.assertIn(label, ' '.join(errors))

    def test_identity_rebinding_is_rejected_without_guessing_stage_directions(self):
        cases = {
            'declaration': BODY.replace('clerk from <Picture 1>', 'clerk from <Picture 2>'),
            'retention': BODY.replace('identity from <Picture 1>.', 'identity from <Picture 2>.'),
            'speaker': BODY.replace('<Subject 1> (S1) asks:', '<Subject 1> (S2) asks:'),
            'missing': BODY.replace('the counter,', '<Subject 9> at the counter,'),
            'duplicate': BODY.replace('summary:', '<Subject 1> is another visitor from <Picture 2>.\nsummary:'),
        }
        self.assertEqual([], compiler.lint_whale_prompt(BODY)[0])
        for kind, bad in cases.items():
            with self.subTest(kind=kind):
                self.assertTrue(compiler.lint_whale_prompt(bad)[0], kind)

    def test_quote_is_one_line_inside_the_visual_timeline_only(self):
        with_newline = BODY.replace('单据呢？', '单据\n呢？')
        speech = next(s for s in BODY.splitlines() if s.startswith('SPEECH:'))
        in_sound = BODY.replace(speech + '\n', '').replace('non_diegetic_music:', speech + '\nnon_diegetic_music:')
        for kind, bad in [('line', with_newline), ('section', in_sound)]:
            with self.subTest(kind=kind):
                self.assertTrue(compiler.lint_whale_prompt(bad)[0], kind)

    def test_task_checks_actual_reference_capacity_not_just_syntax(self):
        gate = import_module('whale_gatekeeper')
        runner = import_module('whale_runner')
        template = json.loads(Path(runner.DEFAULT_WF).read_text(encoding='utf-8'))
        for label in ('<Picture 4>', '<Audio 1>', '<Video 1>'):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as folder:
                batch = self.batch(BODY.replace('A page rustles.', f'A page rustles as in {label}.'))
                (Path(folder) / '批量任务.json').write_text(json.dumps(batch), encoding='utf-8')
                self.assertFalse(gate.audit_step_4(folder)[0])
                with self.assertRaises(ValueError):
                    runner.build_shot_workflow(template, batch['batch_shots'][0], batch=batch)

    def test_approved_reference_mapping_can_use_an_additional_explicit_image(self):
        text = BODY.replace('clerk from <Picture 1>.', 'clerk from <Picture 1> in the coat from <Picture 4>.')
        self.assertEqual([], compiler.lint_whale_prompt(text)[0])

    def test_explicit_speaker_mapping_is_not_a_global_subject_equals_voice_rule(self):
        # In H3 visual and vocal IDs are separate namespaces. Explicit mapping wins.
        text = BODY.replace('<Subject 1> is the clerk', '<Subject 1> (S2) is the clerk').replace('(S1) asks:', '(S2) asks:')
        self.assertEqual([], compiler.lint_whale_prompt(text)[0])

    def test_internal_headers_and_unrecognised_seventh_field_are_not_model_input(self):
        for kind, bad in [('preamble', 'Internal work order\n' + BODY),
                          ('control', BODY + '\n[Visual Constraints | Do Not Speak]\nprivate note'),
                          ('field', BODY + '\neditorial_notes: add score in post')]:
            with self.subTest(kind=kind):
                self.assertTrue(compiler.lint_whale_prompt(bad)[0], kind)
        self.assertEqual([], compiler.lint_whale_prompt(BODY.replace('单据呢？', 'editorial_notes: 请看。'))[0])

    def test_near_miss_reference_cannot_escape_the_declared_subject_check(self):
        for label in ('<subject 9>', '<Subject 0>', '<Subject 03>', '<Picture 1 >'):
            with self.subTest(label=label):
                self.assertTrue(compiler.lint_whale_prompt(BODY.replace('unfolds the receipt.', f'looks at {label}.'))[0])

    def test_published_model_example_is_a_single_lintable_request(self):
        spec = (ROOT / 'references/official-prompt-assembly-spec.md').read_text(encoding='utf-8-sig')
        examples = [block.split('\n```', 1)[0] for block in spec.split('```text\n')[1:]]
        self.assertEqual(len(examples), 1, 'Publish the final body, not conflicting fragments')
        self.assertEqual(compiler.lint_whale_prompt(examples[0])[0], [])

    def test_plain_words_comparisons_and_offscreen_voice_are_legal(self):
        for phrase in ('价格 < 3 元。', 'Picture 1 是个文件名。', '他问：“好了吗？”'):
            with self.subTest(phrase=phrase):
                self.assertEqual([], compiler.lint_whale_prompt(BODY.replace('单据呢？', phrase))[0])
        shot = BODY.replace('<Subject 1> (S1) asks:', 'the narrator (voice S2) says in an off-screen voiceover:')
        self.assertEqual([], compiler.lint_whale_prompt(shot)[0])
