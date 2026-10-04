"""
AntiEnter Hook 安装与卸载管理模块
负责在 Antigravity 全局配置目录 (~/.gemini/config/hooks.json) 中无损注入与移除 hook。
"""
import os
import json
from pathlib import Path

HOOK_NAME = "antienter-auto-approver"
GLOBAL_CONFIG_DIR = Path.home() / ".gemini" / "config"
GLOBAL_HOOKS_FILE = GLOBAL_CONFIG_DIR / "hooks.json"


def get_hook_definition(handler_path: str = None) -> dict:
    if handler_path is None:
        handler_path = str(Path(__file__).resolve().parent / "hook_handler.py")

    return {
        "enabled": True,
        "PreToolUse": [
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"python3 {handler_path}",
                        "timeout": 15,
                    }
                ],
            }
        ],
    }


def install_hook(handler_path: str = None) -> bool:
    """向全局 hooks.json 安装或更新 AntiEnter hook"""
    try:
        GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        hooks_data = {}

        if GLOBAL_HOOKS_FILE.exists():
            try:
                with open(GLOBAL_HOOKS_FILE, "r", encoding="utf-8") as f:
                    hooks_data = json.load(f)
            except Exception:
                hooks_data = {}

        hooks_data[HOOK_NAME] = get_hook_definition(handler_path)

        with open(GLOBAL_HOOKS_FILE, "w", encoding="utf-8") as f:
            json.dump(hooks_data, f, indent=2, ensure_ascii=False)

        return True
    except Exception as e:
        print(f"安装 Hook 失败: {e}")
        return False


def uninstall_hook() -> bool:
    """从全局 hooks.json 中移除 AntiEnter hook"""
    try:
        if not GLOBAL_HOOKS_FILE.exists():
            return True

        with open(GLOBAL_HOOKS_FILE, "r", encoding="utf-8") as f:
            hooks_data = json.load(f)

        if HOOK_NAME in hooks_data:
            del hooks_data[HOOK_NAME]
            with open(GLOBAL_HOOKS_FILE, "w", encoding="utf-8") as f:
                json.dump(hooks_data, f, indent=2, ensure_ascii=False)

        return True
    except Exception as e:
        print(f"卸载 Hook 失败: {e}")
        return False


def is_hook_installed() -> bool:
    """检查 Hook 是否已安装且处于启用状态"""
    if not GLOBAL_HOOKS_FILE.exists():
        return False
    try:
        with open(GLOBAL_HOOKS_FILE, "r", encoding="utf-8") as f:
            hooks_data = json.load(f)
        hook = hooks_data.get(HOOK_NAME)
        return bool(hook and hook.get("enabled", True))
    except Exception:
        return False
