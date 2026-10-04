"""
AntiEnter 事务更新与回滚测试 (涵盖 T12, T13, T14)
"""
import unittest
import tempfile
import shutil
import zipfile
import sys
from pathlib import Path

_current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_current_dir.parent))

from src.updater import (
    parse_version,
    is_newer,
    verify_app_bundle,
    execute_transactional_mac_update,
    UPDATE_LOCK_FILE,
)


class TestUpdater(unittest.TestCase):
    def setUp(self):
        UPDATE_LOCK_FILE.unlink(missing_ok=True)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_updater_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        UPDATE_LOCK_FILE.unlink(missing_ok=True)

    def test_parse_version(self):
        self.assertEqual(parse_version("1.0.0"), (1, 0, 0))
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("V2.0"), (2, 0))

    def test_is_newer(self):
        self.assertTrue(is_newer("v1.2.1", "1.2.0"))
        self.assertTrue(is_newer("2.0.0", "1.9.9"))
        self.assertFalse(is_newer("1.2.0", "1.2.0"))
        self.assertFalse(is_newer("v1.1.0", "1.2.0"))

    def test_t12_invalid_archive_aborts_without_damaging_target(self):
        """T12: 损坏的归档包中止更新，现有安装完好保留"""
        # 准备假目标 App
        target_app = self.temp_dir / "Target.app"
        target_app.mkdir()
        marker = target_app / "original_file.txt"
        marker.write_text("v1.0.0 content")

        # 损坏的 zip
        bad_zip = self.temp_dir / "bad.zip"
        bad_zip.write_text("not a real zip")

        success = execute_transactional_mac_update(
            target_app=target_app,
            archive_path=bad_zip,
            target_version="1.2.5",
        )
        self.assertFalse(success, "损坏的 zip 必须中止更新并返回 False")
        self.assertTrue(target_app.exists(), "原应用目录必须完整保留")
        self.assertTrue(marker.exists(), "原应用文件不得丢失")

    def test_t12_old_pid_timeout_aborts(self):
        """T12: 旧 PID 持续未退出时安全超时中止"""
        target_app = self.temp_dir / "Target.app"
        target_app.mkdir()
        (target_app / "version.txt").write_text("1.0.0")

        # 制作包含合法 App 结构的有效 zip
        stage = self.temp_dir / "stage" / "AntiEnter.app" / "Contents" / "MacOS"
        stage.mkdir(parents=True)
        (stage / "AntiEnter").write_text("dummy")
        (stage.parent / "Info.plist").write_text("""
        <plist><dict>
        <key>CFBundleIdentifier</key><string>com.antienter.app</string>
        <key>CFBundleShortVersionString</key><string>1.2.5</string>
        </dict></plist>
        """)

        valid_zip = self.temp_dir / "valid.zip"
        with zipfile.ZipFile(valid_zip, "w") as zf:
            for f in (self.temp_dir / "stage").rglob("*"):
                zf.write(f, f.relative_to(self.temp_dir / "stage"))

        import os
        from unittest.mock import patch, MagicMock
        with patch("src.updater.is_pid_alive", return_value=True), patch("time.sleep"):
            success = execute_transactional_mac_update(
                target_app=target_app,
                archive_path=valid_zip,
                old_pid=os.getpid(),
                target_version="1.2.5",
            )
            self.assertFalse(success, "旧进程超时未退出应中止更新")
            self.assertTrue(target_app.exists())

    def test_t12_launch_health_check_failure_triggers_rollback(self):
        """T12: 新版拉起后健康检查失败 (pgrep 未能检测到新 PID)，自动回滚旧版本"""
        target_app = self.temp_dir / "Target.app"
        target_app.mkdir()
        marker = target_app / "old_version_marker.txt"
        marker.write_text("version 1.0.0")

        # 制作包含 1.2.5 的合法归档
        stage = self.temp_dir / "stage2" / "AntiEnter.app" / "Contents" / "MacOS"
        stage.mkdir(parents=True)
        (stage / "AntiEnter").write_text("new_binary")
        (stage.parent / "Info.plist").write_text("""
        <plist><dict>
        <key>CFBundleIdentifier</key><string>com.antienter.app</string>
        <key>CFBundleShortVersionString</key><string>1.2.5</string>
        </dict></plist>
        """)

        valid_zip = self.temp_dir / "valid2.zip"
        with zipfile.ZipFile(valid_zip, "w") as zf:
            for f in (self.temp_dir / "stage2").rglob("*"):
                zf.write(f, f.relative_to(self.temp_dir / "stage2"))

        from unittest.mock import patch, MagicMock
        mock_open = MagicMock(returncode=0, stderr=b"")
        mock_pgrep_fail = MagicMock(returncode=1, stdout=b"")

        def mock_subp_run(cmd, *args, **kwargs):
            if cmd[0] == "/usr/bin/ditto":
                # 解压
                shutil.copytree(str(self.temp_dir / "stage2" / "AntiEnter.app"), str(kwargs.get("args", cmd)[-1] + "/AntiEnter.app"))
                return MagicMock(returncode=0)
            elif cmd[0] == "/usr/bin/open":
                return mock_open
            elif cmd[0] == "/usr/bin/pgrep":
                return mock_pgrep_fail
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_subp_run), patch("time.sleep"):
            success = execute_transactional_mac_update(
                target_app=target_app,
                archive_path=valid_zip,
                old_pid=None,
                target_version="1.2.5",
            )
            self.assertFalse(success, "健康检查失败必须返回 False")
            self.assertTrue(target_app.exists(), "必须回滚恢复目标应用")
            self.assertTrue(marker.exists(), "旧版本文件必须完整恢复")

    def test_t12_successful_health_check_cleans_backup(self):
        """T12: 新版拉起就绪检查通过，更新成功并清理旧备份"""
        target_app = self.temp_dir / "Target.app"
        target_app.mkdir()
        (target_app / "old.txt").write_text("old")

        stage = self.temp_dir / "stage3" / "AntiEnter.app" / "Contents" / "MacOS"
        stage.mkdir(parents=True)
        (stage / "AntiEnter").write_text("new_binary")
        (stage.parent / "Info.plist").write_text("""
        <plist><dict>
        <key>CFBundleIdentifier</key><string>com.antienter.app</string>
        <key>CFBundleShortVersionString</key><string>1.2.5</string>
        </dict></plist>
        """)

        valid_zip = self.temp_dir / "valid3.zip"
        with zipfile.ZipFile(valid_zip, "w") as zf:
            for f in (self.temp_dir / "stage3").rglob("*"):
                zf.write(f, f.relative_to(self.temp_dir / "stage3"))

        from unittest.mock import patch, MagicMock
        mock_open = MagicMock(returncode=0, stderr=b"")
        mock_pgrep_ok = MagicMock(returncode=0, stdout=b"99887\n")

        def mock_subp_run(cmd, *args, **kwargs):
            if cmd[0] == "/usr/bin/ditto":
                dest = cmd[-1]
                shutil.copytree(str(self.temp_dir / "stage3" / "AntiEnter.app"), f"{dest}/AntiEnter.app")
                return MagicMock(returncode=0)
            elif cmd[0] == "/usr/bin/open":
                return mock_open
            elif cmd[0] == "/usr/bin/pgrep":
                return mock_pgrep_ok
            elif cmd[0] == "/bin/ps":
                return MagicMock(returncode=0, stdout=b"AntiEnter\n")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_subp_run), patch("time.sleep"):
            success = execute_transactional_mac_update(
                target_app=target_app,
                archive_path=valid_zip,
                old_pid=None,
                target_version="1.2.5",
            )
            self.assertTrue(success, "健康检查通过必须返回 True")
            self.assertTrue(target_app.exists())
            # 确认没有遗留 backup 目录
            backups = list(self.temp_dir.glob("Target.app.backup_*"))
            self.assertEqual(len(backups), 0, "成功更新后必须清除临时备份")

    def test_t14_concurrent_update_blocked_by_lock(self):
        """T14: 存在更新锁时阻止并发更新"""
        UPDATE_LOCK_FILE.write_text("99999")
        success = execute_transactional_mac_update(
            target_app=self.temp_dir / "Target.app",
            archive_path=self.temp_dir / "any.zip",
        )
        self.assertFalse(success, "更新中必须拒绝并发重复更新")

    def test_verify_app_bundle_version_mismatch(self):
        """Bundle 版本与预期不匹配时校验失败"""
        app_dir = self.temp_dir / "Test.app"
        (app_dir / "Contents" / "MacOS").mkdir(parents=True)
        (app_dir / "Contents" / "MacOS" / "AntiEnter").write_text("bin")
        (app_dir / "Contents" / "Info.plist").write_text("""
        <plist><dict>
        <key>CFBundleIdentifier</key><string>com.antienter.app</string>
        <key>CFBundleShortVersionString</key><string>1.2.0</string>
        </dict></plist>
        """)
        self.assertTrue(verify_app_bundle(app_dir, expected_version="1.2.0"))
        self.assertFalse(verify_app_bundle(app_dir, expected_version="1.2.5"))


if __name__ == "__main__":
    unittest.main()
