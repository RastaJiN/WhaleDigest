import tempfile, subprocess, sys, json, os, unittest
from pathlib import Path

PIPE = Path(__file__).resolve().parents[1] / 'scripts/tunjing_pipeline.py'

class ChoiceTest(unittest.TestCase):
    def test_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            source = p/'剧本.md'
            source.write_text('镜1：女上坐姿。\n镜2：亲密站姿。', encoding='utf8')
            def run():
                return subprocess.run([sys.executable,str(PIPE),str(source),'--dry','--total','60'], capture_output=True,encoding='utf8',env={**os.environ,'PYTHONUTF8':'1'})
            state = p/'分镜体位选择.json'
            prompt = p/'视频提示词.md'
            first = run(); self.assertEqual(first.returncode, 3, first.stdout+first.stderr)
            self.assertFalse(prompt.exists()); self.assertFalse((p/'批量任务.json').exists()); cards=json.loads(state.read_text('utf8'))
            self.assertEqual(len(cards),2); run(); self.assertEqual(cards,json.loads(state.read_text('utf8')))
            for c, pid in zip(cards,['lap_sit_back','stand_face_hug']): c['选择']=pid
            state.write_text(json.dumps(cards),encoding='utf8'); result=run()
            self.assertTrue(prompt.exists(),result.stdout+result.stderr)
            board=(p/'分镜.md').read_text('utf8'); self.assertIn('lap_sit_back',board); self.assertIn('stand_face_hug',board)
            source.write_text(source.read_text('utf8').replace('镜2：','镜2：改为'),encoding='utf8'); self.assertEqual(run().returncode,3)
            a,b=json.loads(state.read_text('utf8')); self.assertEqual(a['选择'],'lap_sit_back'); self.assertFalse(b['选择'])
            b['选择']='unknown_recipe'; state.write_text(json.dumps([a,b]),encoding='utf8'); self.assertEqual(run().returncode,3)
            recipe={'orientation':'Face each other','support':'Both standing','beats':['Hold still','Step closer'],'framing':{'size':'mcu','cam':'static_side'}}
            (p/'pose_recipes.json').write_text(json.dumps({'custom_stand':recipe}),encoding='utf8')
            b['选择']='custom_stand'; state.write_text(json.dumps([a,b]),encoding='utf8'); result=run()
            self.assertIn('custom_stand',json.loads((p/'已决分镜.json').read_text('utf8'))['chain'],result.stdout+result.stderr)
            source.write_text('镜1：站立对话。\n镜2：女上坐姿 `lap_sit`。',encoding='utf8'); self.assertNotEqual(run().returncode,3); self.assertEqual([c['选择'] for c in json.loads(state.read_text('utf8'))],['lap_sit'])

if __name__=='__main__': unittest.main()
