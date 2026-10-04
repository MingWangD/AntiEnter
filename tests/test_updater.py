import unittest
import sys
from pathlib import Path

_current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_current_dir.parent))

from src.updater import parse_version, is_newer

class TestUpdater(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(parse_version("1.0.0"), (1, 0, 0))
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("V2.0"), (2, 0))

    def test_is_newer(self):
        self.assertTrue(is_newer("v1.2.1", "1.2.0"))
        self.assertTrue(is_newer("2.0.0", "1.9.9"))
        self.assertFalse(is_newer("1.2.0", "1.2.0"))
        self.assertFalse(is_newer("v1.1.0", "1.2.0"))

if __name__ == "__main__":
    unittest.main()
