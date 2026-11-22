import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import whale_pacing as p

class Pace(unittest.TestCase):
    def test_backward_compatible(self):
        shots=[{'pose':'srs_female','text':'original'}]
        self.assertEqual(p.apply(shots), shots)
    def test_invalid_and_incompatible(self):
        with self.assertRaises(ValueError): p.parse_overrides('[{"shot": 1, "driver":"warp"}]')
        with self.assertRaises(ValueError): p.apply([{'pose':'srs_female'}], 'slow')
    def test_override_preserves_action_and_adds_driver(self):
        shots=[{'pose':'missionary','text':'original motion'}]
        out=p.apply(shots, overrides={1:'slow'})
        self.assertEqual(out[0]['text'], 'original motion')
        self.assertIn('Pace driver:', p.prompt_clause(out[0]))

if __name__ == '__main__': unittest.main()
