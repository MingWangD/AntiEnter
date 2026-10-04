# AntiEnter 第二次修复后复核报告

本报告复核最新工作区相对 `HEAD=2bfedec` 的未提交改动，以及附带记录中“所有复核问题已修复、59 项测试全部通过”的声明。

## 当前验证结果

- `python3 -m unittest discover tests -q`：**59 项通过**。
- 两份 Swift 源文件通过 `swiftc -typecheck`。
- `git diff --check`：通过，无尾随空白报告。
- v1.2.4 macOS/Windows ZIP 可以读取，包内包含版本清单和默认音效资源。
- 更新器已经有“启动健康检查失败后回滚”的测试。
- 本地仍未执行真实 macOS Accessibility UI、真实 Windows Win32 控件树、安装后启动和真实在线更新。

这说明上一轮指出的大部分 Python 生命周期、配置失败和更新器测试问题已经得到处理，但“所有问题已修复”仍然过早。以下问题仍能从当前代码直接推出。

## 仍然存在的高优先级问题

### P1：熔断开启时，通用确认词仍可能自动批准高危操作

位置：

- `/Users/myw/Desktop/AntiEnter/src/app/main.swift:367-445`
- `/Users/myw/Desktop/AntiEnter/src/swift/AntiEnterDaemon.swift:248-297`
- `/Users/myw/Desktop/AntiEnter/src/windows_daemon.py:129-220`

熔断开启时，三套 UI 实现仍允许 `confirm`、`yes`、`proceed`、`ok`、`submit` 等通用词。测试也把熔断开启下的 `Confirm`、`Proceed` 和 `Yes` 视为可自动触发。

当前新增的 `windowContainsDangerContext()` 和 `decision.json` 检查只能在窗口文本包含有限危险指示词，或最近 30 秒存在全局 `ask` 记录时阻止动作。若高危授权窗口只显示通用的 `Confirm`/`Yes`，或 Hook 记录过期、没有关联到当前窗口/请求，UI watcher 仍可能自动 Press/Return。

这不是单纯的误判问题，而是安全边界无法证明：实现没有请求 ID、窗口 ID、工具名或决策关联关系，不能确认“这个 Confirm 就是安全流程”。

建议在熔断开启时默认不自动点击通用确认词；只有能够关联到明确的安全流程上下文时才允许。更稳妥的方案是让 Hook 产生带请求 ID、工具名和目标窗口上下文的短期授权令牌，UI 只消费匹配的令牌。至少增加以下测试：

- 高危授权窗口只有 `Confirm`。
- 高危授权窗口只有 `Yes`。
- 没有 `decision.json`。
- `decision.json` 已过期。
- `decision.json` 的工具名或窗口上下文不匹配。

置信度：**高**。当前测试模型本身就证明通用词在熔断开启时仍会被判定为可执行。

### P1：Windows 的危险上下文检查仍然是文本启发式，且不检查根窗口

位置：`/Users/myw/Desktop/AntiEnter/src/windows_daemon.py:149-173`。

Windows 版本现在增加了 Button/SysCommandLink 类名白名单，这是有效改进。但高危上下文扫描仍只遍历子窗口文本，且没有检查传入的根窗口标题。危险文本如果出现在前台窗口标题、非枚举子树、控件 Value 或自定义可访问性属性中，就不会被识别。

同时，`danger_indicators` 只是有限字符串列表：`rm `、`sudo `、`curl `、`del `、`sh `、`bash `、工具名等，并不等价于 Hook 的完整危险规则。像 `git reset --hard`、`Remove-Item`、`diskpart`、系统目录重定向等情况可能绕过 UI 侧上下文检查。

建议把 Hook 的危险判定结果作为唯一策略来源，不要在 Windows UI 层复制一份不完整的危险字符串列表。UI 层无法得到匹配的安全令牌时，应保持人工确认。测试应覆盖根窗口标题、子窗口标题、控件文本和 Hook 的全部危险模式。

### P1：Swift App 的配置写入仍未使用与 Python 相同的持久化锁

位置：`/Users/myw/Desktop/AntiEnter/src/app/main.swift:167-185`。

Swift `savePersistentConfig()` 仍然直接读取、修改、写入配置文件，没有取得 `antienter_config.lock`；`replaceItemAt` 的错误也被 `try?` 忽略。当前新增的 `flock` 只用于实例登记和注销，并没有保护配置读改写。

当菜单栏 App 与 CLI/daemon 同时更新 `enabled`、熔断或 generation 时，两个进程仍可能互相覆盖字段。Swift 写入失败时也没有返回失败，UI 可能显示新状态而 Python 侧继续读旧状态。

建议抽取统一的跨语言配置协议：读改写都必须锁定同一文件，写入失败返回明确错误；Swift 的菜单操作和退出流程必须处理失败结果。增加“Swift 写入与 CLI 并发更新”以及“replaceItemAt 失败”的测试。

### P1：`advance_generation()` 失败仍被多个调用方忽略

位置：

- `/Users/myw/Desktop/AntiEnter/src/main.py:88-91`
- `/Users/myw/Desktop/AntiEnter/src/controller.py:101`
- `/Users/myw/Desktop/AntiEnter/src/controller.py:179-182`
- `/Users/myw/Desktop/AntiEnter/src/config.py:314-323`

`advance_generation()` 已改为保存失败返回 `-1`，但 CLI 配置命令、`controller.start()` 和 `controller.stop()` 都没有检查这个返回值。配置写入失败时，启停流程仍可能继续，旧的延时动作不会获得新的共享代次，跨进程取消语义不成立。

建议把 `-1` 转换为明确失败，并让启停和配置命令在代次无法持久化时返回非零；增加保存失败时“不会继续启动/停止成功”的测试。

## 次优先级问题

### P2：Swift 配置和实例文件的锁协议仍不是完全统一

Swift 使用 `flock` 打开 `~/.gemini/antienter_config.lock`，Python 在主路径失败时会退到临时目录锁；此外 Swift 的配置文件写入没有锁。正常路径下实例登记的锁已经改善，但异常路径和配置路径仍可能分裂。

建议把运行时目录和锁路径作为明确的跨语言协议，禁止在不同实现中自行推导备用位置；异常路径应显式失败，而不是静默切换到另一个锁。

### P2：停止流程的进程终止异常没有完整反映到返回值

位置：`/Users/myw/Desktop/AntiEnter/src/controller.py:186-206`。

`os.kill` 或等待过程发生 `PermissionError`/其他 `OSError` 时，异常被捕获后没有将 `stopped_ok` 设为 `False`，调用方可能得到成功状态，尽管目标进程仍然存在。建议保留异常信息并返回失败，随后再决定是否卸载 Hook。

### P2：测试数量增加，但生产 UI 仍主要由独立模型间接覆盖

`/Users/myw/Desktop/AntiEnter/tests/test_confirmation.py` 仍测试 Python `MockElement` 分类器；Swift AX 遍历、Swift `flock`、Swift Hook 原子替换和真实 Windows 控件行为没有直接执行。59 项全绿不能替代真实平台集成测试。

建议将确认规则抽成共享测试向量，并增加 macOS/Windows 平台适配层测试；发布前至少在 macOS 实机验证 AXPress/Return，在 Windows 实机验证 Button、Static、GroupBox、前台窗口和按键发送。

### P2：更新器健康检查仍需验证“新版本身份”，不仅是进程名

位置：`/Users/myw/Desktop/AntiEnter/src/updater.py:234-250`。

当前健康检查通过 `pgrep -f AntiEnter.app/Contents/MacOS/AntiEnter` 找到任意匹配进程，并排除 `old_pid`。如果系统中有另一份 AntiEnter.app 正在运行，或者旧进程 PID 没有正确传入，检查可能把错误进程当成新版已就绪。

建议验证新进程 PID 属于目标 Bundle 路径，并读取运行中的版本或健康标记；测试同机存在另一份 AntiEnter.app 的场景。

## 已确认有效的修复

- `update_config()` 和 `save_config()` 失败结果已经向 CLI 传播。
- 前台 daemon 非零退出码会返回失败。
- Swift App Hook 安装器已对损坏 JSON 做保护，并采用临时文件和原子替换。
- Swift 实例登记与注销已增加 `flock` 和自身 PID 校验。
- 更新器已增加启动轮询和失败回滚测试。
- Windows 已加入 Button/SysCommandLink 类名白名单，并过滤 Static、Edit 和 GroupBox。
- 59 项 Python 测试、Swift 类型检查和 `git diff --check` 均通过。

## 复核结论

**建议：仍暂缓发布。** 本轮已经解决上一次报告中的大部分直接缺陷，但高危确认的通用词安全边界、Swift 配置跨进程一致性、代次失败传播和真实平台验证仍未闭环。尤其不能把“最近存在一个 ask 文件”当成当前 UI 请求已获准确关联的证明。

当前结论置信度：**高**。依据包括 59 项测试复跑、Swift 类型检查、差异检查、产物检查和代码路径审查；真实 Accessibility、Win32、安装和更新运行时行为仍需平台集成测试确认。
