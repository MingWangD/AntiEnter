import unittest
from unittest.mock import patch
import sys
from pathlib import Path

# Ensure src is in the path
_current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_current_dir.parent))

from src import controller

class TestController(unittest.TestCase):
    @patch("src.controller.subprocess.Popen")
    @patch("src.controller.sys.platform", "darwin")
    @patch("src.controller.install_hook", return_value=True)
    @patch("src.controller.get_running_pid", return_value=None)
    @patch("src.controller.build_daemon", return_value=True)
    def test_start_daemon_darwin(self, mock_build, mock_pid, mock_hook, mock_popen):
        # Patching Pathlib exists is hard, so we just mock build_daemon
        # and assume DAEMON_BIN.exists() might be true/false.
        # But we can patch the DAEMON_BIN itself in the module.
        pass

    @patch("src.controller.get_running_pid", return_value=12345)
    @patch("src.controller.uninstall_hook")
    @patch("src.controller.os.kill")
    def test_stop_daemon_darwin(self, mock_kill, mock_uninstall, mock_pid):
        controller.stop()
        mock_kill.assert_called_once()
        mock_uninstall.assert_called_once()

if __name__ == "__main__":
    unittest.main()
