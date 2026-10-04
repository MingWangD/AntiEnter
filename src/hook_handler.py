#!/usr/bin/env python3
from __future__ import annotations
"""
AntiEnter 协议层 PreToolUse Hook 处理器
针对 Antigravity 桌面端与 CLI 的工具调用，自动返回 {"decision": "allow"}，免除工具授权弹窗。
内置安全熔断：若匹配到高危黑名单指令、敏感路径覆盖或无效输入，则返回 {"decision": "ask"} 保留人工确认。
"""
import sys
import os
import json
import time
import re
import uuid
from pathlib import Path
from typing import Tuple

# 确保同目录与包导入均兼容（支持源码与 App Bundle 两种运行环境）
_current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_current_dir))
sys.path.insert(0, str(_current_dir.parent))
sys.path.insert(0, str(_current_dir.parent.parent))

try:
    from src.config import load_config, get_active_instance
    from src.sound import play_cue_async
except ImportError:
    from config import load_config, get_active_instance
    from sound import play_cue_async

SUPPORTED_TOOLS = {"run_command", "write_to_file", "replace_file_content"}


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
    """检查是否命中高危指令黑名单（删除文件、破坏性操作、系统路径重定向）"""
    if not config.get("safety_fuse_enabled", True):
        return False, ""

    # 1. 检查 run_command
    if tool_name == "run_command":
        cmd = args.get("CommandLine", "")
        if not isinstance(cmd, str):
            return True, "CommandLine 字段类型异常"
        cmd = cmd.strip()

        # 检查是否包含重定向至系统保护目录
        redir_patterns = [
            r"(?:>|>>|\btee\s+(?:-a\s+)?)\s*[\"']?(?:/etc/|/bin/|/sbin/|/usr/|/System/|/Library/|/private/etc/|[Cc]:\\windows)",
        ]
        for rpat in redir_patterns:
            if re.search(rpat, cmd, re.IGNORECASE):
                return True, f"命令行包含向系统关键目录重定向写入: '{cmd}'"

        # 关键词与正则表达式双重校验（macOS + Linux + Windows）
        deletion_patterns = [
            # Unix / 通用
            r"\brm\s+",
            r"\brmdir\b",
            r"\btrash\b",
            r"\bgit\s+reset\s+--hard\b",
            r"\bgit\s+clean\s+-[a-zA-Z0-9_-]*f",
            r"\bmkfs\b",
            r"\bdd\s+if=",
            r":\(\)\s*\{\s*:\|:&\s*\};:",
            r">\s*/dev/sda",
            r"\bchmod\s+(-[a-zA-Z0-9_-]*R\s+)?777\s+/",
            # Windows 专用危险指令 (CMD / PowerShell)
            r"\bdel\s+",
            r"\brd\s+",
            r"\bRemove-Item\b",
            r"\bformat\s+[A-Za-z]:",
            r"\bdiskpart\b",
            # 系统关机与数据库破坏
            r"\b(shutdown|reboot|init\s+0)\b",
            r"\bkill\s+-9\s+-1\b",
            r"\b(drop|truncate)\s+(database|table)\b",
        ]
        for pat in deletion_patterns:
            if re.search(pat, cmd, re.IGNORECASE):
                return True, f"命令行命中高危操作规则: '{pat}' (cmd: {cmd})"

        # 检查配置中的关键词列表
        for pattern in config.get("dangerous_patterns", []):
            if pattern.lower() in cmd.lower():
                return True, f"命令行包含高危模式: '{pattern}' (cmd: {cmd})"

    # 2. 检查写操作（规范化路径与符号链接解析）
    if tool_name in ("write_to_file", "replace_file_content"):
        target_file = args.get("TargetFile", "")
        if not isinstance(target_file, str) or not target_file.strip():
            return True, "TargetFile 参数缺失或类型异常"

        target_file = target_file.strip()
        # 路径解析规范化（处理 .. 与符号链接）
        try:
            resolved_path = os.path.realpath(os.path.expanduser(target_file))
        except Exception:
            resolved_path = target_file

        norm_file = resolved_path.lower().replace("/", "\\")

        # Unix 保护目录
        unix_protected = (
            "/etc",
            "/bin",
            "/sbin",
            "/usr",
            "/System",
            "/Library",
            "/private/etc",
            "/private/var",
            "/dev",
        )
        if any(resolved_path == p or resolved_path.startswith(p + "/") for p in unix_protected):
            return True, f"目标路径触及系统保护目录: '{resolved_path}'"

        # Windows 保护目录
        raw_norm = target_file.lower().replace("/", "\\")
        win_protected = (
            "c:\\windows",
            "c:\\program files",
            "c:\\program files (x86)",
            "\\windows\\system32",
            "windows\\system32",
        )
        if any(norm_file.startswith(wp) or raw_norm.startswith(wp) for wp in win_protected):
            return True, f"目标路径触及 Windows 系统保护目录: '{resolved_path}'"

    return False, ""


def record_decision(decision: str, tool_name: str, reason: str = ""):
    """写入当前决策状态至 antienter_decision.json，供 UI 守护进程跨进程联动"""
    try:
        try:
            from src.config import get_runtime_dir
            rdir = get_runtime_dir()
        except ImportError:
            try:
                from config import get_runtime_dir
                rdir = get_runtime_dir()
            except ImportError:
                rdir = Path.home() / ".gemini"
        dec_file = rdir / "antienter_decision.json"
        rdir.mkdir(parents=True, exist_ok=True)
        tmp = dec_file.with_suffix(f".tmp.{os.getpid()}_{time.time()}")
        raw_tool_str = str(tool_name) if tool_name is not None else ""
        canonical_str = raw_tool_str.split(":")[-1].strip().lower() if raw_tool_str else ""
        data = {
            "token_id": str(uuid.uuid4()),
            "decision": decision,
            "raw_tool": raw_tool_str,
            "canonical_tool": canonical_str,
            "tool": canonical_str,
            "consumed": False,
            "consumed_at": None,
            "consumed_by": None,
            "timestamp": time.time(),
            "reason": reason,
        }
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dec_file)
    except Exception:
        pass


def process_hook():
    config = load_config()
    raw_input = sys.stdin.read().strip()

    # 1. 严格输入校验：空输入不得容错放行，必须保留人工审批
    if not raw_input:
        reason = "输入为空"
        log_decision("ask", "empty_input", reason)
        record_decision("ask", "empty_input", reason)
        print(json.dumps({"decision": "ask", "reason": "AntiEnter: 空输入保留人工确认"}))
        return

    # 2. JSON 格式校验：坏 JSON 不得容错放行
    try:
        data = json.loads(raw_input)
    except Exception as e:
        reason = f"JSON解析失败: {e}"
        log_decision("ask", "malformed_json", reason)
        record_decision("ask", "malformed_json", reason)
        print(json.dumps({"decision": "ask", "reason": f"AntiEnter: JSON格式错误保留人工确认 ({e})"}))
        return

    if not isinstance(data, dict):
        reason = "顶层结构不是字典"
        log_decision("ask", "invalid_type", reason)
        record_decision("ask", "invalid_type", reason)
        print(json.dumps({"decision": "ask", "reason": "AntiEnter: 协议格式错误保留人工确认"}))
        return

    tool_call = data.get("toolCall")
    if not isinstance(tool_call, dict):
        reason = "缺少 toolCall 字典"
        log_decision("ask", "missing_tool_call", reason)
        record_decision("ask", "missing_tool_call", reason)
        print(json.dumps({"decision": "ask", "reason": "AntiEnter: 缺少工具调用信息保留人工确认"}))
        return

    tool_name = tool_call.get("name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        reason = "缺少工具名称"
        log_decision("ask", "missing_tool_name", reason)
        record_decision("ask", "missing_tool_name", reason)
        print(json.dumps({"decision": "ask", "reason": "AntiEnter: 工具名称缺失保留人工确认"}))
        return

    # 标准化工具名（去除命名空间前缀，如 default_api:run_command -> run_command）
    canonical_name = tool_name.split(":")[-1]

    # 3. 未知工具检查：不支持的工具保留人工审批
    if canonical_name not in SUPPORTED_TOOLS:
        reason = f"未支持的工具类型: {tool_name}"
        log_decision("ask", tool_name, reason)
        record_decision("ask", tool_name, reason)
        print(json.dumps({"decision": "ask", "reason": f"AntiEnter: 未知工具 '{tool_name}' 保留人工确认"}))
        return

    # 3.1 严格参数 Schema 校验：参数缺失、null 或非字典绝不放行 (P1-2)
    tool_args = tool_call.get("args")
    if not isinstance(tool_args, dict):
        reason = "工具参数缺失或类型异常 (非字典)"
        log_decision("ask", tool_name, reason)
        record_decision("ask", tool_name, reason)
        print(json.dumps({"decision": "ask", "reason": f"AntiEnter: {reason}保留人工确认"}))
        return

    if canonical_name == "run_command":
        cmd = tool_args.get("CommandLine")
        if not isinstance(cmd, str) or not cmd.strip():
            reason = "run_command 缺少必填参数 CommandLine 或为空"
            log_decision("ask", tool_name, reason)
            record_decision("ask", tool_name, reason)
            print(json.dumps({"decision": "ask", "reason": f"AntiEnter: {reason}保留人工确认"}))
            return
    elif canonical_name in ("write_to_file", "replace_file_content"):
        target_file = tool_args.get("TargetFile")
        if not isinstance(target_file, str) or not target_file.strip():
            reason = f"{canonical_name} 缺少必填参数 TargetFile 或为空"
            log_decision("ask", tool_name, reason)
            record_decision("ask", tool_name, reason)
            print(json.dumps({"decision": "ask", "reason": f"AntiEnter: {reason}保留人工确认"}))
            return

    # 4. 全局启用状态检查：若暂停或停用，则不自动批准
    if not config.get("enabled", True):
        reason = "AntiEnter 全局已暂停/停用"
        log_decision("ask", tool_name, reason)
        record_decision("ask", tool_name, reason)
        print(json.dumps({"decision": "ask", "reason": "AntiEnter: 当前已停用，恢复人工审批"}))
        return

    # 4.1 存活实例检查：若无活跃运行的 AntiEnter 进程，严禁继续自动放行与发声
    active_inst = get_active_instance()
    if not active_inst and os.getenv("ANTIENTER_TEST_MODE") != "1":
        reason = "AntiEnter 进程未运行"
        log_decision("ask", tool_name, reason)
        record_decision("ask", tool_name, reason)
        print(json.dumps({"decision": "ask", "reason": "AntiEnter: 客户端已退出，恢复人工审批"}))
        return

    # 5. 安全熔断黑名单检查
    dangerous, reason = is_dangerous(canonical_name, tool_args, config)
    if dangerous:
        log_decision("ask", tool_name, reason)
        record_decision("ask", tool_name, reason)
        print(json.dumps({"decision": "ask", "reason": f"AntiEnter: 安全熔断拦截 - {reason}"}))
        return

    # 6. 安全操作自动放行
    log_decision("allow", tool_name, "常规操作自动放行")
    record_decision("allow", tool_name, "")
    play_cue_async()
    print(json.dumps({"decision": "allow", "reason": "AntiEnter 自动批准（完全权限自主模式）"}))


if __name__ == "__main__":
    process_hook()
