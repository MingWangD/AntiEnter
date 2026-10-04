"""
AntiEnter Windows 原生 UI 自动回车守护进程
基于 Windows API (ctypes.windll.user32)，纯标准库实现，零第三方依赖。
检测 Antigravity、Antigravity Tools、终端确认对话框，经过 1.0s 缓冲与蜂鸣音后自动发送 Enter (VK_RETURN)。
"""
from __future__ import annotations
import sys
import os
import time
import ctypes
from ctypes import wintypes
from pathlib import Path

# 同级模块安全导入
_current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_current_dir))
sys.path.insert(0, str(_current_dir.parent))

try:
    from src.config import load_config
    from src.sound import play_cue_async
except ImportError:
    from config import load_config
    from sound import play_cue_async

# Windows 常量
VK_RETURN = 0x0D
KEYEVENTF_KEYUP = 0x0002
GW_ENABLEDPOPUP = 6


def get_foreground_window_title() -> tuple[int, str]:
    """获取前台激活窗口的句柄与标题"""
    if sys.platform != "win32":
        return 0, ""
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return 0, ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return hwnd, ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return hwnd, buf.value


def send_windows_return():
    """通过 Windows API 发送 Return 回车键"""
    if sys.platform != "win32":
        return
    user32 = ctypes.windll.user32
    # Key Down
    user32.keybd_event(VK_RETURN, 0, 0, 0)
    time.sleep(0.03)
    # Key Up
    user32.keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0)


def has_confirm_dialog_windows(hwnd: int, config: dict) -> bool:
    """检查窗口或弹窗中是否含有确认元素"""
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32

    # 1. 检查是否存在模态弹窗 (Popup Window)
    popup_hwnd = user32.GetWindow(hwnd, GW_ENABLEDPOPUP)
    if popup_hwnd and popup_hwnd != hwnd:
        return True

    # 2. 检查窗口类名与子控件
    confirm_keywords = [
        "Proceed", "Allow", "Run", "Submit", "Continue", "Confirm", "Yes", "OK",
        "确定", "允许", "继续", "执行", "好"
    ]
    found = [False]

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def enum_child_callback(child_hwnd, lparam):
        length = user32.GetWindowTextLengthW(child_hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(child_hwnd, buf, length + 1)
            text = buf.value.strip()
            for kw in confirm_keywords:
                if kw.lower() == text.lower() or kw in text:
                    found[0] = True
                    return False  # 停止枚举
        return True

    cb = WNDENUMPROC(enum_child_callback)
    user32.EnumChildWindows(hwnd, cb, 0)
    return found[0]


class WindowsDaemonEngine:
    def __init__(self):
        self.config = load_config()
        self.last_trigger_time = 0
        self.cooldown = 2.0
        self.running = True

    def run(self):
        print("==================================================")
        print("    AntiEnter Windows UI 自动回车守护进程已启动    ")
        print("==================================================")
        buffer_delay = self.config.get("buffer_delay", 1.0)
        print(f"[*] 回车缓冲延时: {buffer_delay} 秒")
        print(f"[*] 提示音状态:   {'开启' if self.config.get('play_sound') else '关闭'}")
        print(f"[*] 高危熔断状态: {'开启' if self.config.get('safety_fuse_enabled') else '关闭'}")
        print("[*] 正在实时监控 Antigravity 窗口与确认对话框...")
        print("[*] 按 Ctrl+C 退出守护进程。")
        print("--------------------------------------------------")

        target_apps = self.config.get("desktop_targets", []) + self.config.get("terminal_targets", [])

        while self.running:
            try:
                time.sleep(0.5)
                if sys.platform != "win32":
                    time.sleep(1)
                    continue

                hwnd, title = get_foreground_window_title()
                if not hwnd or not title:
                    continue

                # 检查前台窗口是否为目标应用
                matched = any(target.lower() in title.lower() for target in target_apps)
                if not matched:
                    continue

                now = time.time()
                if now - self.last_trigger_time < self.cooldown:
                    continue

                # 检查是否有确认弹窗或按钮
                if has_confirm_dialog_windows(hwnd, self.config):
                    print(f"[{time.strftime('%H:%M:%S')}] 检测到 [{title}] 等待确认，开始 {buffer_delay}s 缓冲倒计时...")
                    play_cue_async()

                    time.sleep(buffer_delay)

                    # 再次确认前台未切走
                    current_hwnd, _ = get_foreground_window_title()
                    if current_hwnd == hwnd:
                        print(f"[{time.strftime('%H:%M:%S')}] 触发 Enter 回车确认完成！")
                        send_windows_return()
                        self.last_trigger_time = time.time()

            except KeyboardInterrupt:
                print("\n[AntiEnter] 守护进程已停止。")
                break
            except Exception as e:
                time.sleep(1)


if __name__ == "__main__":
    daemon = WindowsDaemonEngine()
    daemon.run()
