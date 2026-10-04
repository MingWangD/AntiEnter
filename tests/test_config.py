import unittest
import os
import json
import tempfile
from pathlib import Path
import sys

# Ensure src is in the path
_current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_current_dir.parent))

from src.config import load_config, DEFAULT_CONFIG

class TestConfig(unittest.TestCase):
    def test_default_config_keys(self):
        self.assertIn("buffer_delay", DEFAULT_CONFIG)
        self.assertIn("play_sound", DEFAULT_CONFIG)
        self.assertIn("safety_fuse_enabled", DEFAULT_CONFIG)
        self.assertIn("dangerous_patterns", DEFAULT_CONFIG)
        self.assertIn("cli_prompt_patterns", DEFAULT_CONFIG)

    def test_load_config_fallback(self):
        # Even without a real file, it should load defaults or fallback config
        config = load_config()
        self.assertIsInstance(config, dict)
        self.assertIn("buffer_delay", config)
        self.assertIsInstance(config["buffer_delay"], (int, float))

    def test_dangerous_patterns_exist(self):
        config = load_config()
        patterns = config.get("dangerous_patterns", [])
        self.assertTrue(len(patterns) > 0)
        self.assertTrue(any("rm -rf" in p for p in patterns))

if __name__ == "__main__":
    unittest.main()
