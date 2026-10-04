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

from src.config import (
    load_config,
    save_config,
    update_config,
    advance_generation,
    CONFIG_PATH,
    register_instance,
    unregister_instance,
    get_active_instance,
    is_pid_alive,
)
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


def get_running_pid() -> Optional[int]:
    """获取正在运行的实例 PID（统一实例登记）"""
    inst = get_active_instance()
    if inst:
        return inst.get("pid")
    return None


def start(foreground: bool = False) -> bool:
    """启动 AntiEnter（包括安装 Hook 与启动 UI 守护进程，登记统一单实例）"""
    if not update_config({"enabled": True}):
        sys.stderr.write("[AntiEnter] 错误: 无法持久化启用配置，启动中止。\n")
        return False
    config = load_config()
    active_inst = get_active_instance()
    if active_inst is not None:
        pid = active_inst.get("pid")
        entry = active_inst.get("entry", "unknown")
        print(f"[AntiEnter] 守护进程已在运行中 (PID: {pid}, 入口: {entry})。")
        return True

    # 1. 安装/更新 Antigravity 协议层 Hook
    print("[AntiEnter] 1/2 正在配置 Antigravity 全局生命周期 Hook...")
    hook_ok = install_hook()
    if hook_ok:
        print("  ✓ 协议层 PreToolUse Hook 已安装生效（支持桌面端与 CLI 工具零延迟免审批）。")
    else:
        print("  ✗ 协议层 Hook 安装失败，仅依赖 UI 监听。")

    # 2. 准备守护进程启动命令
    entry_name = "windows" if sys.platform == "win32" else "daemon"
    if sys.platform == "win32":
        daemon_cmd = [sys.executable, str(ROOT_DIR / "src" / "windows_daemon.py")]
    else:
        if not DAEMON_BIN.exists():
            if not build_daemon():
                return False
        daemon_cmd = [str(DAEMON_BIN)]

    # 3. 启动 UI 守护进程
    os_name = "Windows" if sys.platform == "win32" else "macOS"
    print(f"[AntiEnter] 2/2 正在启动 {os_name} UI 自动回车守护进程...")
    log_file = config.get("log_file")

    gen = advance_generation()
    if gen == -1:
        sys.stderr.write("[AntiEnter] 错误: 递增代次失败，启动中止。\n")
        return False

    if foreground:
        print("[AntiEnter] 前台运行模式，按 Ctrl+C 退出。")
        proc = subprocess.Popen(daemon_cmd)
        registered = register_instance(proc.pid, f"{entry_name}-foreground")
        if not registered:
            print("[AntiEnter] 实例登记冲突，已有活跃实例运行中。")
            try:
                proc.terminate()
            except Exception:
                pass
            return False
        returncode = 0
        try:
            returncode = proc.wait()
        except KeyboardInterrupt:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            returncode = 0
        finally:
            unregister_instance(proc.pid)
            stop()
        if returncode != 0:
            sys.stderr.write(f"[AntiEnter] 守护进程非正常退出 (退出码: {returncode})。\n")
            return False
        return True

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    with open(log_file, "a", encoding="utf-8") as out:
        proc = subprocess.Popen(
            daemon_cmd,
            stdout=out,
            stderr=out,
            start_new_session=(sys.platform != "win32"),
            creationflags=creation_flags if sys.platform == "win32" else 0,
        )

    time.sleep(0.5)

    if proc.poll() is None:
        registered = register_instance(proc.pid, entry_name)
        if not registered:
            # 存在并发冲突
            try:
                proc.terminate()
            except Exception:
                pass
            print("  ✗ 实例登记冲突，已终止新启动进程。")
            return False

        print(f"  ✓ UI 自动回车守护进程已启动 (PID: {proc.pid})。")
        print("\n[AntiEnter 状态] 🟢 已全面激活！")
        print(f"  - 平台: {os_name}")
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
    """停止 AntiEnter（终止 UI 守护进程、取消排队动作并卸载 Hook）"""
    print("[AntiEnter] 正在停用...")
    stopped_ok = True
    if not update_config({"enabled": False}):
        sys.stderr.write("[AntiEnter] 警告: 无法持久化停用配置。\n")
        stopped_ok = False
    gen = advance_generation()  # 递增代次，取消所有排队任务
    if gen == -1:
        sys.stderr.write("[AntiEnter] 警告: 递增代次失败，排队动作未能共享新代次。\n")
        stopped_ok = False

    active_inst = get_active_instance()

    if active_inst is not None:
        pid = active_inst.get("pid")
        try:
            if sys.platform == "win32":
                res = subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                if res.returncode != 0:
                    stopped_ok = False
            else:
                os.kill(pid, signal.SIGTERM)
                # 等待最多 2 秒确认退出
                for _ in range(20):
                    if not is_pid_alive(pid):
                        break
                    time.sleep(0.1)
                if is_pid_alive(pid):
                    os.kill(pid, signal.SIGKILL)
                    time.sleep(0.2)
                if is_pid_alive(pid):
                    sys.stderr.write(f"[AntiEnter] 错误: 终止进程 (PID: {pid}) 失败，进程依然存活。\n")
                    stopped_ok = False
            if stopped_ok:
                print(f"  ✓ 已终止 UI 守护进程 (PID: {pid})。")
        except ProcessLookupError:
            pass
        except OSError as e:
            sys.stderr.write(f"[AntiEnter] 错误: 终止进程 (PID: {pid}) 异常: {e}\n")
            stopped_ok = False
        finally:
            if not is_pid_alive(pid):
                unregister_instance(pid)
    else:
        print("  - UI 守护进程未在运行。")

    hook_cleaned = uninstall_hook()
    if hook_cleaned:
        print("  ✓ 已卸载 Antigravity 协议层 Hook。")
    else:
        print("  ✗ 卸载 Hook 失败，保留停用状态。")
        stopped_ok = False

    if stopped_ok:
        print("[AntiEnter 状态] 🔴 已完全停止，恢复原生人工审批模式。")
    else:
        print("[AntiEnter 状态] ⚠️ 停止过程中发生部分异常，请检查状态。")
    return stopped_ok


def status() -> int:
    """显示当前状态与配置详情，返回 0 表示正常运行，1 表示未运行"""
    config = load_config()
    active_inst = get_active_instance()
    hook_active = is_hook_installed()

    print("================ AntiEnter 运行状态 ================")
    if active_inst is not None and hook_active:
        print("整体状态: 🟢 运行中 (全功能激活)")
        code = 0
    elif active_inst is not None:
        print("整体状态: 🟡 仅 UI 守护进程运行中 (Hook 未生效)")
        code = 0
    elif hook_active:
        print("整体状态: 🟡 仅协议 Hook 生效中 (UI 守护进程未启动)")
        code = 0
    else:
        print("整体状态: 🔴 未运行 (原生人工确认模式)")
        code = 1

    pid = active_inst.get("pid") if active_inst else None
    entry = active_inst.get("entry") if active_inst else None
    print(f"守护进程 PID: {pid if pid else '无'} {f'({entry})' if entry else ''}")
    print(f"全局 Hook:    {'已安装' if hook_active else '未安装'}")
    print("---------------- 当前核心配置 ----------------")
    print(f"全局启用开关: {'开启' if config.get('enabled', True) else '关闭'}")
    print(f"回车缓冲延时: {config.get('buffer_delay')} 秒")
    print(f"提示音反馈:   {'开启' if config.get('play_sound') else '关闭'}")
    print(f"提示音主题:   {config.get('sound_theme')}")
    print(f"高危指令熔断: {'开启' if config.get('safety_fuse_enabled') else '关闭'}")
    print(f"受管桌面应用: {', '.join(config.get('desktop_targets', []))}")
    print(f"日志文件路径: {config.get('log_file')}")
    print("====================================================")
    return code
