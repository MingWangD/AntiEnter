# AntiEnter 第三次修复后复核报告

本报告复核最新工作区和附带记录中“71 项测试全部通过、令牌机制已经接通”的声明。

## 实际验证

- `python3 -m unittest discover tests -q`：**71 项通过**。
- `swiftc -typecheck`：`src/app/main.swift` 和 `src/swift/AntiEnterDaemon.swift` 均通过。
- `git diff --check`：通过。
- 当前工作区确实包含 `decision.json` 的 allow/ask、过期和工具匹配测试。
- 真实 macOS Accessibility UI、真实 Windows Win32 桌面、安装后启动和在线更新仍未执行。

测试数量和静态检查结果可信，但测试所覆盖的令牌匹配路径与实际 daemon 调用路径仍不一致，不能据此确认高危自动确认已经闭环。

## 必须继续修复的问题

### P1：工具匹配令牌没有接入真实生产调用路径

**证据**

- Windows 函数提供了 `expected_tool` 参数：`/Users/myw/Desktop/AntiEnter/src/windows_daemon.py:74`。
- 测试确实传入了 `expected_tool` 并覆盖工具不匹配：`/Users/myw/Desktop/AntiEnter/tests/test_daemons.py:156-181`。
- 但 Windows daemon 的实际调用在 `/Users/myw/Desktop/AntiEnter/src/windows_daemon.py:304` 和 `:319`，两处都没有传 `expected_tool`。
- Swift App 在 `/Users/myw/Desktop/AntiEnter/src/app/main.swift:460` 调用 `hasActiveHookAllowToken()` 时没有传工具名。
- Swift daemon 在 `/Users/myw/Desktop/AntiEnter/src/swift/AntiEnterDaemon.swift:307` 调用同样没有传工具名。

因此，生产 UI 路径只要看到任意近期 `allow` 令牌，就可能放行当前窗口的通用 `Confirm`/`Yes`/`Proceed`，即使这个令牌来自另一个工具调用。测试中的“工具不匹配拦截”只证明了直接调用辅助函数的行为，没有证明实际 daemon 会传入并执行匹配。

**影响**

安全的 `run_command` allow 令牌可能被另一个 `write_to_file` 授权窗口重放；另一个工具的 allow 令牌也可能被当前窗口消费。令牌仍然是全局、非请求绑定的。

**建议**

统一传递规范化后的工具名：Windows watcher 的初始扫描和发送前复查都必须传入同一个 expected tool；Swift App 和 Swift daemon 的确认目标函数也必须接收当前请求工具名，并将它传给令牌校验。若当前 UI 无法知道请求工具名，安全默认应是不自动点击通用确认词。

同时增加端到端调用测试：通过 `WindowsDaemonEngine.run()` 的实际调用链验证工具不匹配会拒绝，而不是只直接测试 `has_confirm_dialog_windows()`。

### P1：Swift 令牌校验在缺少 `tool` 字段时仍可能返回有效

位置：

- `/Users/myw/Desktop/AntiEnter/src/app/main.swift:139-151`
- `/Users/myw/Desktop/AntiEnter/src/swift/AntiEnterDaemon.swift:103-115`

当前逻辑是：

```swift
if let expected = expectedTool, let tool = json["tool"] as? String, tool != expected {
    return false
}
return true
```

当调用方传入 `expectedTool`、但 JSON 没有 `tool` 字段时，内层 `let tool` 失败，条件体不会执行，函数仍返回 `true`。令牌 schema 不完整时被当作有效授权。

修复为在要求工具匹配时强制要求字段存在并相等，例如 `guard let expectedTool, let actualTool = ..., actualTool == expectedTool else { return false }`。增加缺少 `tool`、`tool=null`、非字符串 `tool` 的 Swift/Windows 一致性测试。

### P1：`Submit ↵` 在熔断开启且没有令牌时仍无条件放行

位置：

- `/Users/myw/Desktop/AntiEnter/src/app/main.swift:454-468`
- `/Users/myw/Desktop/AntiEnter/src/swift/AntiEnterDaemon.swift:301-315`
- `/Users/myw/Desktop/AntiEnter/src/windows_daemon.py:117-140`

三套实现始终把 `Submit ↵` 放入 `allowedPhrases`，即使熔断开启、没有 allow 令牌、窗口上下文无法证明是安全流程。测试也明确要求无令牌时 `Submit ↵` 返回 `True`。

这仍然允许一个高危工具授权窗口只用 `Submit ↵` 作为按钮时自动确认。实现无法从按钮文本本身区分安全流程和高危授权，因而不能把它当成天然安全模板。

修复方式是：熔断开启时所有自动动作都需要有效、匹配当前请求的令牌；或者明确建立安全流程来源（例如仅由特定 CLI 状态机产生的请求 ID）后再允许 `Submit ↵`。至少增加“高危窗口只有 Submit ↵、无令牌”的阻断测试，并调整当前正向测试的安全前提。

### P1：allow 令牌可在有效期内重复重放

`record_decision()` 每次只写一个全局文件，并以时间窗口判断 allow。它没有 nonce、请求 ID、窗口 ID，也没有消费/失效操作。一个安全操作写出的 allow 可以在 10 秒内被多个 UI watcher、多个窗口或多个确认动作重复消费。

建议令牌包含唯一 ID、工具名、请求上下文和目标进程/窗口信息；第一次消费后立即原子标记为已消费。无法实现请求绑定时，应只允许明确的单一安全流程，不应开放通用 `Confirm`/`Yes`。

## 次优先级问题

### P2：当前“工具匹配测试”没有覆盖规范化工具名

Hook 会把 `default_api:run_command` 规范化为 `run_command` 进行危险判断，但 `record_decision()` 保存的是原始 `tool_name`。如果实际调用通过命名空间传入，令牌中的工具名可能是 `default_api:run_command`，而 UI 侧若使用规范化名称比较会不匹配；若不比较又会扩大授权范围。

建议令牌同时保存 `raw_tool` 和 `canonical_tool`，UI 只比较 canonical 值，并增加命名空间工具测试。

### P2：Windows 危险上下文仍不是 Hook 完整规则

`src/windows_daemon.py` 的 `danger_indicators` 仍是有限字符串集合，不覆盖 Hook 中的完整危险规则，如 `git reset --hard`、`Remove-Item`、`diskpart`、系统目录重定向等。UI 层文本扫描只能作为额外防线，不能替代 Hook 的策略结果。

### P2：真实平台行为仍未验证

71 项测试包含大量 Python 模型和 Win32/进程 mock；Swift AX 遍历、实际 `flock` 竞争、真实 Button/Static 控件树、真实进程身份和安装后资源解析仍需要 macOS/Windows 集成测试。

## 已确认有效的改进

- 配置失败、代次失败和进程终止失败已经加入错误传播测试。
- Swift 配置持久化已加入 `flock` 封装和返回值。
- Windows 根窗口危险文本检查和按钮类名过滤已经落地。
- 更新器已进行 PID/进程身份检查，并保留健康检查失败回滚。
- 71 项测试、Swift 类型检查和 `git diff --check` 当前均通过。

## 复核结论

**建议仍暂缓发布。** 本轮修复已经把令牌机制从测试模型推进到生产代码，但真实调用链仍没有传递 `expected_tool`，Swift 校验还接受缺少工具字段的令牌，`Submit ↵` 仍绕过无令牌安全边界，且令牌可重放。应先修复这些 P1 问题，再进行真实平台集成验证。

当前结论置信度：**高**。依据包括 71 项测试复跑、Swift 类型检查、差异检查和生产调用点静态核对。
