"""
AntiEnter 音效模块测试 (涵盖 T15, T16)
"""
import unittest
from unittest.mock import patch
import sys
from pathlib import Path

_current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_current_dir.parent))

from src.sound import resolve_sound_asset, play_cue_async


class TestSound(unittest.TestCase):
    def test_t15_sound_asset_exists(self):
        """T15: 默认 codex-notification 音效资产在工程中存在并能被解析"""
        path = resolve_sound_asset("codex-notification")
        self.assertIsNotNone(path, "codex-notification.wav 应当能被解析")
        self.assertTrue(Path(path).is_file(), f"音效文件必须存在: {path}")

    @patch("src.sound.load_config")
    @patch("subprocess.run")
    def test_t16_muted_sound_zero_calls(self, mock_run, mock_config):
        """T16: 关闭声音时零播放器调用"""
        mock_config.return_value = {"play_sound": False}
        play_cue_async()
        # 由于是异步线程，稍微等待片刻以确保线程执行完成
        import time
        time.sleep(0.05)
        mock_run.assert_not_called()

    def test_t16_unsupported_theme_returns_none(self):
        """未知主题返回 None 并回退系统音"""
        path = resolve_sound_asset("unknown_theme")
        self.assertIsNone(path)


if __name__ == "__main__":
    unittest.main()
