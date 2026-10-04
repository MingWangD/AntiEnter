"""
AntiEnter 控制器与进程实例测试 (涵盖 T08, T09, T11)
"""
import unittest
from unittest.mock import patch, MagicMock
import os
import sys
import tempfile
from pathlib import Path

_current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_current_dir.parent))

from src import controller
from src.config import (
    register_instance,
    unregister_instance,
    get_active_instance,
    is_pid_alive,
    advance_generation,
    load_config,
    save_config,
    DEFAULT_CONFIG,
)


class TestController(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ["ANTIENTER_CONFIG_DIR"] = cls.temp_dir.name
        save_config(DEFAULT_CONFIG)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()
        os.environ.pop("ANTIENTER_CONFIG_DIR", None)

    def setUp(self):
        save_config(DEFAULT_CONFIG)
        unregister_instance()

    def tearDown(self):
        unregister_instance()

    def test_t09_single_instance_registration(self):
        """T09: 单一实例登记，防止重复启动，支持追踪与停止"""
        current_pid = os.getpid()
        ok1 = register_instance(current_pid, "daemon")
        self.assertTrue(ok1, "初次登记应成功")

        inst = get_active_instance()
        self.assertIsNotNone(inst)
        self.assertEqual(inst["pid"], current_pid)
        self.assertEqual(inst["entry"], "daemon")

        # 尝试登记第二个不同 PID
        ok2 = register_instance(999999, "app")
        self.assertFalse(ok2, "已有活跃实例时不得登记副本")

        unregister_instance(current_pid)
        self.assertIsNone(get_active_instance(), "注销后应当无活跃实例")

    def test_t08_task_cancellation_advances_generation(self):
        """T08: 停止或暂停时递增代次，使排队动作全部失效"""
        gen_before = load_config().get("generation", 1)
        controller.stop()
        gen_after = load_config().get("generation", 1)
        self.assertGreater(gen_after, gen_before, "stop() 必须递增 generation 使旧动作作废")

    @patch("src.controller.subprocess.Popen")
    @patch("src.controller.install_hook", return_value=True)
    def test_start_daemon_success(self, mock_hook, mock_popen):
        """真实断言 start() 流程正确触发 Popen 并返回状态"""
        mock_proc = MagicMock()
        mock_proc.pid = 54321
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        with patch("src.controller.is_pid_alive", return_value=True):
            with patch.object(Path, "exists", return_value=True):
                res = controller.start(foreground=False)
                self.assertTrue(res)
                mock_hook.assert_called_once()
                mock_popen.assert_called_once()

    def test_t11_is_pid_alive_detection(self):
        """T11: 进程存活探测逻辑测试 (自身存活，非法 PID 死亡)"""
        # 当前进程必然存活
        self.assertTrue(is_pid_alive(os.getpid()))
        # PID <= 0 必然死亡
        self.assertFalse(is_pid_alive(-1))
        self.assertFalse(is_pid_alive(0))
        # 极高无效 PID 应当判断为死亡
        self.assertFalse(is_pid_alive(99999999))

    def test_start_fails_when_update_config_fails(self):
        """update_config 失败时 start() 应当中止并返回 False"""
        with patch("src.controller.update_config", return_value=None):
            res = controller.start()
            self.assertFalse(res)

    @patch("src.controller.subprocess.Popen")
    @patch("src.controller.install_hook", return_value=True)
    def test_foreground_start_fails_on_nonzero_exit(self, mock_hook, mock_popen):
        """守护进程异常退出 (非零码) 时 start(foreground=True) 必须返回 False"""
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.wait.return_value = 1  # 模拟崩溃退出
        mock_popen.return_value = mock_proc

        with patch.object(Path, "exists", return_value=True):
            res = controller.start(foreground=True)
            self.assertFalse(res, "进程非零退出时前台启动必须返回 False")

    def test_start_fails_when_advance_generation_fails(self):
        """advance_generation 失败时 start() 应当中止并返回 False"""
        with patch("src.controller.advance_generation", return_value=-1):
            res = controller.start()
            self.assertFalse(res, "递增代次失败时 start() 必须返回 False")

    def test_stop_reports_failure_when_advance_generation_fails(self):
        """advance_generation 失败时 stop() 必须返回 False"""
        with patch("src.controller.advance_generation", return_value=-1):
            res = controller.stop()
            self.assertFalse(res, "递增代次失败时 stop() 必须报告失败")

    def test_stop_reports_failure_when_os_kill_raises_error(self):
        """终止进程发生 OSError 时 stop() 必须捕获异常并返回 False"""
        with patch("src.controller.get_active_instance", return_value={"pid": 12345, "entry": "daemon"}):
            with patch("os.kill", side_effect=PermissionError("Operation not permitted")):
                with patch("src.controller.is_pid_alive", return_value=True):
                    res = controller.stop()
                    self.assertFalse(res, "终止进程遇到权限异常时 stop() 必须返回 False")

    def test_stop_reports_failure_when_process_remains_alive(self):
        """SIGKILL 后进程依然存活，stop() 必须返回 False"""
        with patch("src.controller.get_active_instance", return_value={"pid": 12345, "entry": "daemon"}):
            with patch("os.kill"):
                with patch("src.controller.is_pid_alive", return_value=True):
                    res = controller.stop()
                    self.assertFalse(res, "进程强杀后仍存活时 stop() 必须返回 False")


if __name__ == "__main__":
    unittest.main()
