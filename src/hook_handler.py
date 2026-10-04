#!/usr/bin/env python3
from __future__ import annotations
"""
AntiEnter 协议层 PreToolUse Hook 处理器
针对 Antigravity 桌面端与 CLI 的工具调用，自动返回 {"decision": "allow"}，免除工具授权弹窗。
内置安全熔断：若匹配到高危黑名单指令，则返回 {"decision": "ask"} 保留人工确认。
"""
import sys
import os
import json
import time
import re
from pathlib import Path
from typing import Tuple

# 确保同目录与包导入均兼容（支持源码与 App Bundle 两种运行环境）
_current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_current_dir))
sys.path.insert(0, str(_current_dir.parent))
sys.path.insert(0, str(_current_dir.parent.parent))

try:
    from src.config import load_config
    from src.sound import play_cue_async
except ImportError:
    from config import load_config
    from sound import play_cue_async


def log_decision(decision: str, tool_name: str, detail: str):
    """记录放行审计日志"""
    try:
        config = load_config()
        log_file = config.get("log_file")
        if log_file:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] [{decision.upper()}] tool={tool_name} detail={detail}\n")
    except Exception:
        pass


def is_dangerous(tool_name: str, args: dict, config: dict) -> tuple[bool, str]:
    """检查是否命中高危指令黑名单（删除文件、破坏性操作）"""
    if not config.get("safety_fuse_enabled", True):
        return False, ""

    # 1. 检查 run_command
    if tool_name == "run_command":
        cmd = args.get("CommandLine", "").strip()
        
        # 关键词与正则表达式双重校验
        deletion_patterns = [
            r"\brm\s+",
            r"\brmdir\b",
            r"\btrash\b",
            r"\bgit\s+reset\s+--hard\b",
            r"\bgit\s+clean\s+-[a-zA-Z0-9_-]*f",
            r"\bmkfs\b",
            r"\bdd\s+if=",
            r":\(\)\s*\{\s*:\|:&\s*\};:",
            r"\b(shutdown|reboot|init\s+0)\b",
            r"\bkill\s+-9\s+-1\b",
            r"\b(drop|truncate)\s+(database|table)\b",
        ]
        for pat in deletion_patterns:
            if re.search(pat, cmd, re.IGNORECASE):
                return True, f"命令行命中高危操作规则: '{pat}' (cmd: {cmd})"

        # 检查常规关键词列表
        for pattern in config.get("dangerous_patterns", []):
            if pattern in cmd:
                return True, f"命令行包含高危模式: '{pattern}' (cmd: {cmd})"

    # 2. 检查危险的写操作（如覆盖敏感系统文件）
    if tool_name in ("write_to_file", "replace_file_content"):
        target_file = args.get("TargetFile", "")
        # 禁止覆写系统关键配置
        if target_file.startswith(("/etc", "/bin", "/sbin", "/usr/bin", "/System", "/Library")):
            return True, f"目标路径触及系统保护目录: '{target_file}'"

    return False, ""


def process_hook():
    config = load_config()
    raw_input = sys.stdin.read().strip()

    if not raw_input:
        # 异常空输入保底放行
        print(json.dumps({"decision": "allow", "reason": "AntiEnter: 默认放行"}))
        return

    try:
        data = json.loads(raw_input)
    except Exception as e:
        print(json.dumps({"decision": "allow", "reason": f"AntiEnter: JSON解析容错放行 ({e})"}))
        return

    tool_call = data.get("toolCall", {})
    tool_name = tool_call.get("name", "unknown")
    tool_args = tool_call.get("args", {})

    # 安全熔断检查
    dangerous, reason = is_dangerous(tool_name, tool_args, config)
    if dangerous:
        log_decision("ask", tool_name, reason)
        result = {
            "decision": "ask",
            "reason": f"AntiEnter 安全熔断拦截：{reason}。已保留人工审核。"
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    # 正常放行
    # 若配置了 1s 缓冲延时并在 hook 中体现，可以轻微延时并播放提示音
    buffer_delay = config.get("buffer_delay", 1.0)
    if buffer_delay > 0:
        play_cue_async()
        # 控制在合理缓冲期
        time.sleep(min(buffer_delay, 1.0))

    summary = tool_args.get("CommandLine", tool_args.get("TargetFile", tool_name))
    log_decision("allow", tool_name, str(summary)[:100])

    result = {
        "decision": "allow",
        "reason": "AntiEnter 自动批准（完全权限自主模式）"
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    process_hook()
