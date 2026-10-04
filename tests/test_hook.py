"""
AntiEnter 自动化测试模块
覆盖普通指令放行测试、高危指令安全熔断测试、敏感路径拦截测试与配置读写测试。
"""
import sys
import os
import json
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
HOOK_HANDLER = ROOT_DIR / "src" / "hook_handler.py"


def run_handler_with_payload(payload: dict) -> dict:
    """向 hook_handler.py 管道输入 payload 并返回解析后的 JSON 输出"""
    process = subprocess.Popen(
        ["python3", str(HOOK_HANDLER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = process.communicate(input=json.dumps(payload))
    if process.returncode != 0:
        raise RuntimeError(f"Hook 处理程序异常退出: {stderr}")
    return json.loads(stdout.strip())


def test_safe_command_allowed():
    """测试常规安全指令自动放行"""
    payload = {
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "git status"},
        },
        "stepIdx": 1,
    }
    result = run_handler_with_payload(payload)
    assert result.get("decision") == "allow", f"安全指令应当放行，实际输出: {result}"
    print("  ✓ 常规命令放行测试通过 (git status -> allow)")


def test_dangerous_command_blocked():
    """测试极端高危指令被安全熔断拦截 (保留人工确认)"""
    payload = {
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "sudo rm -rf /"},
        },
        "stepIdx": 2,
    }
    result = run_handler_with_payload(payload)
    assert result.get("decision") == "ask", f"高危指令应当保留人工确认，实际输出: {result}"
    print("  ✓ 高危指令熔断测试通过 (rm -rf / -> ask)")


def test_forkbomb_blocked():
    """测试 Fork Bomb 等特殊危险模式拦截"""
    payload = {
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": ":(){ :|:& };:"},
        },
        "stepIdx": 3,
    }
    result = run_handler_with_payload(payload)
    assert result.get("decision") == "ask", f"Fork bomb 应当保留人工确认，实际输出: {result}"
    print("  ✓ Fork Bomb 拦截测试通过 (:(){ :|:& };: -> ask)")


def test_safe_file_write_allowed():
    """测试常规项目文件写入放行"""
    payload = {
        "toolCall": {
            "name": "write_to_file",
            "args": {"TargetFile": "/Users/myw/Desktop/AntiEnter/test.txt"},
        },
        "stepIdx": 4,
    }
    result = run_handler_with_payload(payload)
    assert result.get("decision") == "allow", f"项目目录文件写入应当放行，实际输出: {result}"
    print("  ✓ 项目文件写操作放行测试通过 (write_to_file -> allow)")


def test_system_file_write_blocked():
    """测试针对系统保护目录的文件写入拦截"""
    payload = {
        "toolCall": {
            "name": "write_to_file",
            "args": {"TargetFile": "/etc/hosts"},
        },
        "stepIdx": 5,
    }
    result = run_handler_with_payload(payload)
    assert result.get("decision") == "ask", f"系统保护目录写入应当拦截，实际输出: {result}"
    print("  ✓ 系统关键目录写保护拦截测试通过 (/etc/hosts -> ask)")


def test_rm_rf_any_directory_blocked():
    """测试任意目录的 rm -rf 均被安全熔断拦截"""
    payload = {
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "rm -rf ./build/dist"},
        },
        "stepIdx": 6,
    }
    result = run_handler_with_payload(payload)
    assert result.get("decision") == "ask", f"rm -rf 目录应当保留人工确认，实际输出: {result}"
    print("  ✓ 目录删除拦截测试通过 (rm -rf ./build/dist -> ask)")


def test_rm_file_blocked():
    """测试单文件删除 rm 同样被安全熔断拦截"""
    payload = {
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "rm important_data.json"},
        },
        "stepIdx": 7,
    }
    result = run_handler_with_payload(payload)
    assert result.get("decision") == "ask", f"rm 文件应当保留人工确认，实际输出: {result}"
    print("  ✓ 文件删除拦截测试通过 (rm important_data.json -> ask)")


def test_git_push_allowed():
    """测试 git push 等非破坏性指令自动放行"""
    payload = {
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "git push -u origin main --tags"},
        },
        "stepIdx": 8,
    }
    result = run_handler_with_payload(payload)
    assert result.get("decision") == "allow", f"git push 应当自动放行，实际输出: {result}"
    print("  ✓ 非破坏性指令放行测试通过 (git push -> allow)")


def test_windows_del_blocked():
    """测试 Windows 原生删除指令 del 均被拦截"""
    payload = {
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "del /f /s /q temp.txt"},
        },
        "stepIdx": 9,
    }
    result = run_handler_with_payload(payload)
    assert result.get("decision") == "ask", f"del 指令应当保留人工确认，实际输出: {result}"
    print("  ✓ Windows del 删除拦截测试通过 (del /f /s /q -> ask)")


def test_windows_rd_blocked():
    """测试 Windows 原生目录删除 rd /s 均被拦截"""
    payload = {
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "rd /s /q ./dist"},
        },
        "stepIdx": 10,
    }
    result = run_handler_with_payload(payload)
    assert result.get("decision") == "ask", f"rd /s 目录删除应当保留人工确认，实际输出: {result}"
    print("  ✓ Windows rd 目录删除拦截测试通过 (rd /s /q -> ask)")


def test_windows_remove_item_blocked():
    """测试 PowerShell Remove-Item 破坏性删除指令被拦截"""
    payload = {
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "Remove-Item -Recurse -Force ./data"},
        },
        "stepIdx": 11,
    }
    result = run_handler_with_payload(payload)
    assert result.get("decision") == "ask", f"Remove-Item 应当保留人工确认，实际输出: {result}"
    print("  ✓ PowerShell Remove-Item 删除拦截测试通过 (Remove-Item -> ask)")


def test_windows_system_path_blocked():
    """测试 Windows 系统保护目录写操作拦截"""
    payload = {
        "toolCall": {
            "name": "write_to_file",
            "args": {"TargetFile": "C:\\Windows\\System32\\drivers\\etc\\hosts"},
        },
        "stepIdx": 12,
    }
    result = run_handler_with_payload(payload)
    assert result.get("decision") == "ask", f"Windows 系统保护目录写入应当拦截，实际输出: {result}"
    print("  ✓ Windows 系统关键目录写保护测试通过 (C:\\Windows\\... -> ask)")


def run_all_tests():
    print("======== 开始执行 AntiEnter 核心逻辑自测试 ========")
    test_safe_command_allowed()
    test_dangerous_command_blocked()
    test_rm_rf_any_directory_blocked()
    test_rm_file_blocked()
    test_git_push_allowed()
    test_windows_del_blocked()
    test_windows_rd_blocked()
    test_windows_remove_item_blocked()
    test_windows_system_path_blocked()
    test_forkbomb_blocked()
    test_safe_file_write_allowed()
    test_system_file_write_blocked()
    print("================ 全部测试顺利通过！ ================")


if __name__ == "__main__":
    run_all_tests()
