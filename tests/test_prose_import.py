import unittest
from whale_prose import dialogue_on

class TestProseImport(unittest.TestCase):
    def test_prose_logic(self):
        # 原 neutral.md 内容 (模拟)
        neutral_data = "女子A：<d>[Chinese]你好。</d>"
        self.assertTrue(dialogue_on(neutral_data))
        
        # 原 actions.md 内容 (模拟)
        actions_data = "男子A：<d>[Chinese]过来。</d>"
        self.assertTrue(dialogue_on(actions_data))

if __name__ == "__main__":
    unittest.main()
