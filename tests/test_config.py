"""
AntiEnter 配置与生命周期测试 (涵盖 T03, T10)
"""
import unittest
import os
import json
import tempfile
from pathlib import Path
import sys

_current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_current_dir.parent))

from src.config import (
    load_config,
    save_config,
    update_config,
    advance_generation,
    validate_config,
    DEFAULT_CONFIG,
    CONFIG_PATH,
)


class TestConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ["ANTIENTER_CONFIG_DIR"] = cls.temp_dir.name
        from src.config import save_config, DEFAULT_CONFIG
        save_config(DEFAULT_CONFIG)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()
        os.environ.pop("ANTIENTER_CONFIG_DIR", None)

    def setUp(self):
        from src.config import save_config, DEFAULT_CONFIG
        save_config(DEFAULT_CONFIG)

    def test_default_config_keys(self):
        self.assertIn("enabled", DEFAULT_CONFIG)
        self.assertIn("buffer_delay", DEFAULT_CONFIG)
        self.assertIn("play_sound", DEFAULT_CONFIG)
        self.assertIn("sound_theme", DEFAULT_CONFIG)
        self.assertIn("safety_fuse_enabled", DEFAULT_CONFIG)
        self.assertIn("generation", DEFAULT_CONFIG)

    def test_t03_fuse_toggle_and_persistence(self):
        """T03: 显式关闭熔断后重新开启，配置正确持久化"""
        # 1. 显式关闭
        updated = update_config({"safety_fuse_enabled": False})
        self.assertFalse(updated["safety_fuse_enabled"])
        reloaded = load_config()
        self.assertFalse(reloaded["safety_fuse_enabled"])

        # 2. 重新开启
        updated2 = update_config({"safety_fuse_enabled": True})
        self.assertTrue(updated2["safety_fuse_enabled"])
        reloaded2 = load_config()
        self.assertTrue(reloaded2["safety_fuse_enabled"])

    def test_t10_corrupted_config_recovery(self):
        """T10: 坏 JSON 或类型异常配置自动清洗回退安全默认值"""
        bad_config = {
            "buffer_delay": "not_a_number",
            "play_sound": "invalid_bool",
            "sound_theme": "non_existent_theme",
            "safety_fuse_enabled": None,
            "generation": -5,
        }
        cleaned = validate_config(bad_config)
        self.assertEqual(cleaned["buffer_delay"], 1.0)
        self.assertEqual(cleaned["sound_theme"], "codex-notification")
        self.assertTrue(cleaned["safety_fuse_enabled"])
        self.assertEqual(cleaned["generation"], 1)

    def test_t10_partial_update_preserves_other_fields(self):
        """T10: 增量修改不丢失其他字段"""
        orig = load_config()
        update_config({"buffer_delay": 1.5})
        latest = load_config()
        self.assertEqual(latest["buffer_delay"], 1.5)
        self.assertEqual(latest["dangerous_patterns"], orig["dangerous_patterns"])
        self.assertEqual(latest["desktop_targets"], orig["desktop_targets"])
        # 恢复默认
        update_config({"buffer_delay": 1.0})

    def test_t10_generation_advancement(self):
        """测试代次递增功能"""
        gen1 = advance_generation()
        gen2 = advance_generation()
        self.assertGreater(gen2, gen1)

    def test_update_config_failure_returns_none(self):
        """配置保存失败时 update_config 必须返回 None，不能伪装为成功"""
        from unittest.mock import patch
        with patch("src.config.save_config", return_value=False):
            res = update_config({"buffer_delay": 9.9})
            self.assertIsNone(res)

    def test_advance_generation_failure_returns_minus_one(self):
        """配置保存失败时 advance_generation 必须返回 -1"""
        from unittest.mock import patch
        with patch("src.config.save_config", return_value=False):
            gen = advance_generation()
            self.assertEqual(gen, -1)

    def test_save_config_io_error_handling(self):
        """文件替换异常时 save_config 捕获并返回 False"""
        from unittest.mock import patch
        with patch("os.replace", side_effect=OSError("Disk full")):
            success = save_config(DEFAULT_CONFIG)
            self.assertFalse(success)


if __name__ == "__main__":
    unittest.main()
