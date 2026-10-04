# AntiEnter (Antigravity 自动回车与完全权限自主插件)

> 🚀 **让 Antigravity 拥有类似 OpenAI Codex / Claude Code 的完全自主运行体验**。  
> 无论是桌面端 GUI 弹窗，还是终端 CLI (`agy`) 交互，遇到确认自动触发回车（默认选择推荐第 1 项），实现真正无人值守开发。

[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-blue.svg)](https://github.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Release](https://img.shields.io/badge/Release-v1.0.0-orange.svg)](https://github.com)

---

## 🌟 核心特性

- **跨平台全支持 (macOS + Windows)**：
  - **macOS**：原生 Swift 菜单栏应用 (`AntiEnter.app`)，实时状态图标与下拉菜单控制。
  - **Windows**：基于原生 Win32 API (`user32.dll` + `keybd_event`)，纯 Python 标准库驱动，提供一键批处理启动脚本 (`start_windows.bat`)。
- **双端全支持**：
  - **桌面端 (Desktop/IDE)**：精准监控 Antigravity 窗口与界面交互，弹窗、工件 Proceed、`ask_question` 模态框自动回车确认。
  - **终端端 (CLI / `agy`)**：协议级免密执行工具指令，跨平台支持 Terminal、iTerm、CMD、PowerShell、Windows Terminal。
- **1.0 秒安全缓冲 (Buffer Delay)**：
  - 遇到确认操作时，提供 1.0 秒缓冲倒计时与温和音频提示音（macOS Tink 音效 / Windows 提示蜂鸣），留出人工视觉反馈与紧急干预余地。
- **智能安全熔断机制 (Safety Fuse)**：
  - 自动放行绝大多数常规开发命令（如代码检索、构建、测试、文件读写）。
  - 遇极端高危删除指令（如 Unix `rm -rf`、`rm`；Windows `del /s`、`rd /s`、`Remove-Item`）自动熔断，**强制保留人工弹窗审批**。
- **双引擎融合架构**：
  - **底层协议 Hook (`PreToolUse`)**：零 UI 抢占、零延迟静默批准工具调用。
  - **UI 原生守护进程**：无缝穿透应用层界面确认。
- **一键极简启停**：一条命令或双击批处理全局激活，随时完整停用。

---

## 📦 安装与下载

### 🪟 Windows 用户使用方式

1. 前往 GitHub Releases 下载最新 [`AntiEnter-v1.0.0-windows.zip`](https://github.com/MingWangD/AntiEnter/releases/download/v1.0.0/AntiEnter-v1.0.0-windows.zip)。
2. 解压到任意目录。
3. 双击运行 **`start_windows.bat`** 即可一键启动后台自动回车与全局 Hook！
4. 需恢复人工审批时，双击运行 **`stop_windows.bat`** 即可停用。

> *在 CMD / PowerShell 中亦可使用命令：*
> ```cmd
> .\bin\antienter.bat start
> .\bin\antienter.bat status
> .\bin\antienter.bat stop
> ```

---

### 🍎 macOS 用户使用方式

1. 前往 GitHub Releases 下载最新 [`AntiEnter-v1.0.0-macOS.zip`](https://github.com/MingWangD/AntiEnter/releases/download/v1.0.0/AntiEnter-v1.0.0-macOS.zip)。
2. 解压并将 `AntiEnter.app` 拖入 `/Applications`（或任意目录）。
3. 双击启动，顶部菜单栏即会出现 `⚡⏎` 图标。
4. 首次启动时若系统弹出辅助功能请求，请在 `系统设置 -> 隐私与安全性 -> 辅助功能` 勾选允许。

---

## 📂 项目结构

```text
AntiEnter/
├── bin/
│   ├── antienter              # 核心命令行工具入口
│   └── antienter-daemon       # 原生 macOS Swift 守护进程二进制 (arm64)
├── src/
│   ├── config.py              # 配置管理（延时、黑名单、音效）
│   ├── controller.py          # 守护进程与 Hook 生命周期控制
│   ├── hook_handler.py        # Antigravity 协议级 PreToolUse Hook 处理脚本
│   ├── hook_installer.py      # 全局 hooks.json 注入与清理模块
│   ├── cli_runner.py          # 终端 PTY 智能交互包装器
│   ├── sound.py               # 异步提示音驱动
│   └── swift/
│       └── AntiEnterDaemon.swift  # 原生 macOS 窗口与辅助功能监听源码
├── hooks/
│   └── hooks.json             # Antigravity Hook 规则模板
├── tests/
│   └── test_hook.py           # 核心放行与熔断逻辑自动化测试
└── README.md                  # 说明文档
```

---

## ⚡ 快速使用指南

### 1. 检查运行状态

```bash
./bin/antienter status
```

### 2. 启动自动回车插件 (全面激活)

```bash
./bin/antienter start
```
*启动后会自动：*
1. 向 Antigravity 全局配置安装 `PreToolUse` Hook。
2. 在后台拉起 macOS 原生 UI 守护进程。
3. 桌面端与 CLI 工具调用将全部进入全自动放行模式。

> ⚠️ **macOS 首次运行权限提示**：  
> 首次启动 UI 守护进程时，系统可能会弹出“辅助功能 (Accessibility)”授权提示。请前往：  
> `系统设置 -> 隐私与安全性 -> 辅助功能`，勾选允许终端或 `antienter-daemon`。

### 3. 停止插件 (恢复人工确认)

```bash
./bin/antienter stop
```
*执行后立即停止守护进程并卸载 Hook，所有操作恢复默认的人工逐项审批。*

---

## 🛠️ CLI 常用命令手册

| 命令 | 功能说明 |
| :--- | :--- |
| `./bin/antienter start` | 后台启动守护进程并挂载全局 Hook |
| `./bin/antienter stop` | 停止守护进程并恢复原生审批模式 |
| `./bin/antienter status` | 查看当前工作状态、PID 与活跃配置 |
| `./bin/antienter run` | 在前台直接运行守护进程（带详细调试日志） |
| `./bin/antienter build` | 重新编译 Swift 原生守护进程二进制 |
| `./bin/antienter wrap agy` | 在 PTY 自动回车环境中运行 Antigravity CLI |
| `./bin/antienter test` | 运行放行与熔断自检套件 |
| `./bin/antienter config --delay 1.0` | 自定义回车缓冲延迟（秒） |
| `./bin/antienter config --sound off` | 关闭自动回车提示音（默认开启） |
| `./bin/antienter config --fuse off` | 关闭高危指令熔断（默认开启） |

---

## 🎯 场景对应机制

### 场景一：桌面端 Antigravity (GUI / Electron)
1. **工具执行审批**：被底层的 `PreToolUse` Hook 拦截，直接响应 `{"decision": "allow"}`，无需用户点击。
2. **多选题模态框 (`ask_question`)**：UI 守护进程检测到模态框弹出后，缓冲 1.0 秒并播放提示音，自动发送 `Return` 键（接受第 1 个推荐选项）。
3. **计划/工件确认 (`Proceed`)**：UI 守护进程检测到界面出现 Proceed 焦点，缓冲后自动回车继续。

### 场景二：命令行 Antigravity CLI (`agy`)
1. **工具执行**：与桌面端共享全局 Hook，所有 CLI 命令执行同样零延迟免审批。
2. **终端交互询问**（如 `Proceed? [y/N]`）：使用 `./bin/antienter wrap agy` 运行，PTY 包装器检测到终端提示后自动在 1.0 秒后回车确认。

---

## 🔒 安全熔断规则清单

当命令行或参数匹配以下任意高危模式时，AntiEnter 将**拒绝自动放行**，保留人工审核：
- `rm -rf /`
- `rm -rf ~`
- `rm -rf *`
- `mkfs`
- `dd if=`
- `:(){ :|:& };:` (Fork Bomb)
- 写入 `/etc`, `/bin`, `/sbin`, `/System` 等系统关键目录
