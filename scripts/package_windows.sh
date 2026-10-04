#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

echo "=== 打包 Windows 独立分发包 ==="

# 校验单一版本清单
if [ ! -f "version.json" ]; then
    echo "错误: 根目录缺少 version.json 版本清单文件"
    exit 1
fi

PYTHON_BIN="/usr/bin/python3"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

MANIFEST_VERSION=$($PYTHON_BIN -c "import json; print(json.load(open('version.json'))['version'].strip())")
if [ -n "$1" ] && [ "$1" != "$MANIFEST_VERSION" ]; then
    echo "错误: 命令行参数版本 ($1) 与 version.json ($MANIFEST_VERSION) 不一致！"
    exit 1
fi
VERSION="$MANIFEST_VERSION"

# 校验必需音效资产
if [ ! -f "assets/sounds/codex-notification.wav" ]; then
    echo "错误: 缺少必需音效资产 assets/sounds/codex-notification.wav，打包中止"
    exit 1
fi

WIN_DIST="dist/AntiEnter-Windows"
rm -rf "$WIN_DIST"
mkdir -p "$WIN_DIST/bin" "$WIN_DIST/src" "$WIN_DIST/hooks"

cp start_windows.bat "$WIN_DIST/"
cp stop_windows.bat "$WIN_DIST/"
cp README.md "$WIN_DIST/"
cp LICENSE "$WIN_DIST/"
cp version.json "$WIN_DIST/"
cp bin/antienter.bat "$WIN_DIST/bin/"
cp hooks/hooks.json "$WIN_DIST/hooks/"
cp src/*.py "$WIN_DIST/src/"
mkdir -p "$WIN_DIST/assets/sounds"
cp -R assets/sounds/* "$WIN_DIST/assets/sounds/"

cd dist
zip -r "AntiEnter-v${VERSION}-windows.zip" "AntiEnter-Windows" >/dev/null
cp "AntiEnter-v${VERSION}-windows.zip" "AntiEnter-windows.zip"
rm -rf "AntiEnter-Windows"
cd "$DIR"

echo "✓ Windows 分发包打包完成: dist/AntiEnter-v${VERSION}-windows.zip"
ls -lh dist/AntiEnter-v${VERSION}-windows.zip
