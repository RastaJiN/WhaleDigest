import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import whale_drama_storyboard as wds


class TestDramaStoryboard(unittest.TestCase):
    def test_long_dialogue_never_crushed_and_splits_cleanly(self):
        # 模拟《守护者日记》里 24 秒长台词（约 98 字）+ 普通对白 + 动作
        long_line = "我告诉你，这件事从头到尾都是他一个人在背后安排的，你以为你看到的那些证据是真的吗？" * 2
        script = f"""# EP001 测试集
## 场次 1：客厅对峙
赵斌：{long_line}
欢宝：你胡说！
赵斌冷笑一声，把文件摔在桌上。
"""
        scenes = wds.parse_drama_script(script)
        self.assertEqual(len(scenes), 1)
        shots, summary = wds.build_shots(scenes, episode_id="EP001", target_sec=150.0)
        # 长台词应被拆成多镜，每镜 <= 10s 且 >= 2.0s，绝不被压成 0.21s
        dlg_shots = [s for s in shots if s["kind"] == "dialogue"]
        self.assertGreaterEqual(len(dlg_shots), 3)
        for s in dlg_shots:
            self.assertGreaterEqual(s["duration"], 2.0)
            self.assertLessEqual(s["duration"], 10.0)
        md = wds.render_storyboard_md(shots, summary)
        self.assertIn("EP001-01", md)
        self.assertIn("实际总时长", md)


if __name__ == "__main__":
    unittest.main()
