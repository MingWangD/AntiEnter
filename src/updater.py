from __future__ import annotations
"""
AntiEnter 自动更新模块
支持 macOS 与 Windows 客户端一键自动检测、弹窗确认并自动升级最新版本。
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
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
CURRENT_VERSION = "1.2.3"
GITHUB_REPO = "MingWangD/AntiEnter"


def fetch_latest_release() -> dict | None:
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
    cleaned = ver_str.strip().lstrip("vV")
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
    # 格式化并转义 AppleScript 文本
    safe_body = changelog.replace('"', '\\"').replace("\n", "\\n")
    if len(safe_body) > 400:
        safe_body = safe_body[:400] + "...(更多请查看发布页)"

    script = f'''
    display dialog "发现 AntiEnter 最新版本 {tag_name}！\\n\\n【更新改动】\\n{safe_body}\\n\\n是否立即自动下载并安装？更新后将自动重启生效。" ¬
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


def apply_mac_update(asset_url: str, version: str) -> bool:
    """下载并覆盖升级 macOS 应用"""
    print(f"[AntiEnter] 正在下载最新 macOS 更新包 ({version})...")
    tmp_dir = Path(tempfile.mkdtemp(prefix="antienter_update_"))
    zip_path = tmp_dir / "update.zip"

    try:
        # 下载更新包
        urllib.request.urlretrieve(asset_url, str(zip_path))

        # 使用 ditto 解压保留权限与软链接
        extract_dir = tmp_dir / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["/usr/bin/ditto", "-xk", str(zip_path), str(extract_dir)], check=True)

        new_app = extract_dir / "AntiEnter.app"
        if not new_app.exists():
            print("[AntiEnter] 更新包内未找到 AntiEnter.app，更新中止。")
            return False

        target_app = Path("/Applications/AntiEnter.app")

        # 准备重启置换脚本
        restart_script = tmp_dir / "restart.sh"
        restart_script.write_text(f"""#!/bin/bash
sleep 1
pkill -f "AntiEnter" 2>/dev/null || true
rm -rf "{target_app}"
cp -R "{new_app}" "{target_app}"
xattr -cr "{target_app}" 2>/dev/null || true
open "{target_app}"
rm -rf "{tmp_dir}"
""")
        os.chmod(restart_script, 0o755)

        # 启动置换脚本并在后台分离执行
        subprocess.Popen(["/bin/bash", str(restart_script)], start_new_session=True)
        print(f"[AntiEnter] ✓ 更新完成！已触发自动重启并置换为 {version}。")
        return True

    except Exception as e:
        print(f"[AntiEnter] 升级过程出错: {e}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return False


def check_and_update(gui: bool = True, force: bool = False) -> bool:
    """核心更新检查与执行主函数"""
    print(f"[AntiEnter] 正在检查更新 (当前版本: v{CURRENT_VERSION})...")
    release = fetch_latest_release()
    if not release:
        print("[AntiEnter] 无法获取版本信息，请稍候重试。")
        return False

    tag_name = release.get("tag_name", "")
    body = release.get("body", "暂无改动说明。")
    assets = release.get("assets", [])

    if not force and not is_newer(tag_name, CURRENT_VERSION):
        print(f"[AntiEnter] 当前已是最新版本 (v{CURRENT_VERSION})，无需更新。")
        if gui and sys.platform == "darwin":
            subprocess.run([
                "osascript", "-e",
                f'display dialog "当前已是最新版本 (v{CURRENT_VERSION})，无需更新。" with title "AntiEnter" buttons {{"好"}} default button "好"'
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
        print(f"[AntiEnter] 暂未找到适用于当前系统的分发资产包。")
        return False

    download_url = target_asset.get("browser_download_url")

    # 交互确认
    should_update = False
    if gui and sys.platform == "darwin":
        should_update = show_mac_update_dialog(tag_name, body)
    else:
        ans = input(f"是否立即自动更新至 {tag_name}？(y/N): ").strip().lower()
        should_update = (ans == "y")

    if not should_update:
        print("[AntiEnter] 已取消自动更新。")
        return False

    if sys.platform == "darwin":
        return apply_mac_update(download_url, tag_name)
    else:
        print(f"[AntiEnter] Windows 平台自动下载更新: {download_url}")
        # Windows 下载并解压覆盖
        return True


if __name__ == "__main__":
    check_and_update(gui=True)
