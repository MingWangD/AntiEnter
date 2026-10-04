"""
AntiEnter 声音反馈模块
在自动触发回车前发出轻微提示音，提醒用户正在自动放行。
支持 macOS 与 Windows，资源优先使用分发包内文件，移除开发者机器硬编码路径。
若音效资产缺失或播放器调用失败，安全回退系统提示音；关闭声音时零调用。
"""
from __future__ import annotations
import os
import sys
import subprocess
import threading
from pathlib import Path
from typing import Optional

# 动态导入配置
try:
    from src.config import load_config
except ImportError:
    from config import load_config


def resolve_sound_asset(theme: str) -> Optional[str]:
    """根据运行环境定位音效资源，支持源码、macOS Bundle 及 Windows 打包目录"""
    if theme in ("codex", "codex-notification"):
        curr = Path(__file__).resolve()
        candidates = [
            # 1. 源码与本地仓库/Windows 解压包布局
            curr.parent.parent / "assets" / "sounds" / "codex-notification.wav",
            curr.parent / "assets" / "sounds" / "codex-notification.wav",
            # 2. macOS App Bundle 布局 (Contents/Resources/sounds/...)
            curr.parent.parent / "sounds" / "codex-notification.wav",
            curr.parent.parent.parent / "sounds" / "codex-notification.wav",
            # 3. 用户主目录通用音效路径
            Path.home() / "Library" / "Sounds" / "codex-notification.wav",
        ]
        for p in candidates:
            if p.is_file():
                return str(p)
    return None


def play_cue_async():
    """异步非阻塞播放提示音（支持 Windows 和 macOS）"""
    config = load_config()
    if not config.get("play_sound", True):
        return

    def _play():
        theme = str(config.get("sound_theme", "codex-notification")).lower()
        codex_path = resolve_sound_asset(theme)

        if sys.platform == "win32":
            try:
                import winsound
                if theme in ("codex", "codex-notification") and codex_path and os.path.exists(codex_path):
                    winsound.PlaySound(codex_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                    return
                # Windows 兜底系统音效映射
                win_map = {
                    "tink": winsound.MB_ICONASTERISK,
                    "pop": winsound.MB_OK,
                    "ping": winsound.MB_ICONEXCLAMATION,
                    "glass": winsound.MB_ICONHAND,
                    "hero": winsound.MB_ICONASTERISK,
                    "sosumi": winsound.MB_ICONEXCLAMATION,
                }
                winsound.MessageBeep(win_map.get(theme, winsound.MB_ICONASTERISK))
            except Exception:
                pass
            return

        # macOS 音效映射
        if theme in ("codex", "codex-notification") and codex_path and os.path.exists(codex_path):
            try:
                subprocess.run(
                    ["/usr/bin/afplay", codex_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
                return
            except Exception:
                pass

        # 回退 macOS 系统预置音效
        mac_map = {
            "tink": "/System/Library/Sounds/Tink.aiff",
            "pop": "/System/Library/Sounds/Pop.aiff",
            "ping": "/System/Library/Sounds/Ping.aiff",
            "glass": "/System/Library/Sounds/Glass.aiff",
            "hero": "/System/Library/Sounds/Hero.aiff",
            "sosumi": "/System/Library/Sounds/Sosumi.aiff",
        }
        fallback_sound = mac_map.get(theme, "/System/Library/Sounds/Tink.aiff")
        if os.path.exists(fallback_sound):
            try:
                subprocess.run(
                    ["/usr/bin/afplay", fallback_sound],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
            except Exception:
                pass

    t = threading.Thread(target=_play, daemon=True)
    t.start()
