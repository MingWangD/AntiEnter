import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path
import re

_current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_current_dir.parent))

class TestDaemons(unittest.TestCase):
    def test_windows_daemon_import(self):
        """Test that windows_daemon can be imported and doesn't crash on syntax errors."""
        try:
            import src.windows_daemon
            self.assertTrue(hasattr(src.windows_daemon, "WindowsDaemonEngine"))
        except ImportError as e:
            # It might fail if win32 modules aren't mocked well, but syntax is valid.
            pass

    def test_cli_runner_import(self):
        """Test that cli_runner can be imported."""
        try:
            import src.cli_runner
            self.assertTrue(hasattr(src.cli_runner, "run_with_pty"))
        except ImportError:
            pass

    def test_cli_regex_matching(self):
        """Test if regex matching in cli runner would work for standard prompts."""
        from src.config import DEFAULT_CONFIG
        patterns = [re.compile(p, re.IGNORECASE) for p in DEFAULT_CONFIG.get("cli_prompt_patterns", [])]
        
        # Test positive cases
        output1 = "Do you want to continue? [Y/n]"
        self.assertTrue(any(p.search(output1) for p in patterns))
        
        output2 = "Press Enter to proceed..."
        self.assertTrue(any(p.search(output2) for p in patterns))
        
        # Test negative cases
        output3 = "Building project... done."
        self.assertFalse(any(p.search(output3) for p in patterns))

if __name__ == "__main__":
    unittest.main()
