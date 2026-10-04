"""
AntiEnter 声音反馈模块
在自动触发回车前发出轻微提示音，提醒用户正在自动放行。
"""
import os
import subprocess
import threading
from .config import load_config


def play_cue_async():
    """异步非阻塞播放提示音"""
    config = load_config()
    if not config.get("play_sound", True):
        return

    sound_file = config.get("sound_file", "/System/Library/Sounds/Tink.aiff")
    if not os.path.exists(sound_file):
        return

    def _play():
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
