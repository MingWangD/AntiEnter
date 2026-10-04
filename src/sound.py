"""
AntiEnter 声音反馈模块
在自动触发回车前发出轻微提示音，提醒用户正在自动放行。
"""
import os
import subprocess
import threading
from .config import load_config


def play_cue_async():
    """异步非阻塞播放提示音（支持 Windows 和 macOS）"""
    config = load_config()
    if not config.get("play_sound", True):
        return

    def _play():
        import sys
        from pathlib import Path
        theme = config.get("sound_theme", "codex-notification").lower()
        
        # 寻找 codex-notification.wav 路径
        codex_candidates = [
            Path(__file__).resolve().parent.parent / "assets" / "sounds" / "codex-notification.wav",
            Path.home() / "Library/Sounds/codex-notification.wav",
            Path("/Applications/AntiEnter.app/Contents/Resources/sounds/codex-notification.wav"),
            Path("/Applications/ChatGPT.app/Contents/Resources/codex-notification.wav"),
        ]
        codex_path = next((str(p) for p in codex_candidates if p.exists()), None)

        if sys.platform == "win32":
            try:
                import winsound
                if theme in ("codex", "codex-notification") and codex_path and os.path.exists(codex_path):
                    winsound.PlaySound(codex_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                    return
                # Windows 兜底音效映射
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

        # macOS / Unix 音效映射
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

        mac_map = {
            "tink": "/System/Library/Sounds/Tink.aiff",
            "pop": "/System/Library/Sounds/Pop.aiff",
            "ping": "/System/Library/Sounds/Ping.aiff",
            "glass": "/System/Library/Sounds/Glass.aiff",
            "hero": "/System/Library/Sounds/Hero.aiff",
            "sosumi": "/System/Library/Sounds/Sosumi.aiff",
            "codex-notification": codex_path or "/System/Library/Sounds/Tink.aiff"
        }
        sound_file = mac_map.get(theme, mac_map["codex-notification"])
        
        if os.path.exists(sound_file):
            try:
                subprocess.run(
                    ["/usr/bin/afplay", sound_file],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
            except Exception:
                pass

    t = threading.Thread(target=_play, daemon=True)
    t.start()
