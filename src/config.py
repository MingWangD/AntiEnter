"""
AntiEnter 配置模块
定义缓冲延迟、危险指令黑名单、音效开关、支持的桌面与终端应用标识。
提供跨进程文件锁、原子写入与单实例生命周期登记。
"""
from __future__ import annotations
import os
import sys
import json
import math
import time
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any

ROOT_DIR = Path(__file__).resolve().parent.parent


def get_version() -> str:
    """读取集中管理的单一版本清单"""
    candidates = [
        ROOT_DIR / "version.json",
        Path(__file__).resolve().parent.parent / "version.json",
        Path(__file__).resolve().parent.parent.parent / "Resources" / "version.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "version" in data:
                        return str(data["version"]).strip()
            except Exception:
                pass
    return "1.2.5"


SUPPORTED_THEMES = {
    "codex-notification",
    "codex",
    "tink",
    "pop",
    "ping",
    "glass",
    "hero",
    "sosumi",
}

# 默认配置
DEFAULT_CONFIG: dict[str, Any] = {
    # 统一全局启用开关：若为 False 则停止所有自动确认动作
    "enabled": True,
    # 自动回车前的缓冲延时（秒），默认 1.0s
    "buffer_delay": 1.0,
    # 触发自动回车时是否播放系统提示音
    "play_sound": True,
    # 提示音主题：可选 "codex-notification" (默认), "tink", "pop", "ping", "glass", "hero", "sosumi"
    "sound_theme": "codex-notification",
    # 高危指令熔断黑名单：匹配到这些模式时不自动放行，保留人工弹窗审批
    "safety_fuse_enabled": True,
    # 动作运行代次（用于暂停/启停时代次递增使过期排队动作失效）
    "generation": 1,
    "dangerous_patterns": [
        # Unix / Git / 通用删除
        "rm -rf",
        "rm -r",
        "rm -f",
        "rm ",
        "rmdir",
        "git reset --hard",
        "git clean -f",
        # Windows 原生删除与磁盘危险操作
        "del /s",
        "del /f",
        "del /q",
        "rd /s",
        "rmdir /s",
        "Remove-Item",
        "format ",
        "diskpart",
        # 破坏性命令与格式化
        "mkfs",
        "dd if=",
        ":(){ :|:& };:",
        "> /dev/sda",
        "chmod -R 777 /",
        "shutdown",
        "reboot",
        "init 0",
        "kill -9 -1",
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
    # CLI 终端应用受支持的名称（macOS + Windows）
    "terminal_targets": [
        "Terminal",
        "iTerm2",
        "iTerm",
        "Ghostty",
        "kitty",
        "Alacritty",
        "WezTerm",
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "WindowsTerminal.exe",
        "Windows Terminal",
        "ConEmu",
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


def get_runtime_dir() -> Path:
    env_dir = os.environ.get("ANTIENTER_CONFIG_DIR")
    if env_dir:
        d = Path(env_dir)
        d.mkdir(parents=True, exist_ok=True)
        return d
    gemini_dir = Path.home() / ".gemini"
    gemini_dir.mkdir(parents=True, exist_ok=True)
    return gemini_dir


def get_config_path() -> Path:
    return get_runtime_dir() / "antienter_config.json"


def get_config_lock() -> Path:
    return get_runtime_dir() / "antienter_config.lock"


def get_instance_file() -> Path:
    return get_runtime_dir() / "antienter_instance.json"


def get_decision_file() -> Path:
    return get_runtime_dir() / "antienter_decision.json"


RUNTIME_DIR = get_runtime_dir()
CONFIG_PATH = get_config_path()
CONFIG_LOCK = get_config_lock()
INSTANCE_FILE = get_instance_file()
DECISION_FILE = get_decision_file()

DEFAULT_CONFIG["log_file"] = str(RUNTIME_DIR / "antienter.log")
DEFAULT_CONFIG["pid_file"] = str(RUNTIME_DIR / "antienter.pid")


def validate_config(conf: dict[str, Any]) -> dict[str, Any]:
    """校验并清洗配置，防止异常值导致守护进程故障"""
    cleaned = DEFAULT_CONFIG.copy()
    cleaned.update(conf)

    # 校验 enabled
    if not isinstance(cleaned.get("enabled"), bool):
        cleaned["enabled"] = True

    # 校验 buffer_delay
    delay = cleaned.get("buffer_delay")
    if not isinstance(delay, (int, float)) or math.isnan(delay) or math.isinf(delay) or delay < 0:
        cleaned["buffer_delay"] = 1.0
    else:
        cleaned["buffer_delay"] = float(delay)

    # 校验 play_sound
    if not isinstance(cleaned.get("play_sound"), bool):
        cleaned["play_sound"] = True

    # 校验 sound_theme
    theme = str(cleaned.get("sound_theme", "")).lower()
    if theme not in SUPPORTED_THEMES:
        cleaned["sound_theme"] = "codex-notification"

    # 校验 safety_fuse_enabled (默认开启熔断保护安全)
    if not isinstance(cleaned.get("safety_fuse_enabled"), bool):
        cleaned["safety_fuse_enabled"] = True

    # 校验 generation
    gen = cleaned.get("generation")
    if not isinstance(gen, int) or gen < 1:
        cleaned["generation"] = 1

    rdir = get_runtime_dir()
    cleaned["log_file"] = str(rdir / "antienter.log")
    cleaned["pid_file"] = str(rdir / "antienter.pid")

    return cleaned


import threading

_PROC_LOCK = threading.RLock()
_LOCK_REFS: dict[str, int] = {}
_LOCK_FDS: dict[str, int] = {}


class _FileLock:
    """进程内可重入、跨进程安全的排他文件锁"""
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.key = str(lock_path.resolve())

    def __enter__(self):
        _PROC_LOCK.acquire()
        try:
            count = _LOCK_REFS.get(self.key, 0)
            if count == 0:
                self.lock_path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR)
                if sys.platform != "win32":
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX)
                _LOCK_FDS[self.key] = fd
            _LOCK_REFS[self.key] = count + 1
        except Exception:
            _PROC_LOCK.release()
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            count = _LOCK_REFS.get(self.key, 0)
            if count <= 1:
                _LOCK_REFS.pop(self.key, None)
                fd = _LOCK_FDS.pop(self.key, None)
                if fd is not None:
                    try:
                        if sys.platform != "win32":
                            import fcntl
                            fcntl.flock(fd, fcntl.LOCK_UN)
                        os.close(fd)
                    except Exception:
                        pass
            else:
                _LOCK_REFS[self.key] = count - 1
        finally:
            _PROC_LOCK.release()


def load_config() -> dict[str, Any]:
    """加载配置，文件损坏或不可读时安全回退默认并标记"""
    lock_file = get_config_lock()
    cfg_path = get_config_path()
    with _FileLock(lock_file):
        config = DEFAULT_CONFIG.copy()
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    user_conf = json.load(f)
                    if isinstance(user_conf, dict):
                        config.update(user_conf)
            except Exception:
                # 记录损坏日志，自动保护性回退
                pass
        return validate_config(config)


def save_config(config: dict[str, Any]) -> bool:
    """原子写入保存配置，防止并发写入产生半截文件"""
    validated = validate_config(config)
    lock_file = get_config_lock()
    cfg_path = get_config_path()
    with _FileLock(lock_file):
        try:
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            # 原子写入：先写入同目录临时文件再 rename 覆盖
            temp_file = cfg_path.with_suffix(f".tmp.{os.getpid()}_{time.time()}")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(validated, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, cfg_path)
            return True
        except (OSError, PermissionError) as e:
            sys.stderr.write(f"[AntiEnter] 保存配置失败 ({cfg_path}): {e}\n")
            return False


def update_config(updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    """仅更新请求修改的字段，原子保存并返回最新配置。若保存失败返回 None"""
    lock_file = get_config_lock()
    with _FileLock(lock_file):
        current = load_config()
        current.update(updates)
        if save_config(current):
            return current
        return None


def advance_generation() -> int:
    """递增代次标记，使先前排队的延时任务全部失效。若保存失败返回 -1"""
    lock_file = get_config_lock()
    with _FileLock(lock_file):
        current = load_config()
        next_gen = current.get("generation", 1) + 1
        current["generation"] = next_gen
        if save_config(current):
            return next_gen
        return -1


# ==================== 统一单实例运行登记 ====================

def is_pid_alive(pid: int) -> bool:
    """跨平台精准检查进程存活性"""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259

            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                # 检查权限：如果是权限受限 (ERROR_ACCESS_DENIED=5)，说明进程确实存在但无权访问
                err = kernel32.GetLastError()
                return err == 5
            try:
                exit_code = wintypes.DWORD()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return exit_code.value == STILL_ACTIVE
                return False
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            # 进程存在但无权限发送信号
            return True
        except (ProcessLookupError, OSError):
            return False


def get_active_instance() -> Optional[dict[str, Any]]:
    """获取当前已登记并实际存活的单一实例信息"""
    lock_file = get_config_lock()
    inst_file = get_instance_file()
    with _FileLock(lock_file):
        if not inst_file.exists():
            return None
        try:
            with open(inst_file, "r", encoding="utf-8") as f:
                info = json.load(f)
            pid = info.get("pid")
            if isinstance(pid, int) and is_pid_alive(pid):
                return info
            # 进程已死亡，清理陈旧记录
            inst_file.unlink(missing_ok=True)
            return None
        except Exception:
            inst_file.unlink(missing_ok=True)
            return None


def register_instance(pid: int, entry: str) -> bool:
    """登记单一运行实例（App/CLI 共享）"""
    lock_file = get_config_lock()
    inst_file = get_instance_file()
    with _FileLock(lock_file):
        existing = get_active_instance()
        if existing and existing.get("pid") != pid:
            # 已有存活实例
            return False
        info = {
            "pid": pid,
            "entry": entry,
            "user": os.getenv("USER", os.getenv("USERNAME", "unknown")),
            "started_at": time.time(),
        }
        try:
            inst_file.parent.mkdir(parents=True, exist_ok=True)
            temp = inst_file.with_suffix(f".tmp.{pid}_{time.time()}")
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(info, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, inst_file)
            return True
        except Exception:
            return False


def unregister_instance(pid: Optional[int] = None) -> None:
    """注销实例登记"""
    lock_file = get_config_lock()
    inst_file = get_instance_file()
    with _FileLock(lock_file):
        if not inst_file.exists():
            return
        try:
            if pid is not None:
                with open(inst_file, "r", encoding="utf-8") as f:
                    info = json.load(f)
                if info.get("pid") != pid:
                    return
            inst_file.unlink(missing_ok=True)
        except Exception:
            inst_file.unlink(missing_ok=True)


def consume_decision_token(token_id: Optional[str] = None) -> bool:
    """原子消费 antienter_decision.json 中的活跃令牌，防止重复重放"""
    lock_file = get_config_lock()
    dec_file = get_decision_file()
    with _FileLock(lock_file):
        if not dec_file.exists():
            return False
        try:
            with open(dec_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return False
            if data.get("consumed", False):
                return False
            if token_id is not None and data.get("token_id") != token_id:
                return False
            data["consumed"] = True
            data["consumed_at"] = time.time()
            data["consumed_by"] = os.getpid()
            temp = dec_file.with_suffix(f".tmp.{os.getpid()}_{time.time()}")
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, dec_file)
            return True
        except Exception:
            return False


def get_active_decision_token(expected_tool: Optional[str] = None, max_age: float = 10.0) -> Optional[dict]:
    """读取并校验当前未消费的有效放行令牌"""
    dec_file = get_decision_file()
    if not dec_file.exists():
        return None
    try:
        with open(dec_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if data.get("decision") != "allow":
            return None
        if data.get("consumed", False):
            return None
        ts = float(data.get("timestamp", 0))
        if time.time() - ts >= max_age:
            return None
        actual_tool = data.get("canonical_tool") or data.get("tool")
        if not isinstance(actual_tool, str) or not actual_tool.strip():
            return None
        if expected_tool is not None:
            norm_expected = expected_tool.split(":")[-1].strip().lower()
            norm_actual = actual_tool.split(":")[-1].strip().lower()
            if norm_actual != norm_expected:
                return None
        return data
    except Exception:
        return None
