"""
AntiEnter Hook 安装与卸载管理模块
负责在 Antigravity 全局配置目录 (~/.gemini/config/hooks.json) 中无损注入与移除 hook。
"""
import os
import json
from pathlib import Path

HOOK_NAME = "antienter-auto-approver"


def get_hooks_dir() -> Path:
    env_dir = os.environ.get("ANTIENTER_CONFIG_DIR")
    if env_dir:
        return Path(env_dir) / "config"
    return Path.home() / ".gemini" / "config"


def get_hooks_file() -> Path:
    return get_hooks_dir() / "hooks.json"


GLOBAL_CONFIG_DIR = get_hooks_dir()
GLOBAL_HOOKS_FILE = get_hooks_file()


def get_hook_definition(handler_path: str = None) -> dict:
    import sys
    if handler_path is None:
        handler_path = str(Path(__file__).resolve().parent / "hook_handler.py")

    py_bin = "python" if sys.platform == "win32" else "python3"
    escaped_path = handler_path.replace("\\", "/")

    return {
        "enabled": True,
        "PreToolUse": [
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": f'{py_bin} "{escaped_path}"',
                        "timeout": 15,
                    }
                ],
            }
        ],
    }


def install_hook(handler_path: str = None) -> bool:
    """向全局 hooks.json 安装或更新 AntiEnter hook（原子写入，解析损坏保护）"""
    try:
        hooks_dir = get_hooks_dir()
        hooks_file = get_hooks_file()
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hooks_data = {}

        if hooks_file.exists():
            try:
                with open(hooks_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        hooks_data = json.loads(content)
                        if not isinstance(hooks_data, dict):
                            print("安装 Hook 失败: 现有 hooks.json 根结构不是对象，中止修改以保护用户配置。")
                            return False
            except Exception as e:
                print(f"安装 Hook 失败: 现有 hooks.json 解析错误 ({e})，保留原文件不予覆盖。")
                return False

        hooks_data[HOOK_NAME] = get_hook_definition(handler_path)

        tmp_file = hooks_file.with_suffix(f".tmp.{os.getpid()}")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(hooks_data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, hooks_file)

        return True
    except Exception as e:
        print(f"安装 Hook 失败: {e}")
        return False


def uninstall_hook() -> bool:
    """从全局 hooks.json 中移除 AntiEnter hook（原子写入）"""
    try:
        hooks_file = get_hooks_file()
        if not hooks_file.exists():
            return True

        try:
            with open(hooks_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return True
                hooks_data = json.loads(content)
                if not isinstance(hooks_data, dict):
                    return True
        except Exception as e:
            print(f"卸载 Hook 失败: 现有 hooks.json 解析错误 ({e})，保留原文件。")
            return False

        if HOOK_NAME in hooks_data:
            del hooks_data[HOOK_NAME]
            tmp_file = hooks_file.with_suffix(f".tmp.{os.getpid()}")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(hooks_data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, hooks_file)

        return True
    except Exception as e:
        print(f"卸载 Hook 失败: {e}")
        return False


def is_hook_installed() -> bool:
    """检查 Hook 是否已安装且处于启用状态"""
    hooks_file = get_hooks_file()
    if not hooks_file.exists():
        return False
    try:
        with open(hooks_file, "r", encoding="utf-8") as f:
            hooks_data = json.load(f)
        hook = hooks_data.get(HOOK_NAME)
        return bool(hook and hook.get("enabled", True))
    except Exception:
        return False
