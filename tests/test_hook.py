"""
AntiEnter 自动化测试模块 (unittest)
覆盖普通指令放行测试、高危指令安全熔断测试、敏感路径拦截测试与参数严格校验测试。
"""
import sys
import os
import json
import unittest
import subprocess
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
HOOK_HANDLER = ROOT_DIR / "src" / "hook_handler.py"


def run_handler_with_payload(payload: dict, test_mode: bool = True) -> dict:
    """向 hook_handler.py 管道输入 payload 并返回解析后的 JSON 输出"""
    env = os.environ.copy()
    if test_mode:
        env["ANTIENTER_TEST_MODE"] = "1"
    else:
        env.pop("ANTIENTER_TEST_MODE", None)

    process = subprocess.Popen(
        [sys.executable, str(HOOK_HANDLER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    stdout, stderr = process.communicate(input=json.dumps(payload))
    if process.returncode != 0:
        raise RuntimeError(f"Hook 处理程序异常退出: {stderr}")
    return json.loads(stdout.strip())


class TestHookSecurity(unittest.TestCase):
    """涵盖 T01, T02, T06, T07 测试场景及参数 Schema 严格校验"""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ["ANTIENTER_CONFIG_DIR"] = cls.temp_dir.name
        from src.config import save_config, DEFAULT_CONFIG
        cfg = DEFAULT_CONFIG.copy()
        cfg["enabled"] = True
        save_config(cfg)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()
        os.environ.pop("ANTIENTER_CONFIG_DIR", None)

    def setUp(self):
        from src.config import update_config
        update_config({"enabled": True})

    def test_safe_command_allowed(self):
        """测试常规安全指令在 AntiEnter 运行态下自动放行"""
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "git status"},
            },
            "stepIdx": 1,
        }
        result = run_handler_with_payload(payload)
        self.assertEqual(result.get("decision"), "allow", f"安全指令应当放行，实际输出: {result}")

    def test_dangerous_command_blocked(self):
        """测试极端高危指令被安全熔断拦截 (保留人工确认)"""
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "sudo rm -rf /"},
            },
            "stepIdx": 2,
        }
        result = run_handler_with_payload(payload)
        self.assertEqual(result.get("decision"), "ask", f"高危指令应当保留人工确认，实际输出: {result}")

    def test_forkbomb_blocked(self):
        """测试 Fork Bomb 等特殊危险模式拦截"""
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": ":(){ :|:& };:"},
            },
            "stepIdx": 3,
        }
        result = run_handler_with_payload(payload)
        self.assertEqual(result.get("decision"), "ask", f"Fork bomb 应当保留人工确认，实际输出: {result}")

    def test_safe_file_write_allowed(self):
        """测试常规项目文件写入放行"""
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": str(ROOT_DIR / "test.txt")},
            },
            "stepIdx": 4,
        }
        result = run_handler_with_payload(payload)
        self.assertEqual(result.get("decision"), "allow", f"项目目录文件写入应当放行，实际输出: {result}")

    def test_system_file_write_blocked(self):
        """测试针对系统保护目录的文件写入拦截"""
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "/etc/hosts"},
            },
            "stepIdx": 5,
        }
        result = run_handler_with_payload(payload)
        self.assertEqual(result.get("decision"), "ask", f"系统保护目录写入应当拦截，实际输出: {result}")

    def test_rm_rf_any_directory_blocked(self):
        """测试任意目录的 rm -rf 均被安全熔断拦截"""
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "rm -rf ./build/dist"},
            },
            "stepIdx": 6,
        }
        result = run_handler_with_payload(payload)
        self.assertEqual(result.get("decision"), "ask", f"rm -rf 目录应当保留人工确认，实际输出: {result}")

    def test_rm_file_blocked(self):
        """测试单文件删除 rm 同样被安全熔断拦截"""
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "rm important_data.json"},
            },
            "stepIdx": 7,
        }
        result = run_handler_with_payload(payload)
        self.assertEqual(result.get("decision"), "ask", f"rm 文件应当保留人工确认，实际输出: {result}")

    def test_git_push_allowed(self):
        """测试 git push 等非破坏性指令自动放行"""
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "git push -u origin main --tags"},
            },
            "stepIdx": 8,
        }
        result = run_handler_with_payload(payload)
        self.assertEqual(result.get("decision"), "allow", f"git push 应当自动放行，实际输出: {result}")

    def test_windows_del_blocked(self):
        """测试 Windows 原生删除指令 del 均被拦截"""
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "del /f /s /q temp.txt"},
            },
            "stepIdx": 9,
        }
        result = run_handler_with_payload(payload)
        self.assertEqual(result.get("decision"), "ask", f"del 指令应当保留人工确认，实际输出: {result}")

    def test_windows_rd_blocked(self):
        """测试 Windows 原生目录删除 rd /s 均被拦截"""
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "rd /s /q ./dist"},
            },
            "stepIdx": 10,
        }
        result = run_handler_with_payload(payload)
        self.assertEqual(result.get("decision"), "ask", f"rd /s 目录删除应当保留人工确认，实际输出: {result}")

    def test_windows_remove_item_blocked(self):
        """测试 PowerShell Remove-Item 破坏性删除指令被拦截"""
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "Remove-Item -Recurse -Force ./data"},
            },
            "stepIdx": 11,
        }
        result = run_handler_with_payload(payload)
        self.assertEqual(result.get("decision"), "ask", f"Remove-Item 应当保留人工确认，实际输出: {result}")

    def test_windows_system_path_blocked(self):
        """测试 Windows 系统保护目录写操作拦截"""
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "C:\\Windows\\System32\\drivers\\etc\\hosts"},
            },
            "stepIdx": 12,
        }
        result = run_handler_with_payload(payload)
        self.assertEqual(result.get("decision"), "ask", f"Windows 系统保护目录写入应当拦截，实际输出: {result}")

    # ==================== P1-2: 参数 Schema 缺失校验测试 ====================
    def test_schema_run_command_missing_args(self):
        """run_command 缺少 args 或 args 非字典结构必须返回 ask"""
        payload = {
            "toolCall": {
                "name": "run_command",
            }
        }
        result = run_handler_with_payload(payload)
        self.assertEqual(result.get("decision"), "ask", "缺少 args 必须返回 ask")

        payload_none = {
            "toolCall": {
                "name": "run_command",
                "args": None,
            }
        }
        result_none = run_handler_with_payload(payload_none)
        self.assertEqual(result_none.get("decision"), "ask", "args=None 必须返回 ask")

    def test_schema_run_command_empty_commandline(self):
        """run_command 的 CommandLine 缺失或为空必须返回 ask，杜绝 fail-open"""
        payload_empty = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": ""},
            }
        }
        result_empty = run_handler_with_payload(payload_empty)
        self.assertEqual(result_empty.get("decision"), "ask", "CommandLine 为空必须返回 ask")

        payload_spaces = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "   "},
            }
        }
        result_spaces = run_handler_with_payload(payload_spaces)
        self.assertEqual(result_spaces.get("decision"), "ask", "CommandLine 为纯空白必须返回 ask")

        payload_missing = {
            "toolCall": {
                "name": "run_command",
                "args": {},
            }
        }
        result_missing = run_handler_with_payload(payload_missing)
        self.assertEqual(result_missing.get("decision"), "ask", "CommandLine 缺失必须返回 ask")

    def test_schema_write_missing_targetfile(self):
        """write_to_file 的 TargetFile 缺失或为空必须返回 ask"""
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": ""},
            }
        }
        result = run_handler_with_payload(payload)
        self.assertEqual(result.get("decision"), "ask", "TargetFile 为空必须返回 ask")

    def test_when_antienter_quit_hook_forces_ask(self):
        """验证核心安全承诺：当 AntiEnter 进程退出后，Hook 绝对不放行、绝对不发声，强制恢复人工审批"""
        from src.config import unregister_instance
        unregister_instance()

        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "git status"},
            },
            "stepIdx": 99,
        }
        result = run_handler_with_payload(payload, test_mode=False)
        self.assertEqual(result.get("decision"), "ask", "AntiEnter 退出后必须返回 ask，绝不自动放行")
        self.assertIn("客户端已退出", result.get("reason", ""))

    def test_when_enabled_is_false_hook_forces_ask(self):
        """当 AntiEnter 标记为停用状态时，Hook 强制恢复人工审批"""
        from src.config import update_config
        update_config({"enabled": False})
        try:
            payload = {
                "toolCall": {
                    "name": "run_command",
                    "args": {"CommandLine": "git status"},
                },
                "stepIdx": 100,
            }
            result = run_handler_with_payload(payload, test_mode=True)
            self.assertEqual(result.get("decision"), "ask")
            self.assertIn("已停用", result.get("reason", ""))
        finally:
            update_config({"enabled": True})

    def test_namespaced_tool_generates_canonical_token(self):
        """测试带命名空间的工具名 (default_api:run_command) 在决策令牌中同时保存原始名与规范化名"""
        from src.config import get_decision_file, consume_decision_token, get_active_decision_token
        import json

        payload = {
            "toolCall": {
                "name": "default_api:run_command",
                "args": {"CommandLine": "git status"},
            },
            "stepIdx": 101,
        }
        res = run_handler_with_payload(payload, test_mode=True)
        self.assertEqual(res.get("decision"), "allow")

        dec_file = get_decision_file()
        self.assertTrue(dec_file.exists())
        with open(dec_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data.get("decision"), "allow")
        self.assertEqual(data.get("raw_tool"), "default_api:run_command")
        self.assertEqual(data.get("canonical_tool"), "run_command")
        self.assertEqual(data.get("tool"), "run_command")
        self.assertFalse(data.get("consumed"))
        self.assertTrue(bool(data.get("token_id")))

        # 验证 get_active_decision_token 能够通过规范化名称或命名空间名称成功读取
        tok = get_active_decision_token(expected_tool="run_command")
        self.assertIsNotNone(tok)
        tok_ns = get_active_decision_token(expected_tool="default_api:run_command")
        self.assertIsNotNone(tok_ns)
        tok_mismatch = get_active_decision_token(expected_tool="write_to_file")
        self.assertIsNone(tok_mismatch)

        # 验证原子消费
        consumed_ok = consume_decision_token(data.get("token_id"))
        self.assertTrue(consumed_ok)
        self.assertIsNone(get_active_decision_token(expected_tool="run_command"), "消费后令牌不得再次生效")
        self.assertFalse(consume_decision_token(data.get("token_id")), "重复消费必须返回 False")


if __name__ == "__main__":
    unittest.main()
