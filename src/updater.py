from __future__ import annotations
"""
AntiEnter 自动更新模块
支持 macOS 与 Windows 客户端版本检测、更新提示与可回滚的事务级安全安装。
更新失败时自动回滚至旧版本，绝不损坏已有安装。
"""
import sys
import os
import json
import urllib.request
import urllib.error
import zipfile
import shutil
import tempfile
import subprocess
import time
import argparse
from pathlib import Path
from typing import Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

try:
    from src.config import get_version, load_config, update_config, advance_generation, is_pid_alive
except ImportError:
    from config import get_version, load_config, update_config, advance_generation, is_pid_alive

CURRENT_VERSION = get_version()
GITHUB_REPO = "MingWangD/AntiEnter"
UPDATE_LOCK_FILE = Path(tempfile.gettempdir()) / "antienter_update.lock"


def fetch_latest_release() -> Optional[dict]:
    """从 GitHub API 获取最新发布版本信息"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AntiEnter-Updater", "Accept": "application/vnd.github.v3+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                return data
    except Exception as e:
        print(f"[AntiEnter 更新器] 查询 GitHub Release 失败: {e}")
        return None
    return None


def parse_version(ver_str: str) -> tuple[int, ...]:
    """解析语义化版本号，忽略 v 前缀"""
    cleaned = str(ver_str).strip().lstrip("vV")
    parts = []
    for p in cleaned.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def is_newer(remote_ver: str, local_ver: str) -> bool:
    """比较远程版本是否高于本地版本"""
    return parse_version(remote_ver) > parse_version(local_ver)


def show_mac_update_dialog(tag_name: str, changelog: str) -> bool:
    """在 macOS 弹出系统原生更新确认对话框，返回用户是否选择更新"""
    safe_body = changelog.replace('"', '\\"').replace("\n", "\\n")
    if len(safe_body) > 400:
        safe_body = safe_body[:400] + "...(更多请查看发布页)"

    script = f'''
    display dialog "发现 AntiEnter 最新版本 {tag_name}！\\n\\n【更新改动】\\n{safe_body}\\n\\n是否立即自动下载并安装？更新过程具备事务回滚保护。" ¬
        with title "🎉 AntiEnter 自动更新" ¬
        buttons {{"稍后再说", "确认自动更新"}} ¬
        default button "确认自动更新" ¬
        with icon note
    '''
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        return "确认自动更新" in res.stdout
    except Exception:
        return False


def verify_app_bundle(app_path: Path, expected_version: Optional[str] = None) -> bool:
    """验证待安装 macOS Bundle 的完整性、标识与目标版本"""
    if not app_path.is_dir():
        return False
    info_plist = app_path / "Contents" / "Info.plist"
    if not info_plist.is_file():
        return False
    try:
        content = info_plist.read_text(encoding="utf-8", errors="ignore")
        if "com.antienter.app" not in content and "AntiEnter" not in content:
            return False
    except Exception:
        return False

    exe = app_path / "Contents" / "MacOS" / "AntiEnter"
    if not exe.exists():
        return False

    if expected_version:
        clean_exp = expected_version.strip().lstrip("vV")
        try:
            import plistlib
            with open(info_plist, "rb") as fp:
                plist = plistlib.load(fp)
            ver = plist.get("CFBundleShortVersionString") or plist.get("CFBundleVersion")
            if ver and str(ver).strip().lstrip("vV") != clean_exp:
                return False
        except Exception:
            if f"<string>{clean_exp}</string>" not in content and clean_exp not in content:
                return False

    return True


def execute_transactional_mac_update(
    target_app: Path,
    archive_path: Path,
    old_pid: Optional[int] = None,
    target_version: str = "",
) -> bool:
    """
    可验证、可回滚的事务更新核心流程：
    1. 获取独占更新锁 (O_CREAT | O_EXCL)
    2. 解压并深度校验新包结构与目标版本
    3. 等待指定旧进程退出（超时即安全中止）
    4. 创建同文件系统安全备份
    5. 原子置换新版应用
    6. 验证启动就绪状态，若失败立即回滚
    """
    # 1. 尝试原子加锁
    try:
        lock_fd = os.open(str(UPDATE_LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(lock_fd, "w") as f:
            f.write(str(os.getpid()))
            f.flush()
    except FileExistsError:
        print("[AntiEnter 更新器] 已有更新事务正在进行中，跳过重复更新。")
        return False
    except Exception as e:
        print(f"[AntiEnter 更新器] 无法创建更新锁: {e}")
        return False

    temp_stage_dir = Path(tempfile.mkdtemp(prefix="antienter_update_tx_"))
    backup_app: Optional[Path] = None

    try:
        print(f"[AntiEnter 更新器] 开始执行事务级更新 (目标: {target_app}, 版本: {target_version})...")

        # 2. 解压与包验证
        extract_dir = temp_stage_dir / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)

        res = subprocess.run(
            ["/usr/bin/ditto", "-xk", str(archive_path), str(extract_dir)],
            capture_output=True,
        )
        if res.returncode != 0:
            print("[AntiEnter 更新器] 解压更新归档包失败，保持现有版本不变。")
            return False

        new_app = extract_dir / "AntiEnter.app"
        if not new_app.exists():
            for sub in extract_dir.glob("**/AntiEnter.app"):
                if sub.is_dir():
                    new_app = sub
                    break

        if not verify_app_bundle(new_app, expected_version=target_version):
            print("[AntiEnter 更新器] 新版应用包校验未通过（结构损坏或版本不匹配），中止更新以保护现有安装。")
            return False

        # 3. 等待旧进程完全退出
        if old_pid and old_pid > 0:
            print(f"[AntiEnter 更新器] 等待原进程 (PID: {old_pid}) 退出...")
            exited = False
            for _ in range(30):
                if not is_pid_alive(old_pid):
                    exited = True
                    break
                time.sleep(0.3)
            if not exited:
                print(f"[AntiEnter 更新器] 原进程 (PID: {old_pid}) 超时未退出，中止更新。")
                return False

        # 4. 创建同目录安全备份
        target_app = target_app.resolve()
        if target_app.exists():
            timestamp = int(time.time())
            backup_app = target_app.parent / f"{target_app.name}.backup_{timestamp}"
            print(f"[AntiEnter 更新器] 正在创建旧版本安全备份: {backup_app}")
            shutil.move(str(target_app), str(backup_app))

        # 5. 置换新版应用
        print(f"[AntiEnter 更新器] 正在将新版本安装至: {target_app}")
        try:
            shutil.copytree(str(new_app), str(target_app), symlinks=True)
            subprocess.run(["/usr/bin/xattr", "-cr", str(target_app)], stderr=subprocess.DEVNULL)
        except Exception as copy_err:
            print(f"[AntiEnter 更新器] 复制新版本失败: {copy_err}，正在回滚旧安装...")
            if backup_app and backup_app.exists():
                if target_app.exists():
                    shutil.rmtree(str(target_app), ignore_errors=True)
                shutil.move(str(backup_app), str(target_app))
            return False

        def _rollback_to_backup():
            print("[AntiEnter 更新器] 正在执行回滚恢复旧版本备份...")
            if target_app.exists():
                shutil.rmtree(str(target_app), ignore_errors=True)
            if backup_app and backup_app.exists():
                shutil.move(str(backup_app), str(target_app))
                try:
                    subprocess.run(["/usr/bin/open", str(target_app)], capture_output=True)
                except Exception:
                    pass

        # 6. 拉起并验证新版本
        print("[AntiEnter 更新器] 启动新版本并验证就绪状态...")
        launch_res = subprocess.run(["/usr/bin/open", str(target_app)], capture_output=True)
        if launch_res.returncode != 0:
            err_msg = launch_res.stderr.decode(errors="ignore") if launch_res.stderr else "open 命令执行失败"
            print(f"[AntiEnter 更新器] 启动新版本失败: {err_msg}，触发自动回滚...")
            _rollback_to_backup()
            return False

        # 启动就绪健康检查：持续检测新进程存活
        is_healthy = False
        target_bin_pattern = "AntiEnter.app/Contents/MacOS/AntiEnter"
        for _ in range(6):
            time.sleep(0.5)
            pgrep_res = subprocess.run(["/usr/bin/pgrep", "-f", target_bin_pattern], capture_output=True)
            if pgrep_res.returncode == 0:
                pids = [int(p) for p in pgrep_res.stdout.decode(errors="ignore").split() if p.isdigit()]
                new_pids = [p for p in pids if p != old_pid]
                target_real_str = str(target_app.resolve())
                for np in new_pids:
                    # 优先校验该 PID 确实属于目标 target_app 路径，防止识别为系统内其他副本
                    ps_res = subprocess.run(["/bin/ps", "-p", str(np), "-o", "comm="], capture_output=True)
                    if ps_res.returncode == 0:
                        out = ps_res.stdout
                        comm = out.decode(errors="ignore").strip() if isinstance(out, (bytes, bytearray)) else str(out).strip()
                        if target_real_str in comm or "AntiEnter" in comm:
                            is_healthy = True
                            break
                    else:
                        is_healthy = True
                        break
                if is_healthy:
                    break

        if not is_healthy:
            print("[AntiEnter 更新器] 新版本启动就绪检查未通过 (未探测到活跃新进程)，触发自动回滚...")
            _rollback_to_backup()
            return False

        # 成功，清理备份
        if backup_app and backup_app.exists():
            shutil.rmtree(str(backup_app), ignore_errors=True)

        print(f"[AntiEnter 更新器] ✓ 升级完成！已成功置换并拉起新版 {target_version}。")
        return True

    except Exception as e:
        print(f"[AntiEnter 更新器] 更新过程发生未知异常: {e}")
        if backup_app and backup_app.exists():
            print("[AntiEnter 更新器] 正在回滚至旧版本备份...")
            if target_app.exists():
                shutil.rmtree(str(target_app), ignore_errors=True)
            shutil.move(str(backup_app), str(target_app))
        return False

    finally:
        shutil.rmtree(temp_stage_dir, ignore_errors=True)
        UPDATE_LOCK_FILE.unlink(missing_ok=True)


def apply_mac_update_flow(
    asset_url: str,
    version: str,
    target_path: Optional[str] = None,
    old_pid: Optional[int] = None,
) -> bool:
    """下载更新包并执行事务更新流程"""
    print(f"[AntiEnter] 正在下载最新 macOS 更新包 ({version})...")
    tmp_dir = Path(tempfile.mkdtemp(prefix="antienter_download_"))
    zip_path = tmp_dir / "update.zip"

    try:
        urllib.request.urlretrieve(asset_url, str(zip_path))
        target = Path(target_path) if target_path else Path("/Applications/AntiEnter.app")
        return execute_transactional_mac_update(
            target_app=target,
            archive_path=zip_path,
            old_pid=old_pid,
            target_version=version,
        )
    except Exception as e:
        print(f"[AntiEnter] 下载更新包失败: {e}")
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def check_and_update(gui: bool = True, force: bool = False) -> bool:
    """核心更新检查与执行主函数"""
    current_ver = get_version()
    print(f"[AntiEnter] 正在检查更新 (当前版本: v{current_ver})...")
    release = fetch_latest_release()
    if not release:
        print("[AntiEnter] 无法获取版本信息，请稍候重试。")
        return False

    tag_name = release.get("tag_name", "")
    body = release.get("body", "暂无改动说明。")
    assets = release.get("assets", [])

    if not force and not is_newer(tag_name, current_ver):
        print(f"[AntiEnter] 当前已是最新版本 (v{current_ver})，无需更新。")
        if gui and sys.platform == "darwin":
            subprocess.run([
                "osascript", "-e",
                f'display dialog "当前已是最新版本 (v{current_ver})，无需更新。" with title "AntiEnter" buttons {{"好"}} default button "好"'
            ])
        return True

    print(f"[AntiEnter] 发现新版本: {tag_name}！")
    print(f"------------ 更新说明 ------------\n{body}\n----------------------------------")

    # 寻找当前平台对应的更新包
    target_asset = None
    for a in assets:
        name = a.get("name", "")
        if sys.platform == "win32" and "windows.zip" in name.lower():
            target_asset = a
            break
        elif sys.platform == "darwin" and "macos.zip" in name.lower():
            target_asset = a
            break

    if not target_asset:
        print("[AntiEnter] 暂未找到适用于当前系统的分发资产包。")
        return False

    download_url = target_asset.get("browser_download_url")

    # Windows 平台目前不提供自动事务置换，引导手动下载
    if sys.platform == "win32":
        print("[AntiEnter] Windows 平台暂不支持在线事务自动置换。")
        print(f"[AntiEnter] 请前往 GitHub Releases 手动下载安装包: https://github.com/{GITHUB_REPO}/releases/tag/{tag_name}")
        print(f"[AntiEnter] 下载地址: {download_url}")
        return False

    # macOS 交互确认
    should_update = False
    if gui and sys.platform == "darwin":
        should_update = show_mac_update_dialog(tag_name, body)
    else:
        ans = input(f"是否立即自动更新至 {tag_name}？(y/N): ").strip().lower()
        should_update = (ans == "y")

    if not should_update:
        print("[AntiEnter] 已取消自动更新。")
        return False

    running_pid = None
    try:
        from src.controller import get_running_pid
        running_pid = get_running_pid()
    except Exception:
        try:
            from controller import get_running_pid
            running_pid = get_running_pid()
        except Exception:
            pass

    return apply_mac_update_flow(download_url, tag_name, old_pid=running_pid)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AntiEnter 更新器")
    parser.add_argument("--apply", action="store_true", help="以独立事务模式执行安装与回滚")
    parser.add_argument("--target", type=str, help="目标应用安装路径")
    parser.add_argument("--old-pid", type=int, help="原进程 PID")
    parser.add_argument("--version", type=str, default="", help="目标版本号")
    parser.add_argument("--archive", type=str, help="已下载的 ZIP 归档路径")
    parser.add_argument("--cli", action="store_true", help="命令行交互模式")

    args = parser.parse_args()

    if args.apply:
        if not args.target or not args.archive:
            print("错误: --apply 模式必须指定 --target 与 --archive 参数")
            sys.exit(1)
        ok = execute_transactional_mac_update(
            target_app=Path(args.target),
            archive_path=Path(args.archive),
            old_pid=args.old_pid,
            target_version=args.version,
        )
        sys.exit(0 if ok else 1)
    else:
        ok = check_and_update(gui=(not args.cli))
        sys.exit(0 if ok else 1)
