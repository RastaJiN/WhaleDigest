import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import tunjing_pose_choice as choice
from tunjing_pose_select import load_poses


class PoseConfirmationContract(unittest.TestCase):
    def _choose(self, folder, text, scene="bedroom"):
        source = folder / "剧本.md"
        source.write_text(text, encoding="utf-8")
        return choice.choose(text, source, load_poses(), scene), source, folder / "分镜体位选择.json"

    def test_ordinary_dialogue_empty_shot_and_non_intimate_standing_do_not_open_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            text = (
                "镜1：她说：‘女上位。’\n"
                "镜2：空间建立空镜，地板和床边。\n"
                "镜3：两人站着交谈，随后各自看向门口。\nS1：亲密站姿？\n"
            )
            result, _, state = self._choose(folder, text)
            self.assertEqual(result, ["env_establish"])
            self.assertFalse(state.exists())

    def test_ambiguous_intimate_content_stops_on_one_unified_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / "剧本.md"
            text = "镜1：亲密站姿。"
            source.write_text(text, encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                choice.choose(text, source, load_poses(), "bedroom")
            self.assertEqual(raised.exception.code, 3)
            cards = json.loads((folder / "分镜体位选择.json").read_text(encoding="utf-8"))
            self.assertEqual(len(cards), 1)
            card = cards[0]
            self.assertEqual(card["scene_mode"], "intimate")
            self.assertEqual(card["entry_mode"], "linear")
            self.assertEqual([step["role"] for step in card["steps"]], ["main_pose"])
            self.assertFalse(card["resolved"])
            self.assertEqual(set(card["steps"][0]["候选"]), {"stand_face_hug", "stand_doggy_wall", "stand_bend_doggy"})

    def test_direct_entry_and_nonlinear_modes_are_explicit_and_do_not_invent_foreplay(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            direct = (
                "镜1：direct_entry；foreplay=none；main_pose=lap_sit；"
                "solo_action=pillow_hump；order=main_pose>solo_action。"
            )
            result, source, state = self._choose(folder, direct, "chair")
            self.assertEqual(result, ["lap_sit", "pillow_hump"])
            card = json.loads(state.read_text(encoding="utf-8"))[0]
            self.assertEqual(card["entry_mode"], "direct_entry")
            self.assertEqual(card["foreplay_mode"], "none")
            self.assertEqual(card["foreplay"], ["none"])
            self.assertEqual(card["selected_order"], ["lap_sit", "pillow_hump"])
            self.assertNotIn("kiss_fondle", result)

            nonlinear = (
                "镜2：nonlinear；foreplay=already_established；"
                "main_pose=cowgirl_upright；solo_action=toy_tease；"
                "order=solo_action>main_pose。"
            )
            source.write_text(nonlinear, encoding="utf-8")
            result = choice.choose(nonlinear, source, load_poses(), "bedroom")
            self.assertEqual(result, ["toy_tease", "cowgirl_upright"])
            card = json.loads(state.read_text(encoding="utf-8"))[0]
            self.assertEqual(card["entry_mode"], "nonlinear")
            self.assertEqual(card["foreplay_mode"], "already_established")
            self.assertEqual(card["selected_order"], ["toy_tease", "cowgirl_upright"])
            self.assertNotIn("undress", result)

    def test_not_in_shot_foreplay_and_confirmed_fields_survive_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            text = (
                "镜1：非线性切入；前戏=not_in_shot；main_pose=lap_sit；main_pose=cowgirl_upright；"
                "solo_action=pillow_hump。"
            )
            result, source, state = self._choose(folder, text, "chair")
            self.assertEqual(result, ["lap_sit", "cowgirl_upright", "pillow_hump"])
            card = json.loads(state.read_text(encoding="utf-8"))[0]
            for step in card["steps"]:
                if step["选择"] == "lap_sit":
                    step.update(initiator="S1", pace="slow", facing="face_to_face", support="seated_lap", load="S2")
                elif step["选择"] == "cowgirl_upright":
                    step.update(transition="one_take", initiator="S2", pace="fast")
                elif step["选择"] == "pillow_hump":
                    step.update(initiator="S1", pace="fast", facing="away", support="floor", load="S1")
                    step["transition"] = "cut"
            card.update(scene_end="exit", exit="S1")
            state.write_text(json.dumps([card], ensure_ascii=False, indent=2), encoding="utf-8")
            self.assertEqual(choice.choose(text, source, load_poses(), "chair"), result)

            cmd = [
                sys.executable, str(SCRIPTS / "tunjing_scene.py"),
                "--chain", ",".join(result),
                "--card-offset", "0", "--total", "10", "--scene", "chair",
                "--script-file", str(source), "--out-dir", str(folder),
            ]
            run = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"})
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

            frozen = json.loads((folder / "已决分镜.json").read_text(encoding="utf-8"))
            self.assertEqual(frozen["cards"][0]["foreplay_mode"], "not_in_shot")
            self.assertEqual(frozen["cards"][0]["entry_mode"], "nonlinear")
            self.assertEqual(frozen["cards"][0]["selected_order"], ["lap_sit", "cowgirl_upright", "pillow_hump"])
            rows = json.loads((folder / "批量任务.json").read_text(encoding="utf-8"))
            self.assertEqual(rows["storyboard_cards"][0]["foreplay_mode"], "not_in_shot")
            action_rows = [row for row in rows["batch_shots"] if "action_decision" in row]
            self.assertEqual([[s['选择'] for s in r['action_steps']] for r in action_rows],
                             [['lap_sit','cowgirl_upright'], ['pillow_hump']])
            self.assertEqual([r['action_steps'] for r in action_rows], [r['action_steps'] for r in frozen['shots']])
            from tunjing_compiler import parse_prompt_sections, lint_tunjing_document
            from tunjing_task_source import load_task_source, validate_batch_metadata
            validate_batch_metadata(load_task_source(folder)[1]); md=(folder/'视频提示词.md').read_text('utf8')
            self.assertEqual(lint_tunjing_document(md)[0], [])
            for row in action_rows: self.assertIn(row['prompt'], md)
            visual=[parse_prompt_sections(r['prompt'])[0]['detailed_description'] for r in action_rows]
            for cue in ('Open directly','lap_sit','cowgirl_upright','without a cut','initiator: S1','initiator: S2',
                        'pace: slow','pace: fast','facing: face to face','support: seated lap','load: S2'):
                self.assertIn(cue, visual[0])
            self.assertLess(visual[0].index('pace: slow'), visual[0].index('pace: fast'))
            self.assertEqual(visual[0].count('Camera:'),1)
            self.assertIn('after a cut',visual[1]); self.assertIn('S1 leaves the frame',visual[1])
            batch_path = folder/'批量任务.json'
            fresh = batch_path.read_bytes()
            action_rows[0]['prompt'] = action_rows[0]['prompt'].replace('pace: slow','pace: fast')
            batch_path.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf8')
            with self.assertRaises(ValueError): load_task_source(folder)
            batch_path.write_bytes(fresh)
            for name in ['剧本.md','分镜体位选择.json','已决分镜.json','视频提示词.md']:
                with self.subTest(stale=name):
                    path=folder/name; original=path.read_bytes(); path.write_bytes(original+b'\n')
                    with self.assertRaises(ValueError): load_task_source(folder)
                    path.write_bytes(original); load_task_source(folder)

    def test_source_hash_change_clears_previous_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            text = "镜1：direct_entry；foreplay=none；main_pose=lap_sit。"
            result, source, state = self._choose(folder, text, "chair")
            self.assertEqual(result, ["lap_sit"])
            old = json.loads(state.read_text(encoding="utf-8"))[0]
            old['steps'][0].update(initiator='S1', pace='fast')
            state.write_text(json.dumps([old]), encoding='utf8')
            choice.choose(text, source, load_poses(), 'chair')
            source.write_text(text.replace("main_pose=lap_sit", "女上坐姿"), encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                choice.choose(source.read_text(encoding="utf-8"), source, load_poses(), "chair")
            self.assertEqual(raised.exception.code, 3)
            new = json.loads(state.read_text(encoding="utf-8"))[0]
            self.assertNotEqual(new["source_hash"], old["source_hash"])
            self.assertEqual(new["steps"][0]["pace"], "NA")
            self.assertEqual(new["选择"], "")
            self.assertEqual(new["foreplay"], ["none"])
            self.assertEqual(new["entry_mode"], "direct_entry")

    def test_non_intimate_aliases_and_explicit_absent_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            # Distinguish physical metadata or conversational words from visible intimacy.
            plain='镜1：两人先后入座，谈起往事。\n镜2：非亲密站立，面对面交谈。\n镜3：只有言语挑逗，无身体接触。\n镜4：单人动作：他站着看表。\n镜5：empty_cut。'
            ids,_,state=self._choose(root,plain); self.assertFalse(state.exists()); self.assertNotIn('stand_face_hug',ids)
            text='镜1：nonlinear；foreplay=not_in_shot；main_pose=none；solo_action=toy_tease。'
            chain,_,state=self._choose(root,text); self.assertEqual(chain,['toy_tease'])
            c,=json.loads(state.read_text('utf8')); self.assertEqual((c['main_pose'],c['solo_action']),(['none'],['toy_tease']))

    def test_spoken_tease_and_ordinary_solo_labels_do_not_mask_later_actions(self):
        for text in ('只有言语挑逗，无身体接触。随后亲密站姿。',
                     '单人动作：他站着看表。然后女上坐姿。',
                     '单人动作：她整理衣领；随后亲密站姿。'):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with self.assertRaises(SystemExit) as pending:
                    self._choose(root, '镜1：' + text)
                self.assertEqual(pending.exception.code, 3)
                card, = json.loads((root / choice.CARD).read_text('utf8'))
                self.assertEqual([s['role'] for s in card['steps']], ['main_pose'])
        for text in ('单人动作：待定。', '挑逗。'):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(SystemExit) as pending:
                    self._choose(Path(tmp), '镜1：' + text)
                self.assertEqual(pending.exception.code, 3)

    def test_explicit_absence_cannot_override_visible_same_role(self):
        for text, role in [('main_pose=none；main_pose=lap_sit。', 'main_pose'),
                           ('solo_action=none；solo_action=toy_tease。', 'solo_action')]:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with self.assertRaises(SystemExit) as pending:
                    self._choose(root, '镜1：' + text)
                self.assertEqual(pending.exception.code, 3)
                card, = json.loads((root / choice.CARD).read_text('utf8'))
                self.assertTrue(any(role in e and 'contradict' in e for e in card['errors']), card['errors'])

    def test_one_take_uses_first_camera_and_all_visible_cast_not_just_endpoint(self):
        from tunjing_scene import build_scene, save_project_artifacts
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); text='镜1：lap_sit，然后 solo_action=pillow_hump。'
            _,source,state=self._choose(root,text); card,=json.loads(state.read_text('utf8'))
            card['steps'][1]['transition']='one_take'; state.write_text(json.dumps([card]),encoding='utf8')
            choice.choose(text,source,load_poses(),'bedroom'); cmd=[sys.executable,'-X','utf8',str(SCRIPTS/'tunjing_scene.py'),'--out-dir',str(root),'--scene','bedroom','--chain','lap_sit,pillow_hump']
            run=subprocess.run(cmd,capture_output=True); self.assertEqual(run.returncode,0,run.stderr)
            row,=json.loads((root/'批量任务.json').read_text('utf8'))['batch_shots']
            self.assertEqual(row['camera_motion'],'arc_subtle'); self.assertNotEqual(row['ref_images'][1],row['ref_images'][2]);self.assertIn('<Subject 2>',row['prompt'])
            self.assertEqual(row['action_steps'][0]['framing']['cam'], row['camera_motion'])
            self.assertIn('straddles his lap face-to-face', row['prompt'])
            # A machine receipt may locate staging shots; it cannot inject a new intimate action.
            plan_path=root/choice.PLAN; plan=json.loads(plan_path.read_text('utf8')); plan['sequence'].append({'staging':'cowgirl','line':1})
            plan_path.write_text(json.dumps(plan),encoding='utf8')
            with self.assertRaises(ValueError): choice.reviewed_plan(root,source,'bedroom')

    def test_speech_overflow_does_not_replay_a_confirmed_exit(self):
        from tunjing_scene import prepare_dialogue_shots
        shot = dict(pose='lap_sit', size='mcu', action_steps=[{'scene_end':'exit'}])
        with self.assertRaisesRegex(ValueError,'分镜|reviewed'):
            prepare_dialogue_shots([shot], '1:S1:'+'来。'*90, 12)

    def test_single_reviewed_action_needs_no_extra_pose_for_gate_2(self):
        from tunjing_gatekeeper import audit_step_2
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); text='## 第一幕\n## 第二幕\n镜1：direct_entry；foreplay=none；main_pose=lap_sit。'
            self._choose(root,text)
            ok,why=audit_step_2(root); self.assertTrue(ok,why)
            (root/'剧本.md').write_text('## 第一幕\n## 第二幕\n',encoding='utf8'); self.assertFalse(audit_step_2(root)[0])

    def test_machine_appendix_does_not_hide_authored_shots_added_after_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); before='镜1：env_establish。'
            text=before+choice.GENERATED+'的吞鲸标准调度序列（供门禁与分镜引擎识别）：\n\n- `env_establish` 空镜\n\n镜2：亲密站姿。'
            with self.assertRaises(SystemExit): self._choose(root,text)
            card,=json.loads((root/choice.CARD).read_text('utf8')); self.assertEqual(card['镜头'],'镜2')

    def test_foreplay_and_solo_repeat_in_review_order_not_role_order(self):
        from tunjing_compiler import parse_prompt_sections
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); text='镜1：nonlinear；foreplay=kiss_fondle；solo_action=toy_tease；foreplay=kiss_pin；solo_action=pillow_hump；main_pose=lap_sit。'
            _,source,state=self._choose(root,text)
            card,=json.loads(state.read_text('utf8')); card.update(transitions_order=[3,2,4,1,0],scene_end='hold')
            state.write_text(json.dumps([card]),encoding='utf8'); chain=choice.choose(text,source,load_poses(),'bedroom')
            expected=['pillow_hump','kiss_pin','lap_sit','toy_tease','kiss_fondle']; self.assertEqual(chain,expected)
            run=subprocess.run([sys.executable,'-X','utf8',str(SCRIPTS/'tunjing_scene.py'),'--chain',','.join(chain),'--scene','bedroom','--out-dir',str(root)],capture_output=True)
            self.assertEqual(run.returncode,0,run.stderr)
            batch=json.loads((root/'批量任务.json').read_text('utf8')); self.assertEqual([s['pose'] for s in batch['batch_shots']],expected)
            c,=batch['storyboard_cards']; self.assertEqual(c['foreplay'],['kiss_pin','kiss_fondle']); self.assertEqual(c['solo_action'],['pillow_hump','toy_tease']); self.assertEqual(c['transitions_order'],[3,2,4,1,0]); self.assertEqual(c['foreplay_mode'],'in_shot')
            self.assertIn('Hold the final stance',parse_prompt_sections(batch['batch_shots'][-1]['prompt'])[0]['detailed_description'])
            self.assertNotIn('Hold the final stance',batch['batch_shots'][0]['prompt'])

    def test_cli_mixed_source_keeps_speaker_shot_and_visible_action_order(self):
        from dryrun_test import png_bytes
        from tunjing_task_source import load_task_source
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); source=folder/'剧本.md'; assets=folder/'00_资产'; assets.mkdir()
            for name in ('female_dressed.png','male_dressed.png','female_nude.png','male_nude.png','scene_main.png'):
                (assets/name).write_bytes(png_bytes())
            source.write_text('## 第一幕\n镜1：direct_entry；foreplay=none；女上坐姿。\n'
                              '## 第二幕\n镜2：空镜。\n镜3：两人站着交谈。男子A：<d>[Chinese]开会。</d>\n'
                              '镜4：非线性切入；单人动作。',encoding='utf8')
            def run(script,*args):
                return subprocess.run([sys.executable,'-X','utf8',str(SCRIPTS/script),*map(str,args)],
                                      capture_output=True,encoding='utf8',env=dict(os.environ,PYTHONUTF8='1'))
            pipe=('tunjing_pipeline.py',folder,'--dry','--total','18')
            wrong=('tunjing_scene.py','--out-dir',folder,'--chain','undress,cowgirl')
            self.assertNotEqual(run(*wrong).returncode,0)
            self.assertEqual(run(*pipe).returncode,3)
            for name in ('批量任务.json','已决分镜.json','视频提示词.md'): self.assertFalse((folder/name).exists())
            state=folder/'分镜体位选择.json'; cards=json.loads(state.read_text('utf8'))
            self.assertEqual([c['镜头'] for c in cards],['镜1','镜4'])
            cards[0]['选择']='lap_sit_back'; cards[1].update(选择='pillow_hump',foreplay_mode='already_established')
            state.write_text(json.dumps(cards),encoding='utf8')
            resolved=run(*pipe); self.assertEqual(resolved.returncode,0,resolved.stdout+resolved.stderr)
            self.assertEqual(run('export_comfy_payload.py',folder,'--offline').returncode,0)
            _,batch,_=load_task_source(folder); rows=batch['batch_shots']
            self.assertEqual([r['pose'] for r in rows],['lap_sit_back','env_establish','blocking_2s','pillow_hump'])
            self.assertNotIn('SPEECH:',rows[0]['prompt']); self.assertIn('<Subject 2> (S2) says:',rows[2]['prompt'])
            self.assertIn('already established',rows[3]['prompt']); self.assertNotIn('already established',rows[0]['prompt'])
            for name in batch['pose_input_hashes']:
                path=folder/name; original=path.read_bytes(); path.write_bytes(original+b'\n')
                self.assertNotEqual(run('export_comfy_payload.py',folder,'--offline').returncode,0)
                path.write_bytes(original)
            self.assertNotEqual(run(*wrong).returncode,0)
            doc=source.read_text('utf8').replace('女上坐姿','女上坐姿，姿态未定')
            source.write_text(doc,encoding='utf8'); self.assertEqual(run(*pipe).returncode,3)
            c,d=json.loads(state.read_text('utf8')); self.assertFalse(c['resolved']); self.assertEqual(d['选择'],'pillow_hump')
            self.assertNotEqual(run('export_comfy_payload.py',folder,'--offline').returncode,0)

    def test_gate_distinguishes_shot_directions_from_actual_dialogue(self):
        from tunjing_gatekeeper import audit_step_2
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'剧本.md'
            text='## 第一幕\n镜1：env_establish。\n## 第二幕\n镜2：lap_sit。\n'
            source.write_text(text,encoding='utf8')
            ok,why=audit_step_2(root); self.assertTrue(ok,why)
            for speech in ('女子A：还有事。','镜3：女子A：还有事。','镜3：他说：还有事。'):
                source.write_text(text+speech,encoding='utf8'); self.assertFalse(audit_step_2(root)[0],speech)

    def test_negative_or_context_only_and_ambiguous_visible_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            text='镜1：非亲密站姿，两人并排交谈。\n镜2：没有亲密动作，两人先后入场。\n镜3：她站姿端正。'
            ids,_,state=self._choose(root,text)
            self.assertEqual(ids,[]); self.assertFalse(state.exists())
            for action in ['两人缠绵，体位未定','她站着与他亲密接触','两人亲密站姿','他说：“等一下。”随后亲密站姿']:
                with self.assertRaises(SystemExit) as cm: self._choose(root,'镜1：'+action)
                self.assertEqual(cm.exception.code,3)
                card,=json.loads(state.read_text('utf8')); self.assertFalse(card['resolved'])

    def test_invalid_entry_order_role_transition_or_presence_stays_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'剧本.md'; text='镜1：lap_sit，然后 cowgirl。'
            _,_,state=self._choose(root,text); original=state.read_text('utf8')
            for change in [{'pre':'wrong'},{'post':'wrong'},{'transition':'teleport'}]:
                cards=json.loads(original); cards[0]['steps'][1].update(change); state.write_text(json.dumps(cards),encoding='utf8')
                with self.assertRaises(SystemExit): choice.choose(text,source,load_poses(),'bedroom')
                self.assertTrue(json.loads(state.read_text('utf8'))[0]['errors'])
            for line in ['foreplay=none；foreplay=kiss_fondle；main_pose=lap_sit', 'solo_action=lap_sit',
                         'main_pose=lap_sit；solo_action=pillow_hump；order=solo_action>solo_action',
                         'direct_entry；foreplay=kiss_fondle；main_pose=lap_sit']:
                with self.subTest(line=line), self.assertRaises(SystemExit): self._choose(root,'镜1：'+line)

    def test_contradictory_confirmed_support_blocks_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            text = "镜1：main_pose=lap_sit。"
            result, source, state = self._choose(folder, text, "chair")
            self.assertEqual(result, ["lap_sit"])
            card = json.loads(state.read_text(encoding="utf-8"))[0]
            card["steps"][0].update(support="wall", facing="face_to_face", load="S2")
            state.write_text(json.dumps([card], ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                choice.choose(text, source, load_poses(), "chair")
            self.assertEqual(raised.exception.code, 3)
            current = json.loads(state.read_text(encoding="utf-8"))[0]
            self.assertFalse(current["resolved"])
            self.assertTrue(any("support" in error and "lap_sit" in error for error in current["errors"]))


if __name__ == "__main__":
    unittest.main()
