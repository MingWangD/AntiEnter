"""
AntiEnter Windows 原生 UI 自动回车守护进程
基于 Windows API (ctypes.windll.user32)，纯标准库实现，零第三方依赖。
检测 Antigravity、Antigravity Tools、终端确认对话框，经过 1.0s 缓冲与蜂鸣音后自动发送 Enter (VK_RETURN)。
收紧识别策略：仅匹配真实有效的按钮控件，杜绝普通编辑区与文本误判；支持运行代次与动作取消。
"""
from __future__ import annotations
import sys
import os
import json
import time
import ctypes
from ctypes import wintypes
from pathlib import Path

# 同级模块安全导入
_current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_current_dir))
sys.path.insert(0, str(_current_dir.parent))

try:
    from src.config import (
        load_config,
        register_instance,
        unregister_instance,
        get_active_instance,
        consume_decision_token,
        get_active_decision_token,
    )
    from src.sound import play_cue_async
except ImportError:
    from config import (
        load_config,
        register_instance,
        unregister_instance,
        get_active_instance,
        consume_decision_token,
        get_active_decision_token,
    )
    from sound import play_cue_async

# Windows 常量
VK_RETURN = 0x0D
KEYEVENTF_KEYUP = 0x0002
GW_ENABLEDPOPUP = 6


# Windows API
user32 = getattr(ctypes, "windll", None).user32 if hasattr(ctypes, "windll") else None


def get_foreground_window_title() -> tuple[int, str]:
    """获取前台激活窗口的句柄与标题"""
    if sys.platform != "win32" or user32 is None:
        return 0, ""
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
    if sys.platform != "win32" or user32 is None:
        return
    # Key Down
    user32.keybd_event(VK_RETURN, 0, 0, 0)
    time.sleep(0.03)
    # Key Up
    user32.keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0)


def detect_window_tool(hwnd: int, _user32=None) -> Optional[str]:
    """从窗口标题及子控件文本中提取当前请求的规范化工具名"""
    u32 = _user32 or user32
    if u32 is None:
        return None

    tool_keywords = [
        ("run_command", ["run_command", "run command", "commandline", "command:"]),
        ("write_to_file", ["write_to_file", "write to file", "targetfile"]),
        ("replace_file_content", ["replace_file_content", "replace file content"]),
    ]

    # 1. 检查根窗口标题
    root_len = u32.GetWindowTextLengthW(hwnd)
    if root_len > 0:
        root_buf = ctypes.create_unicode_buffer(root_len + 1)
        u32.GetWindowTextW(hwnd, root_buf, root_len + 1)
        rt = root_buf.value.lower()
        for ctool, kws in tool_keywords:
            if any(kw in rt for kw in kws):
                return ctool

    # 2. 扫描子控件文本
    detected = [None]
    if hasattr(ctypes, "WINFUNCTYPE") and hasattr(ctypes, "wintypes"):
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    else:
        WNDENUMPROC = lambda fn: fn

    def enum_tool_cb(child_hwnd, lparam):
        if not u32.IsWindowVisible(child_hwnd):
            return True
        length = u32.GetWindowTextLengthW(child_hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            u32.GetWindowTextW(child_hwnd, buf, length + 1)
            txt = buf.value.lower()
            for ctool, kws in tool_keywords:
                if any(kw in txt for kw in kws):
                    detected[0] = ctool
                    return False
        return True

    u32.EnumChildWindows(hwnd, WNDENUMPROC(enum_tool_cb), 0)
    return detected[0]


def has_confirm_dialog_windows(hwnd: int, config: dict, _user32=None, expected_tool: Optional[str] = None) -> bool:
    """检查窗口中是否包含明确的确认交互目标，杜绝编辑区与正文误判，联动高危熔断与 Hook 决策"""
    u32 = _user32 or user32
    if u32 is None:
        return False

    fuse_enabled = config.get("safety_fuse_enabled", True)

    # 1. 检查是否存在活跃的 Hook ask 决策（30s 内保留人工确认）
    try:
        from src.config import get_decision_file
        dec_file = get_decision_file()
    except Exception:
        try:
            from config import get_decision_file
            dec_file = get_decision_file()
        except Exception:
            dec_file = Path.home() / ".gemini" / "antienter_decision.json"

    has_safe_token = False
    if dec_file.exists():
        try:
            with open(dec_file, "r", encoding="utf-8") as df:
                dec_data = json.load(df)
            if isinstance(dec_data, dict):
                decision = dec_data.get("decision")
                ts = float(dec_data.get("timestamp", 0))
                consumed = dec_data.get("consumed", False)
                if decision == "ask" and time.time() - ts < 30.0:
                    # Hook 判定高危或异常等待人工审批，UI 严禁自动按键
                    return False
                elif decision == "allow" and not consumed and (time.time() - ts < 10.0):
                    raw_tool = dec_data.get("canonical_tool") or dec_data.get("tool")
                    if isinstance(raw_tool, str) and raw_tool.strip() and expected_tool:
                        norm_tool = raw_tool.split(":")[-1].strip().lower()
                        norm_expected = expected_tool.split(":")[-1].strip().lower()
                        if norm_tool == norm_expected:
                            has_safe_token = True
        except Exception:
            pass

    # 否定排除词（含否定含义的按钮绝不点击，防止误点"Do not proceed"、"Don't allow"）
    negative_words = [
        "do not", "don't", "never", "cancel", "deny", "reject",
        "refuse", "disallow", "no, ", "取消", "拒绝", "不",
    ]

    safe_exact_words = {
        "confirm", "submit", "proceed", "ok", "yes",
        "确定", "继续", "好", "skip", "跳过",
    }
    tool_exact_words = {"allow", "允许"}
    tool_permission_phrases = [
        "yes, allow this time",
        "allow this time",
        "yes, and always allow",
        "always allow",
        "allow pushing",
        "allow searching",
        "allow running",
        "allow editing",
        "allow writing",
        "始终允许",
        "本次允许",
        "总是允许",
    ]

    # 规则：
    # 熔断开启时：所有自动动作（无论是 Submit ↵ 还是通用确认词）均必须持有与当前工具绑定的未消费有效令牌！
    # 熔断关闭时：允许 Submit ↵、所有通用词及工具授权模板
    if not fuse_enabled:
        strong_phrases = ["submit ↵"] + tool_permission_phrases
        exact_action_words = safe_exact_words | tool_exact_words
    elif has_safe_token:
        strong_phrases = ["submit ↵"]
        exact_action_words = set(safe_exact_words)
    else:
        strong_phrases = []
        exact_action_words = set()

    if hasattr(ctypes, "WINFUNCTYPE") and hasattr(ctypes, "wintypes"):
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    else:
        WNDENUMPROC = lambda fn: fn

    danger_indicators = [
        # Unix / Git / 通用删除与破坏性指令
        "rm -rf", "rm -r", "rm -f", "rm ", "rmdir", "trash",
        "git reset --hard", "git reset", "git clean",
        "sudo ", "curl ", "sh ", "bash ",
        "mkfs", "dd if=", ":(){ :|:& };:", "> /dev/", "chmod -r 777", "chmod 777",
        # Windows 原生危险指令与磁盘操作
        "del /s", "del /f", "del /q", "del ", "rd /s", "rd /q", "rd /", "rd ",
        "remove-item", "format ", "diskpart",
        # 关机与强杀
        "shutdown", "reboot", "init 0", "kill -9",
        # 系统保护路径重定向与写入
        "/etc/", "/bin/", "/sbin/", "/usr/", "/system/", "/library/",
        "c:\\windows", "system32",
        # 敏感工具调用特征
        "commandline", "run_command", "write_to_file", "replace_file_content",
    ]
    for dp in config.get("dangerous_patterns", []):
        if dp and str(dp).lower() not in danger_indicators:
            danger_indicators.append(str(dp).lower())

    # 若开启熔断，预先检查根窗口标题与子控件文本是否涉及高危工具或命令行执行
    if fuse_enabled:
        root_len = u32.GetWindowTextLengthW(hwnd)
        if root_len > 0:
            root_buf = ctypes.create_unicode_buffer(root_len + 1)
            u32.GetWindowTextW(hwnd, root_buf, root_len + 1)
            root_title = root_buf.value.lower()
            if any(di in root_title for di in danger_indicators):
                return False

        has_danger = [False]

        def enum_context_callback(child_hwnd, lparam):
            if not u32.IsWindowVisible(child_hwnd):
                return True
            length = u32.GetWindowTextLengthW(child_hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                u32.GetWindowTextW(child_hwnd, buf, length + 1)
                text_lower = buf.value.lower()
                if any(di in text_lower for di in danger_indicators):
                    has_danger[0] = True
                    return False
            return True

        u32.EnumChildWindows(hwnd, WNDENUMPROC(enum_context_callback), 0)
        if has_danger[0]:
            # 窗口中包含高危指令或敏感工具调用，熔断生效，严禁自动发键
            return False

    found = [False]

    def enum_child_callback(child_hwnd, lparam):
        if not u32.IsWindowVisible(child_hwnd):
            return True
        if not u32.IsWindowEnabled(child_hwnd):
            return True

        # 严格获取控件类名：必须是真实可点击按钮 (Button / SysCommandLink)
        # 排除静态文本 (Static)、标签 (Label)、超链接 (SysLink) 及编辑框 (Edit)
        class_buf = ctypes.create_unicode_buffer(256)
        u32.GetClassNameW(child_hwnd, class_buf, 256)
        class_name = class_buf.value.lower()

        if not any(btn_cls in class_name for btn_cls in ["button", "syscommandlink"]):
            return True

        # 排除非按钮样式的控件（例如 GroupBox: BS_GROUPBOX = 0x7）
        try:
            GWL_STYLE = -16
            style = u32.GetWindowLongW(child_hwnd, GWL_STYLE)
            if (style & 0xF) == 0x7:  # BS_GROUPBOX
                return True
        except Exception:
            pass

        length = u32.GetWindowTextLengthW(child_hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            u32.GetWindowTextW(child_hwnd, buf, length + 1)
            text = buf.value.strip()
            text_lower = text.lower()

            # 否定短语防误触（如 "Do not proceed", "Don't allow", "Cancel"）
            if any(nw in text_lower for nw in negative_words):
                return True

            # 1. 强特征短语匹配
            for sp in strong_phrases:
                if sp in text_lower:
                    found[0] = True
                    return False

            # 2. 精确按钮词匹配
            if text_lower in exact_action_words:
                found[0] = True
                return False

        return True

    cb = WNDENUMPROC(enum_child_callback)
    u32.EnumChildWindows(hwnd, cb, 0)
    return found[0]


class WindowsDaemonEngine:
    def __init__(self):
        self.last_trigger_time = 0
        self.cooldown = 2.0
        self.running = True

    def check_and_trigger(self, hwnd: int, title: str, config: dict, _user32=None) -> bool:
        """检查并执行自动确认动作（含工具提取、缓冲延时、发送前重检与令牌消费）"""
        target_apps = config.get("desktop_targets", []) + config.get("terminal_targets", [])
        matched = any(target.lower() in title.lower() for target in target_apps)
        if not matched:
            return False

        now = time.time()
        if now - self.last_trigger_time < self.cooldown:
            return False

        expected_tool = detect_window_tool(hwnd, _user32)

        if not has_confirm_dialog_windows(hwnd, config, _user32=_user32, expected_tool=expected_tool):
            return False

        captured_gen = config.get("generation", 1)
        delay = config.get("buffer_delay", 1.0)
        print(f"[{time.strftime('%H:%M:%S')}] 检测到 [{title}] 等待确认 (工具: {expected_tool})，开始 {delay}s 缓冲倒计时...")
        play_cue_async()

        if delay > 0:
            time.sleep(delay)

        latest_cfg = load_config()
        if not latest_cfg.get("enabled", True) or latest_cfg.get("generation", 1) != captured_gen:
            print(f"[{time.strftime('%H:%M:%S')}] 策略变更或已暂停，取消自动动作。")
            return False

        current_hwnd = hwnd if _user32 is not None else get_foreground_window_title()[0]
        if current_hwnd == hwnd and has_confirm_dialog_windows(hwnd, latest_cfg, _user32=_user32, expected_tool=expected_tool):
            # 消费令牌，杜绝重放
            try:
                from src.config import consume_decision_token
                consume_decision_token()
            except Exception:
                try:
                    from config import consume_decision_token
                    consume_decision_token()
                except Exception:
                    pass
            print(f"[{time.strftime('%H:%M:%S')}] 触发 Enter 回车确认完成！")
            send_windows_return()
            self.last_trigger_time = time.time()
            return True
        return False

    def run(self):
        config = load_config()
        if not register_instance(os.getpid(), "windows"):
            print("[AntiEnter] 已有活跃运行实例，守护进程退出。")
            return

        try:
            print("==================================================")
            print("    AntiEnter Windows UI 自动回车守护进程已启动    ")
            print("==================================================")
            print(f"[*] 全局启用状态: {'开启' if config.get('enabled', True) else '关闭'}")
            print(f"[*] 回车缓冲延时: {config.get('buffer_delay', 1.0)} 秒")
            print(f"[*] 提示音状态:   {'开启' if config.get('play_sound') else '关闭'}")
            print(f"[*] 高危熔断状态: {'开启' if config.get('safety_fuse_enabled') else '关闭'}")
            print("[*] 正在实时监控 Antigravity 窗口与确认对话框...")
            print("[*] 按 Ctrl+C 退出守护进程。")
            print("--------------------------------------------------")

            while self.running:
                try:
                    time.sleep(0.5)
                    if sys.platform != "win32":
                        time.sleep(1)
                        continue

                    # 动态读取最新配置
                    config = load_config()
                    if not config.get("enabled", True):
                        continue

                    hwnd, title = get_foreground_window_title()
                    if not hwnd or not title:
                        continue

                    self.check_and_trigger(hwnd, title, config)

                except KeyboardInterrupt:
                    print("\n[AntiEnter] 守护进程已停止。")
                    break
                except Exception:
                    time.sleep(1)
        finally:
            unregister_instance(os.getpid())


if __name__ == "__main__":
    daemon = WindowsDaemonEngine()
    daemon.run()
