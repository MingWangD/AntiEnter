# AntiEnter (Antigravity 自动回车与完全权限自主插件)

> 🚀 **让 Antigravity 拥有类似 OpenAI Codex / Claude Code 的完全自主运行体验**。  
> 无论是桌面端 GUI 弹窗，还是终端 CLI (`agy`) 交互，常规操作自动批准（默认推荐选项）；高危操作保留人工审批；支持暂停、取消与事务级回滚。

[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-blue.svg)](https://github.com/MingWangD/AntiEnter)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Release](https://img.shields.io/badge/Release-v1.2.5-orange.svg)](https://github.com/MingWangD/AntiEnter/releases)

---

## 🌟 核心特性

- **跨平台全支持 (macOS + Windows)**：
  - **macOS**：原生 Swift 菜单栏应用 (`AntiEnter.app`)，具备实时状态图标、运行代次取消、事务级更新回滚与下拉菜单控制。
  - **Windows**：基于原生 Win32 API (`user32.dll` + `keybd_event`)，纯 Python 标准库驱动，提供一键批处理启动脚本 (`start_windows.bat`)。
- **双端全支持**：
  - **桌面端 (Desktop/IDE)**：收紧识别范围，仅对真实有效的目标按钮触发动作，绝不对文本编辑区、代码或普通说明文字误操作。
  - **终端端 (CLI / `agy`)**：协议级免密执行工具指令，跨平台支持 Terminal、iTerm、CMD、PowerShell、Windows Terminal。
- **1.0 秒安全缓冲 (Buffer Delay)**：
  - 遇到确认操作时，提供 1.0 秒缓冲倒计时与提示音（默认 `codex-notification` 音效），留出人工视觉反馈与紧急干预余地。
- **智能安全熔断机制 (Safety Fuse)**：
  - 自动放行常规开发命令（如代码检索、构建、测试、项目文件读写）。
  - 遇高危删除指令（如 Unix `rm -rf`、`rm`；Windows `del /s`、`rd /s`、`Remove-Item`）、磁盘格式化、路径穿越（`..`）或敏感系统目录覆盖写入时自动熔断，**强制保留人工弹窗审批**。
  - *注：命令黑名单属于有限安全保护屏障，不能作为底层绝对安全沙箱隔离。*
- **统一实例与代次控制**：
  - App 与 CLI 共享统一实例登记，防止重复启动；同一用户只允许单一运行实例。
  - 动作排队引入运行代次（generation token）：暂停、停用或策略切换立即取消排队旧任务，避免暂停后突发执行。
- **可验证、可回滚的更新事务**：
  - macOS 客户端支持事务级更新，自动验证包结构与目标版本，置换失败或拉起异常时自动原子回滚旧版本。

---

## 📦 安装与下载

### 🪟 Windows 用户使用方式

1. 前往 GitHub Releases 下载最新 [`AntiEnter-v1.2.5-windows.zip`](https://github.com/MingWangD/AntiEnter/releases/tag/v1.2.5)。
2. 解压到任意目录。
3. 双击运行 **`start_windows.bat`** 即可一键启动后台自动回车与全局 Hook！
4. 需恢复人工审批时，双击运行 **`stop_windows.bat`** 即可停用。

> *在 CMD / PowerShell 中亦可使用命令：*
> ```cmd
> .\bin\antienter.bat start
> .\bin\antienter.bat status
> .\bin\antienter.bat stop
> ```
> *注意：Windows 平台暂不支持 PTY 交互包装器 (`wrap` 命令) 以及在线事务自动置换；新版本发布请前往 Releases 页面手动下载。*

---

### 🍎 macOS 用户使用方式

1. 前往 GitHub Releases 下载最新 [`AntiEnter-v1.2.5-macOS.zip`](https://github.com/MingWangD/AntiEnter/releases/tag/v1.2.5)。
2. 解压并将 `AntiEnter.app` 拖入 `/Applications`（或任意目录）。
3. 双击启动，顶部菜单栏即会出现 `⚡⏎` 图标。
4. 首次启动时若系统弹出辅助功能请求，请在 `系统设置 -> 隐私与安全性 -> 辅助功能` 勾选允许。

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

### 3. 停止插件 (恢复人工确认)

```bash
./bin/antienter stop
```

---

## 🛠️ CLI 常用命令手册

| 命令 | 功能说明 |
| :--- | :--- |
| `./bin/antienter start` | 后台启动守护进程并挂载全局 Hook |
| `./bin/antienter stop` | 停止守护进程并恢复原生审批模式 |
| `./bin/antienter status` | 查看当前工作状态、PID 与活跃配置 |
| `./bin/antienter run` | 在前台直接运行守护进程（带详细调试日志） |
| `./bin/antienter build` | 重新编译 Swift 原生守护进程二进制 |
| `./bin/antienter wrap agy` | 在 PTY 自动回车环境中运行 Antigravity CLI (macOS) |
| `./bin/antienter test` | 运行自动化验收测试套件 |
| `./bin/antienter config --delay 1.0` | 自定义回车缓冲延迟（秒） |
| `./bin/antienter config --sound off` | 关闭自动回车提示音（默认开启） |
| `./bin/antienter config --theme codex-notification` | 设置提示音主题 (`codex-notification`, `tink`, `pop`, `ping`, `glass`, `hero`, `sosumi`) |
| `./bin/antienter config --fuse off` | 显式关闭高危指令熔断（默认开启） |
| `./bin/antienter config --enabled off` | 暂停自动确认动作（保留配置与 Hook） |

---

## 🔒 安全熔断规则清单

当命令行或参数匹配以下模式时，AntiEnter 将**拒绝自动放行**，保留人工审核：
- `rm`, `rm -rf`, `rmdir`, `trash`
- `del`, `rd`, `Remove-Item`
- `git reset --hard`, `git clean -f`
- `mkfs`, `dd if=`, `format`, `diskpart`
- `:(){ :|:& };:` (Fork Bomb)
- 重定向覆盖或直接写入 `/etc`, `/bin`, `/sbin`, `/usr`, `/System`, `/Library`, `C:\Windows` 等系统关键目录
- 缺少必要字段、JSON 损坏或未知非标准工具调用
