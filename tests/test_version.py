"""
AntiEnter 版本一致性测试 (涵盖 T17)
"""
import unittest
import json
import sys
from pathlib import Path

_current_dir = Path(__file__).resolve().parent
ROOT_DIR = _current_dir.parent
sys.path.insert(0, str(ROOT_DIR))

from src.config import get_version
import src.updater as updater


class TestVersionConsistency(unittest.TestCase):
    def test_t17_version_manifest_exists(self):
        """T17: 单一版本清单文件 version.json 必须存在且有效"""
        manifest = ROOT_DIR / "version.json"
        self.assertTrue(manifest.exists(), "根目录必须存在 version.json")
        with open(manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("version", data)
        version_str = data["version"]
        self.assertEqual(version_str, "1.2.5")

    def test_t17_updater_matches_manifest(self):
        """T17: updater.CURRENT_VERSION 必须与单一版本清单完全一致"""
        manifest_ver = get_version()
        self.assertEqual(updater.CURRENT_VERSION, manifest_ver)


if __name__ == "__main__":
    unittest.main()
