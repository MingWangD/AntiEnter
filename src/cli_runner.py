from __future__ import annotations
"""
AntiEnter CLI PTY 智能交互包装器
用于包装 Antigravity CLI (agy) 或任何交互式终端指令。
在终端检测到等待确认提示时，自动在 1.0s 缓冲后注入 Return (\n)。
"""
import sys
import os
import pty
import select
import tty
import termios
import re
import time
from pathlib import Path
from typing import List

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


def run_with_pty(cmd_args: list[str]):
    """使用 PTY 运行 CLI 命令并监控输出提示"""
    config = load_config()
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
            sys.exit(1)

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
                    if now - last_trigger_time > cooldown:
                        tail = output_buffer[-300:]
                        matched = any(pattern.search(tail) for pattern in prompt_patterns)
                        if matched:
                            play_cue_async()
                            time.sleep(buffer_delay)
                            # 发送回车
                            os.write(master_fd, b"\n")
                            last_trigger_time = time.time()
                            output_buffer = ""
                except OSError:
                    break
    finally:
        if old_term_settings:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_term_settings)
            except Exception:
                pass
        try:
            os.close(master_fd)
            _, status = os.waitpid(pid, 0)
            sys.exit(os.waitstatus_to_exitcode(status))
        except Exception:
            sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 cli_runner.py <command> [args...]")
        sys.exit(1)
    run_with_pty(sys.argv[1:])
