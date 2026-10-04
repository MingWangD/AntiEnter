#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

echo "=== 打包 Windows 独立分发包 ==="

VERSION="${1:-1.2.0}"
WIN_DIST="dist/AntiEnter-Windows"
rm -rf "$WIN_DIST" dist/AntiEnter-*-windows.zip dist/AntiEnter-windows.zip
mkdir -p "$WIN_DIST/bin" "$WIN_DIST/src" "$WIN_DIST/hooks"

cp start_windows.bat "$WIN_DIST/"
cp stop_windows.bat "$WIN_DIST/"
cp README.md "$WIN_DIST/"
cp LICENSE "$WIN_DIST/"
cp bin/antienter.bat "$WIN_DIST/bin/"
cp hooks/hooks.json "$WIN_DIST/hooks/"
cp src/*.py "$WIN_DIST/src/"
mkdir -p "$WIN_DIST/assets/sounds"
cp -R assets/sounds/* "$WIN_DIST/assets/sounds/" 2>/dev/null || true

cd dist
zip -r "AntiEnter-v${VERSION}-windows.zip" "AntiEnter-Windows" >/dev/null
cp "AntiEnter-v${VERSION}-windows.zip" "AntiEnter-windows.zip"
rm -rf "AntiEnter-Windows"
cd "$DIR"

echo "✓ Windows 分发包打包完成: dist/AntiEnter-v${VERSION}-windows.zip"
ls -lh dist/AntiEnter-v${VERSION}-windows.zip
