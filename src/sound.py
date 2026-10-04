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
        theme = config.get("sound_theme", "tink").lower()
        
        if sys.platform == "win32":
            try:
                import winsound
                # Windows 音效映射
                win_map = {
                    "tink": winsound.MB_ICONASTERISK,
                    "pop": winsound.MB_OK,
                    "ping": winsound.MB_ICONEXCLAMATION,
                    "glass": winsound.MB_ICONHAND
                }
                winsound.MessageBeep(win_map.get(theme, winsound.MB_ICONASTERISK))
            except Exception:
                pass
            return

        # macOS / Unix 音效映射
        if theme == "antigravity":
            try:
                subprocess.run(
                    ["/usr/bin/osascript", "-e", "beep"],
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
            "antigravity": "/System/Library/Sounds/Tink.aiff"
        }
        sound_file = mac_map.get(theme, mac_map["tink"])
        
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
