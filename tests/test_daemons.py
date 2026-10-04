"""
AntiEnter 守护进程与 CLI 运行器测试 (涵盖 T18)
"""
import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path
import re

_current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_current_dir.parent))


class TestDaemons(unittest.TestCase):
    def test_windows_daemon_import(self):
        """测试 windows_daemon 跨平台安全导入，语法与结构完好"""
        import src.windows_daemon as wd
        self.assertTrue(hasattr(wd, "WindowsDaemonEngine"))
        self.assertTrue(hasattr(wd, "has_confirm_dialog_windows"))

    def test_cli_runner_import(self):
        """测试 cli_runner 延迟导入在所有平台均可安全导入"""
        import src.cli_runner as cr
        self.assertTrue(hasattr(cr, "run_with_pty"))

    def test_t18_windows_wrap_unsupported(self):
        """T18: Windows 平台调用 wrap 返回明确说明与非零退出码"""
        with patch("sys.platform", "win32"):
            import src.cli_runner as cr
            code = cr.run_with_pty(["echo", "hello"])
            self.assertEqual(code, 1, "Windows wrap 必须返回非零状态码 1")

    def test_cli_regex_matching(self):
        """测试 CLI 提示正则匹配准确性"""
        from src.config import DEFAULT_CONFIG
        patterns = [re.compile(p, re.IGNORECASE) for p in DEFAULT_CONFIG.get("cli_prompt_patterns", [])]

        # 正向样本
        self.assertTrue(any(p.search("Do you want to continue? [Y/n]") for p in patterns))
        self.assertTrue(any(p.search("Press Enter to proceed...") for p in patterns))
        self.assertTrue(any(p.search("Are you sure? [y/N]") for p in patterns))

        # 反向样本
        self.assertFalse(any(p.search("Building project... done.") for p in patterns))
        self.assertFalse(any(p.search("Compilation succeeded.") for p in patterns))


    def test_windows_daemon_control_filtering(self):
        """测试 Windows 守护进程排除 Static、Edit、GroupBox 等非按钮控件，仅匹配 Button，且支持熔断扫描"""
        import src.windows_daemon as wd
        from unittest.mock import MagicMock

        # 1. 模拟 Static 控件文本为 "Confirm"
        mock_u32_static = MagicMock()
        mock_u32_static.IsWindowVisible.return_value = True
        mock_u32_static.IsWindowEnabled.return_value = True
        mock_u32_static.GetWindowLongW.return_value = 0
        def fake_enum_static(hwnd, callback, lparam):
            callback(101, lparam)
            return True
        mock_u32_static.EnumChildWindows.side_effect = fake_enum_static
        def fake_get_class(hwnd, buf, size):
            buf.value = "Static"
            return len("Static")
        def fake_get_text(hwnd, buf, size):
            buf.value = "Confirm"
            return len("Confirm")
        mock_u32_static.GetClassNameW.side_effect = fake_get_class
        mock_u32_static.GetWindowTextLengthW.return_value = 7
        mock_u32_static.GetWindowTextW.side_effect = fake_get_text

        res1 = wd.has_confirm_dialog_windows(1234, {"safety_fuse_enabled": False}, _user32=mock_u32_static)
        self.assertFalse(res1, "Static 控件即使包含 'Confirm' 也绝不能作为确认按钮触发")

        # 2. 模拟真实 Button 控件文本为 "Confirm"
        mock_u32_btn = MagicMock()
        mock_u32_btn.IsWindowVisible.return_value = True
        mock_u32_btn.IsWindowEnabled.return_value = True
        mock_u32_btn.GetWindowLongW.return_value = 0
        def fake_enum_button(hwnd, callback, lparam):
            callback(102, lparam)
            return True
        mock_u32_btn.EnumChildWindows.side_effect = fake_enum_button
        def fake_btn_class(hwnd, buf, size):
            buf.value = "Button"
            return len("Button")
        def fake_btn_text(hwnd, buf, size):
            buf.value = "Confirm"
            return len("Confirm")
        mock_u32_btn.GetClassNameW.side_effect = fake_btn_class
        mock_u32_btn.GetWindowTextLengthW.return_value = 7
        mock_u32_btn.GetWindowTextW.side_effect = fake_btn_text

        res2 = wd.has_confirm_dialog_windows(1234, {"safety_fuse_enabled": False}, _user32=mock_u32_btn)
        self.assertTrue(res2, "Button 控件且文本为 'Confirm' 应当成功匹配")

        # 3. 模拟熔断开启下，窗口包含高危指令 ("rm -rf /")，即使有 Button 也必须拦截
        mock_u32_danger = MagicMock()
        mock_u32_danger.IsWindowVisible.return_value = True
        mock_u32_danger.IsWindowEnabled.return_value = True
        mock_u32_danger.GetWindowLongW.return_value = 0
        def fake_enum_danger(hwnd, callback, lparam):
            callback(103, lparam)
            return True
        mock_u32_danger.EnumChildWindows.side_effect = fake_enum_danger
        def fake_danger_text(hwnd, buf, size):
            buf.value = "rm -rf /important_dir"
            return len(buf.value)
        mock_u32_danger.GetClassNameW.side_effect = fake_btn_class
        mock_u32_danger.GetWindowTextLengthW.return_value = 20
        mock_u32_danger.GetWindowTextW.side_effect = fake_danger_text

        res3 = wd.has_confirm_dialog_windows(1234, {"safety_fuse_enabled": True}, _user32=mock_u32_danger)
        self.assertFalse(res3, "熔断开启且窗口包含高危指令时必须拒绝自动确认")

    def test_windows_daemon_token_authorization_matrix(self):
        """测试 Windows 守护进程在熔断开启下针对 Hook 决策令牌的严格授权矩阵"""
        import src.windows_daemon as wd
        import tempfile
        import json
        import time
        import os

        mock_u32_btn = MagicMock()
        mock_u32_btn.IsWindowVisible.return_value = True
        mock_u32_btn.IsWindowEnabled.return_value = True
        mock_u32_btn.GetWindowLongW.return_value = 0
        def fake_enum_button(hwnd, callback, lparam):
            callback(102, lparam)
            return True
        mock_u32_btn.EnumChildWindows.side_effect = fake_enum_button
        def fake_btn_class(hwnd, buf, size):
            buf.value = "Button"
            return len("Button")
        def fake_btn_text(hwnd, buf, size):
            buf.value = "Confirm"
            return len("Confirm")
        mock_u32_btn.GetClassNameW.side_effect = fake_btn_class
        mock_u32_btn.GetWindowTextLengthW.return_value = 7
        mock_u32_btn.GetWindowTextW.side_effect = fake_btn_text

        with tempfile.TemporaryDirectory() as td:
            old_env = os.environ.get("ANTIENTER_CONFIG_DIR")
            os.environ["ANTIENTER_CONFIG_DIR"] = td
            try:
                dec_file = Path(td) / "antienter_decision.json"

                # 1. 无决策文件：熔断开启下 bare Confirm 必须拒绝
                res_no_token = wd.has_confirm_dialog_windows(1234, {"safety_fuse_enabled": True}, _user32=mock_u32_btn)
                self.assertFalse(res_no_token, "无令牌时熔断开启下必须拦截 Confirm")

                # 2. 有效 allow 令牌（未过期、工具匹配）：熔断开启下允许 Confirm
                now = time.time()
                with open(dec_file, "w", encoding="utf-8") as f:
                    json.dump({"decision": "allow", "tool": "run_command", "timestamp": now}, f)
                res_valid_token = wd.has_confirm_dialog_windows(
                    1234, {"safety_fuse_enabled": True}, _user32=mock_u32_btn, expected_tool="run_command"
                )
                self.assertTrue(res_valid_token, "持有有效令牌时必须放行 Confirm")

                # 3. 过期 allow 令牌 (>10s)：必须拦截
                with open(dec_file, "w", encoding="utf-8") as f:
                    json.dump({"decision": "allow", "tool": "run_command", "timestamp": now - 15.0}, f)
                res_expired = wd.has_confirm_dialog_windows(
                    1234, {"safety_fuse_enabled": True}, _user32=mock_u32_btn, expected_tool="run_command"
                )
                self.assertFalse(res_expired, "过期令牌必须拒绝 Confirm")

                # 4. 活跃 ask 决策 (30s 内)：必须拦截
                with open(dec_file, "w", encoding="utf-8") as f:
                    json.dump({"decision": "ask", "tool": "run_command", "timestamp": now - 2.0}, f)
                res_ask = wd.has_confirm_dialog_windows(
                    1234, {"safety_fuse_enabled": True}, _user32=mock_u32_btn, expected_tool="run_command"
                )
                self.assertFalse(res_ask, "ask 状态必须拦截 Confirm")

                # 5. 工具不匹配：必须拦截
                with open(dec_file, "w", encoding="utf-8") as f:
                    json.dump({"decision": "allow", "tool": "run_command", "timestamp": now}, f)
                res_mismatch = wd.has_confirm_dialog_windows(
                    1234, {"safety_fuse_enabled": True}, _user32=mock_u32_btn, expected_tool="write_to_file"
                )
                self.assertFalse(res_mismatch, "工具不匹配时必须拦截 Confirm")

                # 6. 已消费令牌 (consumed=True)：必须拦截防重放
                with open(dec_file, "w", encoding="utf-8") as f:
                    json.dump({"decision": "allow", "tool": "run_command", "timestamp": now, "consumed": True}, f)
                res_consumed = wd.has_confirm_dialog_windows(
                    1234, {"safety_fuse_enabled": True}, _user32=mock_u32_btn, expected_tool="run_command"
                )
                self.assertFalse(res_consumed, "已消费的令牌必须拦截")

                # 7. 缺少 tool 字段：必须拦截
                with open(dec_file, "w", encoding="utf-8") as f:
                    json.dump({"decision": "allow", "timestamp": now}, f)
                res_no_tool = wd.has_confirm_dialog_windows(
                    1234, {"safety_fuse_enabled": True}, _user32=mock_u32_btn, expected_tool="run_command"
                )
                self.assertFalse(res_no_tool, "缺少 tool 字段必须拦截")

                # 8. tool 为 null：必须拦截
                with open(dec_file, "w", encoding="utf-8") as f:
                    json.dump({"decision": "allow", "tool": None, "timestamp": now}, f)
                res_null_tool = wd.has_confirm_dialog_windows(
                    1234, {"safety_fuse_enabled": True}, _user32=mock_u32_btn, expected_tool="run_command"
                )
                self.assertFalse(res_null_tool, "tool 为 null 必须拦截")

                # 9. tool 命名空间规范化匹配：default_api:run_command 匹配 run_command
                with open(dec_file, "w", encoding="utf-8") as f:
                    json.dump({"decision": "allow", "tool": "default_api:run_command", "timestamp": now}, f)
                res_ns = wd.has_confirm_dialog_windows(
                    1234, {"safety_fuse_enabled": True}, _user32=mock_u32_btn, expected_tool="run_command"
                )
                self.assertTrue(res_ns, "命名空间工具名规范化后必须成功匹配")

                # 10. Submit ↵ 在熔断开启下无令牌被拦截，持令牌被放行
                mock_u32_submit = MagicMock()
                mock_u32_submit.IsWindowVisible.return_value = True
                mock_u32_submit.IsWindowEnabled.return_value = True
                mock_u32_submit.GetWindowLongW.return_value = 0
                mock_u32_submit.EnumChildWindows.side_effect = fake_enum_button
                mock_u32_submit.GetClassNameW.side_effect = fake_btn_class
                mock_u32_submit.GetWindowTextLengthW.return_value = 8
                def fake_sub_text(hwnd, buf, size):
                    buf.value = "Submit ↵"
                    return len("Submit ↵")
                mock_u32_submit.GetWindowTextW.side_effect = fake_sub_text

                # 移除令牌：Submit ↵ 必须被拦截
                dec_file.unlink(missing_ok=True)
                res_sub_notoken = wd.has_confirm_dialog_windows(
                    1234, {"safety_fuse_enabled": True}, _user32=mock_u32_submit, expected_tool="run_command"
                )
                self.assertFalse(res_sub_notoken, "熔断开启且无令牌时 Submit ↵ 必须被拦截")

                # 写入有效令牌：Submit ↵ 必须放行
                with open(dec_file, "w", encoding="utf-8") as f:
                    json.dump({"decision": "allow", "tool": "run_command", "timestamp": now}, f)
                res_sub_token = wd.has_confirm_dialog_windows(
                    1234, {"safety_fuse_enabled": True}, _user32=mock_u32_submit, expected_tool="run_command"
                )
                self.assertTrue(res_sub_token, "持有效令牌时 Submit ↵ 应当放行")
            finally:
                if old_env is not None:
                    os.environ["ANTIENTER_CONFIG_DIR"] = old_env
                else:
                    os.environ.pop("ANTIENTER_CONFIG_DIR", None)

    def test_windows_daemon_engine_run_end_to_end_rejects_mismatch_and_consumes_token(self):
        """测试 WindowsDaemonEngine 端到端执行：自动识别窗口工具名、工具不匹配拦截、成功确认并原子消费令牌"""
        import src.windows_daemon as wd
        import tempfile
        import json
        import time
        import os

        # 构造一个窗口：标题为 "Antigravity"，包含 Static 文本 "Command: run_command"，以及 Button "Confirm"
        mock_u32 = MagicMock()
        mock_u32.IsWindowVisible.return_value = True
        mock_u32.IsWindowEnabled.return_value = True
        mock_u32.GetWindowLongW.return_value = 0

        # 枚举子窗口返回两个控件：101 (Static: TargetFile: foo.txt -> write_to_file), 102 (Button: Confirm)
        def fake_enum(hwnd, callback, lparam):
            callback(101, lparam)
            callback(102, lparam)
            return True
        mock_u32.EnumChildWindows.side_effect = fake_enum

        def fake_class(hwnd, buf, size):
            if hwnd == 101:
                buf.value = "Static"
            else:
                buf.value = "Button"
            return len(buf.value)
        mock_u32.GetClassNameW.side_effect = fake_class

        def fake_text_len(hwnd):
            return 25 if hwnd == 101 else 7
        mock_u32.GetWindowTextLengthW.side_effect = fake_text_len

        def fake_text(hwnd, buf, size):
            if hwnd == 101:
                buf.value = "TargetFile: /tmp/code.py"
            else:
                buf.value = "Confirm"
            return len(buf.value)
        mock_u32.GetWindowTextW.side_effect = fake_text

        with tempfile.TemporaryDirectory() as td:
            old_env = os.environ.get("ANTIENTER_CONFIG_DIR")
            os.environ["ANTIENTER_CONFIG_DIR"] = td
            try:
                dec_file = Path(td) / "antienter_decision.json"
                now = time.time()

                daemon = wd.WindowsDaemonEngine()
                daemon.cooldown = 0
                cfg = {
                    "enabled": True,
                    "buffer_delay": 0,
                    "play_sound": False,
                    "safety_fuse_enabled": True,
                    "desktop_targets": ["Antigravity"],
                    "terminal_targets": [],
                    "generation": 1,
                }

                # 1. 窗口提示 write_to_file，但令牌是 run_command -> 端到端 check_and_trigger 必须拒绝！
                with open(dec_file, "w", encoding="utf-8") as f:
                    json.dump({"decision": "allow", "tool": "run_command", "timestamp": now}, f)

                with patch("src.windows_daemon.send_windows_return") as mock_ret:
                    triggered = daemon.check_and_trigger(1234, "Antigravity - Project", cfg, _user32=mock_u32)
                    self.assertFalse(triggered, "工具不匹配时端到端必须拒绝确认")
                    mock_ret.assert_not_called()

                # 2. 写入匹配 write_to_file 的令牌 -> 端到端 check_and_trigger 必须成功并发送回车！
                with open(dec_file, "w", encoding="utf-8") as f:
                    json.dump({"decision": "allow", "tool": "write_to_file", "timestamp": now}, f)

                with patch("src.windows_daemon.send_windows_return") as mock_ret:
                    triggered2 = daemon.check_and_trigger(1234, "Antigravity - Project", cfg, _user32=mock_u32)
                    self.assertTrue(triggered2, "工具匹配时端到端必须执行确认")
                    mock_ret.assert_called_once()

                # 3. 验证令牌已被原子消费 (consumed=True)
                with open(dec_file, "r", encoding="utf-8") as f:
                    consumed_data = json.load(f)
                self.assertTrue(consumed_data.get("consumed"), "执行确认后必须原子将令牌标记为 consumed=True")

                # 4. 再次尝试触发：由于令牌已消费，端到端必须拒绝重放！
                with patch("src.windows_daemon.send_windows_return") as mock_ret:
                    triggered3 = daemon.check_and_trigger(1234, "Antigravity - Project", cfg, _user32=mock_u32)
                    self.assertFalse(triggered3, "已消费的令牌严禁重复重放确认")
                    mock_ret.assert_not_called()
            finally:
                if old_env is not None:
                    os.environ["ANTIENTER_CONFIG_DIR"] = old_env
                else:
                    os.environ.pop("ANTIENTER_CONFIG_DIR", None)


if __name__ == "__main__":
    unittest.main()
