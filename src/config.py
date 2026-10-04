"""
AntiEnter 配置模块
定义缓冲延迟、危险指令黑名单、音效开关、支持的桌面与终端应用标识。
"""
import os
import json
from pathlib import Path

# 默认配置
DEFAULT_CONFIG = {
    # 自动回车前的缓冲延时（秒），用户指定 1.0s
    "buffer_delay": 1.0,
    # 触发自动回车时是否播放系统提示音
    "play_sound": True,
    # 提示音路径（macOS 经典音效）
    "sound_file": "/System/Library/Sounds/Tink.aiff",
    # 高危指令熔断黑名单：匹配到这些模式时不自动放行，保留人工弹窗审批
    "safety_fuse_enabled": True,
    "dangerous_patterns": [
        "rm -rf /",
        "rm -rf ~",
        "rm -rf *",
        "mkfs",
        "dd if=",
        ":(){ :|:& };:",
        "> /dev/sda",
        "chmod -R 777 /",
        "shutdown",
        "reboot",
        "init 0",
    ],
    # 桌面端受支持的进程/应用名称与 Bundle ID 关键词
    "desktop_targets": [
        "Antigravity",
        "Antigravity Tools",
        "Gemini",
        "Electron",
        "Code",
        "Cursor",
    ],
    # CLI 终端应用受支持的名称
    "terminal_targets": [
        "Terminal",
        "iTerm2",
        "iTerm",
        "Ghostty",
        "kitty",
        "Alacritty",
        "WezTerm",
    ],
    # CLI 终端提示匹配关键词（正则或子串）
    "cli_prompt_patterns": [
        r"\[y/n\]",
        r"\[Y/n\]",
        r"\[y/N\]",
        r"proceed\?",
        r"continue\?",
        r"press enter to",
        r"select an option",
        r"confirm\?",
    ],
}


def _resolve_dir():
    gemini_dir = Path.home() / ".gemini"
    try:
        gemini_dir.mkdir(parents=True, exist_ok=True)
        test_file = gemini_dir / ".write_test"
        test_file.touch()
        test_file.unlink(missing_ok=True)
        return gemini_dir
    except (OSError, PermissionError):
        fallback = Path(__file__).resolve().parent.parent / ".antienter_runtime"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

RUNTIME_DIR = _resolve_dir()
CONFIG_PATH = RUNTIME_DIR / "antienter_config.json"

DEFAULT_CONFIG["log_file"] = str(RUNTIME_DIR / "antienter.log")
DEFAULT_CONFIG["pid_file"] = str(RUNTIME_DIR / "antienter.pid")


def load_config() -> dict:
    """加载配置，不存在则回退至默认配置"""
    config = DEFAULT_CONFIG.copy()
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_conf = json.load(f)
                config.update(user_conf)
        except Exception:
            pass
    return config


def save_config(config: dict) -> None:
    """持久化保存配置"""
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except (OSError, PermissionError):
        # 回退至项目目录本地保存
        local_cfg = Path(__file__).resolve().parent.parent / ".antienter_runtime" / "antienter_config.json"
        local_cfg.parent.mkdir(parents=True, exist_ok=True)
        with open(local_cfg, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
