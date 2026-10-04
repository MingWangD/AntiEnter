from __future__ import annotations
import os
import sys
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

# 同级/上级模块导入
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.config import load_config, save_config, CONFIG_PATH
from src.hook_installer import install_hook, uninstall_hook, is_hook_installed

DAEMON_BIN = ROOT_DIR / "bin" / "antienter-daemon"
SWIFT_SRC = ROOT_DIR / "src" / "swift" / "AntiEnterDaemon.swift"


def build_daemon() -> bool:
    """编译 Swift 守护进程"""
    print("[AntiEnter] 正在编译原生 macOS 守护进程...")
    DAEMON_BIN.parent.mkdir(parents=True, exist_ok=True)
    cache_dir = ROOT_DIR / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "/usr/bin/swiftc",
        "-O",
        "-module-cache-path",
        str(cache_dir),
        str(SWIFT_SRC),
        "-o",
        str(DAEMON_BIN),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        os.chmod(DAEMON_BIN, 0o755)
        print("[AntiEnter] 编译成功！")
        return True
    else:
        print(f"[AntiEnter] 编译失败: {res.stderr}")
        return False


def get_running_pid() -> int | None:
    """获取正在运行的守护进程 PID"""
    config = load_config()
    pid_file = Path(config.get("pid_file"))
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)  # 探测进程是否存活
        return pid
    except (OSError, ValueError):
        # 进程已死亡，清理僵死 PID
        try:
            pid_file.unlink(missing_ok=True)
        except Exception:
            pass
        return None


def start(foreground: bool = False) -> bool:
    """启动 AntiEnter（包括安装 Hook 与启动 UI 守护进程）"""
    config = load_config()
    pid = get_running_pid()
    if pid is not None:
        print(f"[AntiEnter] 守护进程已在运行中 (PID: {pid})。")
        return True

    # 1. 安装/更新 Antigravity 协议层 Hook
    print("[AntiEnter] 1/2 正在配置 Antigravity 全局生命周期 Hook...")
    hook_ok = install_hook()
    if hook_ok:
        print("  ✓ 协议层 PreToolUse Hook 已安装生效（支持桌面端与 CLI 工具零延迟免审批）。")
    else:
        print("  ✗ 协议层 Hook 安装失败，仅依赖 UI 监听。")

    # 2. 检查守护进程二进制
    if not DAEMON_BIN.exists():
        if not build_daemon():
            return False

    # 3. 启动 UI 守护进程
    print("[AntiEnter] 2/2 正在启动 macOS UI 自动回车守护进程...")
    pid_file = Path(config.get("pid_file"))
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    log_file = config.get("log_file")

    if foreground:
        print("[AntiEnter] 前台运行模式，按 Ctrl+C 退出。")
        try:
            subprocess.run([str(DAEMON_BIN)])
        except KeyboardInterrupt:
            stop()
        return True

    with open(log_file, "a", encoding="utf-8") as out:
        proc = subprocess.Popen(
            [str(DAEMON_BIN)],
            stdout=out,
            stderr=out,
            start_new_session=True,
        )

    pid_file.write_text(str(proc.pid))
    time.sleep(0.5)

    if proc.poll() is None:
        print(f"  ✓ UI 自动回车守护进程已启动 (PID: {proc.pid})。")
        print("\n[AntiEnter 状态] 🟢 已全面激活！")
        print(f"  - 模式: 桌面端 + CLI 双端全自动")
        print(f"  - 回车缓冲: {config.get('buffer_delay')} 秒")
        print(f"  - 提示音: {'开启' if config.get('play_sound') else '关闭'}")
        print(f"  - 高危熔断: {'开启' if config.get('safety_fuse_enabled') else '关闭'}")
        print("\n使用 'antienter stop' 可随时停用并恢复手动确认。")
        return True
    else:
        print("  ✗ 守护进程未能持续运行，请查看日志: " + log_file)
        return False


def stop() -> bool:
    """停止 AntiEnter（杀掉守护进程并卸载 Hook）"""
    print("[AntiEnter] 正在停用...")
    pid = get_running_pid()
    if pid is not None:
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"  ✓ 已终止 UI 守护进程 (PID: {pid})。")
        except ProcessLookupError:
            pass
        config = load_config()
        pid_file = Path(config.get("pid_file"))
        pid_file.unlink(missing_ok=True)
    else:
        print("  - UI 守护进程未在运行。")

    uninstall_hook()
    print("  ✓ 已卸载 Antigravity 协议层 Hook。")
    print("[AntiEnter 状态] 🔴 已完全停止，恢复原生人工审批模式。")
    return True


def status():
    """显示当前状态与配置详情"""
    config = load_config()
    pid = get_running_pid()
    hook_active = is_hook_installed()

    print("================ AntiEnter 运行状态 ================")
    if pid is not None and hook_active:
        print("整体状态: 🟢 运行中 (全功能激活)")
    elif pid is not None:
        print("整体状态: 🟡 仅 UI 守护进程运行中 (Hook 未生效)")
    elif hook_active:
        print("整体状态: 🟡 仅协议 Hook 生效中 (UI 守护进程未启动)")
    else:
        print("整体状态: 🔴 未运行 (原生人工确认模式)")

    print(f"守护进程 PID: {pid if pid else '无'}")
    print(f"全局 Hook:    {'已安装' if hook_active else '未安装'}")
    print("---------------- 当前核心配置 ----------------")
    print(f"回车缓冲延时: {config.get('buffer_delay')} 秒")
    print(f"提示音反馈:   {'开启' if config.get('play_sound') else '关闭'}")
    print(f"高危指令熔断: {'开启' if config.get('safety_fuse_enabled') else '关闭'}")
    print(f"受管桌面应用: {', '.join(config.get('desktop_targets', []))}")
    print(f"日志文件路径: {config.get('log_file')}")
    print("====================================================")
