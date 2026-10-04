from __future__ import annotations
"""
AntiEnter CLI PTY 智能交互包装器
用于包装 Antigravity CLI (agy) 或任何交互式终端指令。
在终端检测到等待确认提示时，自动在 1.0s 缓冲后注入 Return (\n)。
若开启高危熔断且命令为高危指令，则保持人工确认，不自动注入。
Windows 平台暂不支持 PTY 模式。
"""
import sys
import os
import re
import time
import subprocess
from pathlib import Path
from typing import List

_current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_current_dir))
sys.path.insert(0, str(_current_dir.parent))
sys.path.insert(0, str(_current_dir.parent.parent))

try:
    from src.config import load_config
    from src.sound import play_cue_async
    from src.hook_handler import is_dangerous
except ImportError:
    from config import load_config
    from sound import play_cue_async
    from hook_handler import is_dangerous


def run_with_pty(cmd_args: list[str]) -> int:
    """使用 PTY 运行 CLI 命令并监控输出提示（Unix 专属）"""
    if sys.platform == "win32":
        sys.stderr.write("错误: Windows 平台暂不支持 PTY 终端交互包装器 (wrap 命令)。\n")
        return 1

    import pty
    import select
    import tty
    import termios

    config = load_config()
    if not config.get("enabled", True):
        # AntiEnter 已暂停，直接透传运行，杜绝 shell 注入
        return subprocess.run(cmd_args, check=False).returncode

    # 检查被包装的命令本身是否为高危命令
    full_cmd = " ".join(cmd_args)
    fuse_active = config.get("safety_fuse_enabled", True)
    cmd_dangerous, reason = is_dangerous("run_command", {"CommandLine": full_cmd}, config)

    buffer_delay = config.get("buffer_delay", 1.0)
    prompt_patterns = [
        re.compile(p, re.IGNORECASE)
        for p in config.get("cli_prompt_patterns", [])
    ]

    master_fd, slave_fd = pty.openpty()
    pid = os.fork()

    if pid == 0:
        # 子进程
        os.close(master_fd)
        os.setsid()
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        if slave_fd > 2:
            os.close(slave_fd)
        try:
            os.execvp(cmd_args[0], cmd_args)
        except Exception as e:
            sys.stderr.write(f"执行命令失败 {cmd_args}: {e}\n")
            sys.exit(127)

    # 父进程
    os.close(slave_fd)
    old_term_settings = None
    try:
        old_term_settings = termios.tcgetattr(sys.stdin.fileno())
        tty.setraw(sys.stdin.fileno())
    except Exception:
        pass

    output_buffer = ""
    last_trigger_time = 0
    cooldown = 2.0

    try:
        while True:
            rlist, _, _ = select.select([sys.stdin.fileno(), master_fd], [], [], 0.1)

            # 读取标准输入并转发到子进程
            if sys.stdin.fileno() in rlist:
                try:
                    user_input = os.read(sys.stdin.fileno(), 1024)
                    if not user_input:
                        break
                    os.write(master_fd, user_input)
                except OSError:
                    break

            # 读取子进程输出并打印到终端
            if master_fd in rlist:
                try:
                    data = os.read(master_fd, 1024)
                    if not data:
                        break
                    os.write(sys.stdout.fileno(), data)
                    sys.stdout.flush()

                    text = data.decode("utf-8", errors="ignore")
                    output_buffer += text
                    if len(output_buffer) > 2000:
                        output_buffer = output_buffer[-2000:]

                    # 检查是否匹配提示
                    now = time.time()
                    if (now - last_trigger_time) > cooldown:
                        # 若开启熔断且当前命令是高危指令，不自动注入
                        if not (fuse_active and cmd_dangerous):
                            if any(p.search(output_buffer) for p in prompt_patterns):
                                play_cue_async()
                                time.sleep(buffer_delay)
                                os.write(master_fd, b"\n")
                                last_trigger_time = time.time()
                                output_buffer = ""
                except OSError:
                    break

    finally:
        if old_term_settings is not None:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_term_settings)
            except Exception:
                pass
        os.close(master_fd)

    _, status = os.waitpid(pid, 0)
    exit_code = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else (status >> 8)
    return exit_code
