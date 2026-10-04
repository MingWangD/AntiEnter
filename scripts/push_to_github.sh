#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

echo "=================================================="
echo "          AntiEnter 一键推送到 GitHub             "
echo "=================================================="

# 检查当前 remote
CURRENT_REMOTE=$(git remote get-url origin 2>/dev/null || true)

if [ -n "$CURRENT_REMOTE" ]; then
    echo "检测到当前已配置 origin: $CURRENT_REMOTE"
    echo "正在推送分支与标签..."
    git push -u origin main --tags
    echo "✓ 推送成功！"
    exit 0
fi

# 优先尝试 gh cli
if which gh >/dev/null 2>&1; then
    echo "尝试通过 GitHub CLI (gh) 自动创建远程仓库..."
    if gh repo create AntiEnter --public --source=. --remote=origin --push; then
        git push origin --tags
        echo "✓ 成功在 GitHub 创建仓库并推送代码与标签！"
        exit 0
    else
        echo "gh 自动创建未完成（可能需重新登录: gh auth login），转入手动输入模式。"
    fi
fi

# 手动输入 remote
echo ""
echo "请在 GitHub 网页新建仓库 (命名为 AntiEnter)，并在此粘贴远程地址："
read -p "Git 远程地址 (例如: git@github.com:MingWangD/AntiEnter.git 或 https://github.com/MingWangD/AntiEnter.git): " REMOTE_URL

if [ -n "$REMOTE_URL" ]; then
    git remote add origin "$REMOTE_URL"
    git branch -M main
    git push -u origin main --tags
    echo "✓ 成功推送到 $REMOTE_URL ！"
else
    echo "未输入远程地址，你可以后续随时手动执行:"
    echo "  git remote add origin <your-repo-url>"
    echo "  git push -u origin main --tags"
fi
