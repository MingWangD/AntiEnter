#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

echo "=== 开始构建 AntiEnter.app macOS 应用程序 ==="

# 准备构建目录
APP_BUNDLE="dist/AntiEnter.app"
CONTENTS="$APP_BUNDLE/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
CACHE_DIR="$DIR/.cache"
VERSION="${1:-1.2.0}"

rm -rf "$APP_BUNDLE" dist/*.zip dist/*.dmg
mkdir -p "$MACOS" "$RESOURCES/scripts" "$CACHE_DIR"

# 1. 生成高分辨率应用图标
echo "[1/5] 渲染应用图标与 ICNS..."
swift -module-cache-path "$CACHE_DIR" scripts/create_icon.swift "$CACHE_DIR/icon_1024.png"

ICONSET="$CACHE_DIR/AppIcon.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"

sips -z 16 16     "$CACHE_DIR/icon_1024.png" --out "$ICONSET/icon_16x16.png" >/dev/null
sips -z 32 32     "$CACHE_DIR/icon_1024.png" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
sips -z 32 32     "$CACHE_DIR/icon_1024.png" --out "$ICONSET/icon_32x32.png" >/dev/null
sips -z 64 64     "$CACHE_DIR/icon_1024.png" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
sips -z 128 128   "$CACHE_DIR/icon_1024.png" --out "$ICONSET/icon_128x128.png" >/dev/null
sips -z 256 256   "$CACHE_DIR/icon_1024.png" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
sips -z 256 256   "$CACHE_DIR/icon_1024.png" --out "$ICONSET/icon_256x256.png" >/dev/null
sips -z 512 512   "$CACHE_DIR/icon_1024.png" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
sips -z 512 512   "$CACHE_DIR/icon_1024.png" --out "$ICONSET/icon_512x512.png" >/dev/null
cp "$CACHE_DIR/icon_1024.png" "$ICONSET/icon_512x512@2x.png"

iconutil -c icns "$ICONSET" -o "$RESOURCES/AppIcon.icns"
echo "  ✓ 图标打包完成: $RESOURCES/AppIcon.icns"

# 2. 编译 Swift 可执行程序
echo "[2/5] 编译 Swift 菜单栏原生应用..."
swiftc -O -module-cache-path "$CACHE_DIR" \
    src/app/main.swift \
    -o "$MACOS/AntiEnter"

chmod +x "$MACOS/AntiEnter"
echo "  ✓ 二进制生成完成: $MACOS/AntiEnter"

# 3. 复制依赖脚本与模板
echo "[3/5] 打包嵌入 Python 脚本与配置模板..."
mkdir -p "$RESOURCES/scripts/src"
cp src/hook_handler.py "$RESOURCES/scripts/"
cp src/config.py "$RESOURCES/scripts/"
cp src/sound.py "$RESOURCES/scripts/"
cp src/cli_runner.py "$RESOURCES/scripts/"
cp src/*.py "$RESOURCES/scripts/src/"
cp hooks/hooks.json "$RESOURCES/"
mkdir -p "$RESOURCES/sounds"
cp -R assets/sounds/* "$RESOURCES/sounds/" 2>/dev/null || true
chmod +x "$RESOURCES/scripts/hook_handler.py"
chmod +x "$RESOURCES/scripts/src/hook_handler.py"

# 4. 写入 Info.plist 与 PkgInfo
echo "[4/5] 写入 macOS Bundle 元数据 (Info.plist)..."
cat << EOF > "$CONTENTS/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>AntiEnter</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>com.antienter.app</string>
    <key>CFBundleName</key>
    <string>AntiEnter</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSSupportsAutomaticGraphicsSwitching</key>
    <true/>
</dict>
</plist>
EOF

echo -n "APPL????" > "$CONTENTS/PkgInfo"

# 签名 App (本地 ad-hoc 签名)
codesign --force --deep --sign - "$APP_BUNDLE" 2>/dev/null || true

# 5. 生成 Release 发布压缩包
echo "[5/5] 生成 GitHub Release 发布包..."
cd dist
zip -r -y "AntiEnter-v${VERSION}-macOS.zip" "AntiEnter.app" >/dev/null
cp "AntiEnter-v${VERSION}-macOS.zip" "AntiEnter-macOS.zip"
cd "$DIR"

echo ""
echo "=== 构建成功！==="
echo "应用包路径: $DIR/dist/AntiEnter.app"
echo "发布包路径: $DIR/dist/AntiEnter-v${VERSION}-macOS.zip"
ls -lh dist/
