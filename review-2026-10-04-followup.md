# AntiEnter 修复后复核报告

本报告复核附带记录中“所有问题已修复、51 项测试全通过”的声明，范围是当前工作区相对 `HEAD=2bfedec` 的未提交改动。

## 验证结果

- `python3 -m unittest discover tests -v`：**51 项通过**。
- `git diff --check`：通过，无尾随空白报告。
- 两份 Swift 源文件通过 `swiftc -typecheck`。
- `dist/AntiEnter-v1.2.4-macOS.zip` 和 `dist/AntiEnter-v1.2.4-windows.zip` 均可读取；包内包含 `version.json` 和 `codex-notification.wav`。
- 仍未执行真实 macOS Accessibility UI、真实 Windows Win32 控件树、安装后启动、更新成功路径和并发更新竞争。

测试与静态检查结果说明改动方向已有明显改善，但不能据此确认“所有问题已修复”。下面的问题仍能从当前代码直接推出，部分已经复现。

## 仍需修复的问题

### P1：配置写入失败仍会被报告为成功

位置：`/Users/myw/Desktop/AntiEnter/src/config.py:303-310`。

`update_config()` 调用 `save_config(current)` 后不检查返回值，始终返回内存中的新配置。对 `save_config()` 返回 `False` 的场景进行 mock 后，实际结果是：调用方收到 `enabled=False`，随后 `load_config()` 仍然读到 `enabled=True`。

这会让 CLI/UI 显示设置成功，但 Hook 和 daemon 继续使用旧配置。修复方式是让 `update_config()` 返回明确的成功/失败结果，或在保存失败时抛出异常；所有调用方都必须根据失败结果停止报告成功。需要增加主配置不可写、临时文件创建失败、原子替换失败的测试。

### P1：Swift App 的 Hook 安装器仍会覆盖损坏的用户配置

位置：`/Users/myw/Desktop/AntiEnter/src/app/main.swift:469-494`。

当前 Swift `HookManager.installHook()` 在读取或解析 `hooks.json` 失败时保持空字典，随后写入只包含 AntiEnter 的配置。Python 安装器已经在 `/Users/myw/Desktop/AntiEnter/src/hook_installer.py:60-80` 增加了损坏保护，但实际菜单栏 App 使用的是 Swift 实现，因此风险仍然存在。

此外 Swift 安装器直接 `write(to:)`，没有使用同目录临时文件加原子替换；写入失败也被 `try?` 吞掉，却仍记录“安装成功”。

修复方式是：解析失败、顶层不是对象或写入失败时保留原文件并返回失败；成功解析后只修改自己的键，采用临时文件、`fsync` 和原子替换。为 Swift App 增加损坏 JSON、第三方 Hook 保留和权限失败测试。

### P1：更新器的健康检查失败后仍然继续成功

位置：`/Users/myw/Desktop/AntiEnter/src/updater.py:214-237`。

更新器调用 `/usr/bin/open` 后执行 `pgrep`。但当第一次 `pgrep` 返回非零时，代码只等待一秒，然后直接清理备份并返回成功；没有再次检查，也没有在仍未找到进程时回滚。`pgrep` 只证明某个进程名存在，也没有核对新版本 PID、版本号或就绪状态。

因此“启动请求已被系统接受”仍可能被误报为“新版已启动并验证通过”。修复方式是使用明确的启动就绪协议：等待新 PID 或健康标记，核对版本；超时必须回滚，并且在确认成功前保留旧备份。增加 `open=0、pgrep=1` 和“找到旧进程但没有新版就绪”的回滚测试。

### P1：前台运行模式不检查 daemon 退出码

位置：`/Users/myw/Desktop/AntiEnter/src/controller.py:101-126`。

前台模式等待子进程后无条件返回 `True`。如果 daemon 启动后立即以非零状态退出，`start(foreground=True)` 仍然报告成功。Windows 和 macOS 都可能出现这种情况，尤其是辅助功能权限、资源或实例登记失败时。

修复方式是保存 `proc.wait()` 的返回码，仅在子进程正常退出或用户主动中断时返回成功；立即异常退出必须返回非零并保留诊断信息。增加子进程退出码为 1 的测试。

### P1：Windows 确认扫描仍未验证控件角色

位置：`/Users/myw/Desktop/AntiEnter/src/windows_daemon.py:145-186`。

`EnumChildWindows` 会扫描所有可见且启用的子窗口，只排除几个编辑框类名，然后按窗口文本匹配。它没有确认控件是按钮、复选框或可执行控件。普通静态文本、标签或说明文字只要包含 `submit ↵`，或精确等于 `confirm`、`yes`、`proceed`，就可能触发 Return。

这仍然保留了上一轮“正文/静态文本误触发”的 Windows 路径。应加入 Win32 控件角色/类名白名单，或改为获取可访问性控件类型后再判定。测试必须覆盖静态文本、标签、按钮、编辑框、隐藏和禁用控件。

### P1：熔断开启时的通用确认词仍无法区分高危授权

位置：

- `/Users/myw/Desktop/AntiEnter/src/app/main.swift:367-383`
- `/Users/myw/Desktop/AntiEnter/src/swift/AntiEnterDaemon.swift:248-264`
- `/Users/myw/Desktop/AntiEnter/src/windows_daemon.py:131-180`

熔断开启时仍允许 `confirm`、`yes`、`proceed`、`ok` 等通用词。当前测试也明确把熔断开启下的 `Confirm` 视为可自动触发。若高危工具授权对话框使用 `Confirm` 或 `Yes`，且 Hook 决策文件不存在、已过期或没有与当前窗口关联，UI watcher 仍可能自动点击。

仅用一个 30 秒的全局 `decision.json` 无法证明某个按钮对应当前工具调用。安全默认应是：熔断开启时，通用确认词也只能在有明确的安全流程上下文时自动执行；无法关联调用时只提示、不按键。增加“危险授权按钮标题为 Confirm/Yes”“没有 Hook 记录”“记录已过期”的测试。

### P2：Swift 单实例检查不是原子占有

位置：`/Users/myw/Desktop/AntiEnter/src/app/main.swift:208-226`。

Swift App 先读取实例文件，再写入临时文件和替换实例文件。检查与写入之间没有跨进程锁或原子创建，因此两个 App 同时启动时都可能看到无活跃实例，然后互相覆盖登记。Python 端虽然有文件锁，但 Swift 没有使用同一把锁协议。

修复方式是让 Swift 和 Python 使用同一套原子注册协议，包含启动令牌；注销只能删除属于自己的登记。增加两个并发启动进程的竞争测试。

### P2：测试仍主要验证替身逻辑

`/Users/myw/Desktop/AntiEnter/tests/test_confirmation.py` 仍然自定义 Python `MockElement` 和 `classify_element()`，并没有调用 Swift Accessibility 或 Windows 控件扫描实现。51 项全绿能证明 Python 合约模型，但不能证明生产 UI 行为。

建议把判定规则抽成共享测试向量，平台代码只负责把原生控件转换成统一输入；补充 Swift 单元测试、Win32 mock 测试、打包后资源路径测试和安装后 smoke test。

## 已确认修复的部分

以下修复已由当前代码和测试确认，建议保留：

- Hook 对缺少或错误类型 `args`、空 `CommandLine`、空 `TargetFile` 返回 `ask`。
- CLI 暂停透传不再使用 `os.system(" ".join(args))`。
- Hook 决策写入独立状态文件，macOS/Swift daemon 能在熔断开启时读取近期 `ask` 决策。
- macOS AX 匹配加入了控件角色、否定词和工具授权短语分离。
- Python Hook 安装器对损坏 JSON 进行保护，使用原子替换。
- 更新锁改为 `O_CREAT|O_EXCL`，Bundle 版本校验已加入。
- 测试配置使用临时目录，当前 51 项测试不再受用户主目录状态污染。
- 版本清单、音效资源和最终 ZIP 的基本内容已存在。

## 复核结论

**建议：仍暂缓发布。** 本轮确实修复了上一份报告中的大部分直接问题，但“所有问题已修复”不成立。至少应先完成配置失败可见性、Swift Hook 配置保护、更新器真正的启动就绪回滚、前台退出码、Windows 控件角色和通用确认词安全边界，然后再进行真实 macOS/Windows 集成验证。

当前结论置信度：**高**。依据包括 51 项测试复跑、Swift 类型检查、产物目录检查、配置失败路径复现和当前源代码静态证据；真实 UI、Win32 和安装更新行为仍未被本地环境验证。
