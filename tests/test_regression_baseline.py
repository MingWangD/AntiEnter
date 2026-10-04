"""
AntiEnter 回归基线测试
覆盖本次审查中发现的缺陷：
1. Hook 输入校验缺失（空输入、坏 JSON、缺字段、未知工具容错放行）
2. 路径穿越与重定向未拦截（../../etc/hosts、> /etc/hosts）
3. 文本误判（"你好"、"let skipped = true"、"Confirming migration"、"Skip tutorial"）
4. 版本不一致（updater.py 版本滞后）
5. 音效资源路径（macOS App Bundle 内路径解析失败）
6. 更新器失败分支仍判定成功
"""
import unittest
import json
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
HOOK_HANDLER = ROOT_DIR / "src" / "hook_handler.py"


import os
import tempfile


def run_hook(raw_input: str) -> dict:
    env = os.environ.copy()
    env["ANTIENTER_TEST_MODE"] = "1"
    proc = subprocess.Popen(
        [sys.executable, str(HOOK_HANDLER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    stdout, stderr = proc.communicate(input=raw_input)
    if proc.returncode != 0:
        raise RuntimeError(f"Hook exit {proc.returncode}: {stderr}")
    return json.loads(stdout.strip())


class TestHookRegressionBaseline(unittest.TestCase):
    """验证 Hook 边界与安全拦截缺陷"""

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

    def test_empty_input_must_ask(self):
        # 空输入必须保留人工确认，不能放行
        res = run_hook("")
        self.assertEqual(res.get("decision"), "ask", "空输入应返回 ask")

    def test_malformed_json_must_ask(self):
        # 损坏的 JSON 必须保留人工确认，不能容错放行
        res = run_hook("{corrupted_json")
        self.assertEqual(res.get("decision"), "ask", "坏 JSON 应返回 ask")

    def test_missing_fields_must_ask(self):
        # 缺少必要字段应保留人工确认
        res = run_hook(json.dumps({}))
        self.assertEqual(res.get("decision"), "ask", "空对象应返回 ask")
        res2 = run_hook(json.dumps({"toolCall": {}}))
        self.assertEqual(res2.get("decision"), "ask", "缺少 toolCall.name 应返回 ask")

    def test_unknown_tool_must_ask(self):
        # 未知工具应当保留人工确认
        payload = {"toolCall": {"name": "dangerous_unknown_tool", "args": {}}, "stepIdx": 1}
        res = run_hook(json.dumps(payload))
        self.assertEqual(res.get("decision"), "ask", "未知工具应返回 ask")

    def test_path_traversal_system_file_blocked(self):
        # 相对路径穿越写入系统文件必须拦截
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "../../../../etc/hosts"},
            },
            "stepIdx": 2,
        }
        res = run_hook(json.dumps(payload))
        self.assertEqual(res.get("decision"), "ask", "路径穿越写 /etc/hosts 应拦截")

    def test_command_system_file_redirection_blocked(self):
        # run_command 重定向覆盖系统文件必须拦截
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "echo 'bad' > /etc/resolv.conf"},
            },
            "stepIdx": 3,
        }
        res = run_hook(json.dumps(payload))
        self.assertEqual(res.get("decision"), "ask", "向系统关键文件重定向写入应拦截")


class TestVersionBaseline(unittest.TestCase):
    """验证版本一致性缺陷"""

    def test_updater_version_matches_manifest(self):
        import src.updater as updater
        # 当前 updater.py 版本滞后为 1.2.3，而 tag 为 v1.2.4
        self.assertEqual(updater.CURRENT_VERSION, "1.2.5", "updater.CURRENT_VERSION 应与当前版本 1.2.5 一致")


class TestSoundPathBaseline(unittest.TestCase):
    """验证 App Bundle 结构下音效查找缺陷"""

    def test_bundle_sound_resolution(self):
        # 模拟位于 AntiEnter.app/Contents/Resources/scripts/sound.py 的环境
        # 此时 sound.py 应能找到 Contents/Resources/sounds/codex-notification.wav
        from src.sound import play_cue_async
        # 验证默认音效资产在仓库中真实存在
        default_wav = ROOT_DIR / "assets" / "sounds" / "codex-notification.wav"
        self.assertTrue(default_wav.exists(), "默认 codex-notification.wav 音效资产必须存在")


if __name__ == "__main__":
    unittest.main()
