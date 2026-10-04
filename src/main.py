#!/usr/bin/env python3
"""
AntiEnter CLI 主程序
"""
import sys
import os
import argparse
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.controller import start, stop, status, build_daemon
from src.cli_runner import run_with_pty
from src.config import load_config, save_config


def main():
    parser = argparse.ArgumentParser(
        prog="antienter",
        description="AntiEnter: Antigravity 桌面端与 CLI 自动回车与完全权限自主模式插件",
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    p_start = subparsers.add_parser("start", help="启动 AntiEnter 插件")
    p_start.add_argument("--foreground", "-f", action="store_true", help="前台运行守护进程")

    subparsers.add_parser("stop", help="停止 AntiEnter 插件")
    subparsers.add_parser("status", help="查看 AntiEnter 运行状态")
    subparsers.add_parser("run", help="前台运行守护进程")
    subparsers.add_parser("build", help="重新编译 Swift 守护进程")

    p_wrap = subparsers.add_parser("wrap", help="在 PTY 智能回车环境下运行命令行程序 (如 agy)")
    p_wrap.add_argument("cmd", nargs=argparse.REMAINDER, help="要包装执行的命令及参数")

    p_cfg = subparsers.add_parser("config", help="查看或修改配置")
    p_cfg.add_argument("--delay", type=float, help="设置缓冲延时 (秒，如 1.0)")
    p_cfg.add_argument("--sound", choices=["on", "off"], help="开启或关闭提示音")
    p_cfg.add_argument("--fuse", choices=["on", "off"], help="开启或关闭高危指令安全熔断")

    subparsers.add_parser("test", help="运行功能与熔断自检")
    p_update = subparsers.add_parser("update", help="检查并自动更新 AntiEnter 至最新版本")
    p_update.add_argument("--cli", action="store_true", help="命令行交互模式更新（默认弹出原生对话框）")

    args = parser.parse_args()

    if args.command == "start":
        start(foreground=args.foreground)
    elif args.command == "stop":
        stop()
    elif args.command == "status":
        status()
    elif args.command == "run":
        start(foreground=True)
    elif args.command == "build":
        build_daemon()
    elif args.command == "wrap":
        if not args.cmd:
            print("错误: 请指定要运行的命令，例如: antienter wrap agy")
            sys.exit(1)
        run_with_pty(args.cmd)
    elif args.command == "config":
        cfg = load_config()
        changed = False
        if args.delay is not None:
            cfg["buffer_delay"] = args.delay
            changed = True
            print(f"[配置] 缓冲延时已更新为: {args.delay} 秒")
        if args.sound is not None:
            cfg["play_sound"] = (args.sound == "on")
            changed = True
            print(f"[配置] 提示音已更新为: {args.sound}")
        if args.fuse is not None:
            cfg["safety_fuse_enabled"] = (args.fuse == "on")
            changed = True
            print(f"[配置] 高危熔断已更新为: {args.fuse}")
        if changed:
            save_config(cfg)
        else:
            print("当前配置:")
            for k, v in cfg.items():
                print(f"  {k}: {v}")
    elif args.command == "test":
        import subprocess
        test_file = ROOT_DIR / "tests" / "test_hook.py"
        subprocess.run(["python3", str(test_file)])
    elif args.command == "update":
        from src.updater import check_and_update
        check_and_update(gui=(not args.cli))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
