import Cocoa
import ApplicationServices
import Darwin

// MARK: - App Configuration & State
class AppState {
    static let shared = AppState()

    var version: String {
        if let bundleVer = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String, !bundleVer.isEmpty {
            return bundleVer
        }
        let candidates = [
            Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/version.json"),
            Bundle.main.bundleURL.deletingLastPathComponent().appendingPathComponent("version.json"),
            Bundle.main.bundleURL.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("version.json"),
            URL(fileURLWithPath: FileManager.default.currentDirectoryPath).appendingPathComponent("version.json")
        ]
        for c in candidates {
            if let data = try? Data(contentsOf: c),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let ver = json["version"] as? String {
                return ver
            }
        }
        return "1.2.5"
    }

    var isEnabled: Bool = true
    var bufferDelay: Double = 1.0
    var playSound: Bool = true
    var soundTheme: String = "codex-notification"
    var safetyFuseEnabled: Bool = true
    var currentGeneration: Int = 1

    var lastTriggerTime: TimeInterval = 0
    let cooldown: TimeInterval = 2.0

    let targetApps: Set<String> = [
        "Antigravity",
        "Antigravity Tools",
        "Gemini",
        "Electron",
        "Code",
        "Cursor",
        "Terminal",
        "iTerm2",
        "Ghostty",
        "kitty",
        "Alacritty"
    ]

    // 通用安全流程短语（问答、提交等，不涉及敏感工具授权）
    let safeFlowPhrases: [String] = [
        "submit ↵"
    ]

    // 工具授权短语（仅在显式关闭熔断时才允许 UI 自动点击；开启熔断时由 Hook 全权判定）
    let toolPermissionPhrases: [String] = [
        "yes, allow this time",
        "allow this time",
        "yes, and always allow",
        "always allow",
        "allow pushing",
        "allow searching",
        "allow running",
        "allow editing",
        "allow writing",
        "始终允许",
        "本次允许",
        "总是允许"
    ]

    // 精确按钮词（区分普通流程词与工具授权词）
    let safeExactWords: Set<String> = [
        "confirm",
        "submit",
        "proceed",
        "ok",
        "yes",
        "确定",
        "继续",
        "好",
        "skip",
        "跳过"
    ]

    let toolExactWords: Set<String> = [
        "allow",
        "允许"
    ]

    // 否定词排除（含否定含义的按钮绝不点击，如 "Do not proceed", "Don't allow"）
    let negativeWords: [String] = [
        "do not", "don't", "never", "cancel", "deny", "reject",
        "refuse", "disallow", "no, ", "取消", "拒绝", "不"
    ]

    var configDir: URL {
        if let env = ProcessInfo.processInfo.environment["ANTIENTER_CONFIG_DIR"], !env.isEmpty {
            return URL(fileURLWithPath: env)
        }
        let home = FileManager.default.homeDirectoryForCurrentUser
        return home.appendingPathComponent(".gemini")
    }

    var configFile: URL {
        return configDir.appendingPathComponent("antienter_config.json")
    }

    var instanceFile: URL {
        return configDir.appendingPathComponent("antienter_instance.json")
    }

    var decisionFile: URL {
        return configDir.appendingPathComponent("antienter_decision.json")
    }

    var globalHooksFile: URL {
        let home = FileManager.default.homeDirectoryForCurrentUser
        return home.appendingPathComponent(".gemini/config/hooks.json")
    }

    var logFile: URL {
        return configDir.appendingPathComponent("antienter.log")
    }

    func isHookPendingAsk() -> Bool {
        guard safetyFuseEnabled, FileManager.default.fileExists(atPath: decisionFile.path) else { return false }
        guard let data = try? Data(contentsOf: decisionFile),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let dec = json["decision"] as? String, dec == "ask",
              let ts = json["timestamp"] as? Double else {
            return false
        }
        return (Date().timeIntervalSince1970 - ts) < 30.0
    }

    func hasActiveHookAllowToken(expectedTool: String? = nil) -> Bool {
        guard let expected = expectedTool, !expected.isEmpty else {
            return false
        }
        guard FileManager.default.fileExists(atPath: decisionFile.path),
              let data = try? Data(contentsOf: decisionFile),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let dec = json["decision"] as? String, dec == "allow",
              let ts = json["timestamp"] as? Double else {
            return false
        }
        if let consumed = json["consumed"] as? Bool, consumed {
            return false
        }
        guard (Date().timeIntervalSince1970 - ts) < 10.0 else {
            return false
        }
        let rawActual = (json["canonical_tool"] as? String) ?? (json["tool"] as? String)
        guard let actual = rawActual, !actual.isEmpty else {
            return false
        }
        let normActual = actual.split(separator: ":").last.map(String.init)?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? ""
        let normExpected = expected.split(separator: ":").last.map(String.init)?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? ""
        guard !normActual.isEmpty, normActual == normExpected else {
            return false
        }
        return true
    }

    @discardableResult
    func markTokenConsumed() -> Bool {
        let res = withConfigLock { () -> Bool in
            guard FileManager.default.fileExists(atPath: decisionFile.path),
                  let data = try? Data(contentsOf: decisionFile),
                  var json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return false
            }
            if let consumed = json["consumed"] as? Bool, consumed {
                return false
            }
            json["consumed"] = true
            json["consumed_at"] = Date().timeIntervalSince1970
            do {
                let outData = try JSONSerialization.data(withJSONObject: json, options: [.prettyPrinted])
                let tmp = decisionFile.deletingLastPathComponent().appendingPathComponent("antienter_decision.tmp.\(ProcessInfo.processInfo.processIdentifier)")
                try outData.write(to: tmp, options: .atomic)
                _ = try FileManager.default.replaceItemAt(decisionFile, withItemAt: tmp)
                return true
            } catch {
                return false
            }
        }
        return res ?? false
    }

    func withConfigLock<T>(_ action: () throws -> T) rethrows -> T? {
        try? FileManager.default.createDirectory(at: configDir, withIntermediateDirectories: true)
        let lockURL = configDir.appendingPathComponent("antienter_config.lock")
        let fd = open(lockURL.path, O_CREAT | O_RDWR, 0o644)
        guard fd >= 0 else {
            log("获取跨进程配置锁失败 (fd: \(fd))")
            return nil
        }
        defer { close(fd) }
        guard flock(fd, LOCK_EX) == 0 else {
            log("获取排他锁失败 (errno: \(errno))")
            return nil
        }
        defer { flock(fd, LOCK_UN) }
        return try action()
    }

    func log(_ message: String) {
        let timestamp = ISO8601DateFormatter().string(from: Date())
        let line = "[\(timestamp)] \(message)\n"
        if let data = line.data(using: .utf8) {
            try? FileManager.default.createDirectory(at: configDir, withIntermediateDirectories: true)
            if FileManager.default.fileExists(atPath: logFile.path) {
                if let fileHandle = try? FileHandle(forWritingTo: logFile) {
                    fileHandle.seekToEndOfFile()
                    fileHandle.write(data)
                    fileHandle.closeFile()
                }
            } else {
                try? data.write(to: logFile)
            }
        }
    }

    // MARK: - 持久化配置同步（排他锁保护与错误回退）
    func loadPersistentConfig() {
        _ = withConfigLock { () -> Void in
            guard FileManager.default.fileExists(atPath: configFile.path),
                  let data = try? Data(contentsOf: configFile),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return
            }
            if let en = json["enabled"] as? Bool { isEnabled = en }
            if let d = json["buffer_delay"] as? Double, d >= 0 { bufferDelay = d }
            if let ps = json["play_sound"] as? Bool { playSound = ps }
            if let st = json["sound_theme"] as? String { soundTheme = st }
            if let sf = json["safety_fuse_enabled"] as? Bool { safetyFuseEnabled = sf }
            if let gen = json["generation"] as? Int { currentGeneration = gen }
        }
    }

    @discardableResult
    func savePersistentConfig() -> Bool {
        let res = withConfigLock { () -> Bool in
            var json: [String: Any] = [:]
            if let data = try? Data(contentsOf: configFile),
               let existing = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                json = existing
            }
            json["enabled"] = isEnabled
            json["buffer_delay"] = bufferDelay
            json["play_sound"] = playSound
            json["sound_theme"] = soundTheme
            json["safety_fuse_enabled"] = safetyFuseEnabled
            json["generation"] = currentGeneration

            do {
                let outputData = try JSONSerialization.data(withJSONObject: json, options: [.prettyPrinted])
                let tmp = configFile.deletingLastPathComponent().appendingPathComponent("antienter_config.tmp.\(ProcessInfo.processInfo.processIdentifier)")
                try outputData.write(to: tmp, options: .atomic)
                _ = try FileManager.default.replaceItemAt(configFile, withItemAt: tmp)
                return true
            } catch {
                log("保存配置失败: \(error.localizedDescription)")
                return false
            }
        }
        return res ?? false
    }

    @discardableResult
    func advanceGeneration() -> Bool {
        currentGeneration += 1
        return savePersistentConfig()
    }

    // MARK: - 统一单实例登记
    func getActiveInstance() -> [String: Any]? {
        guard FileManager.default.fileExists(atPath: instanceFile.path),
              let data = try? Data(contentsOf: instanceFile),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let pid = json["pid"] as? Int32 else {
            return nil
        }
        if kill(pid, 0) == 0 {
            return json
        }
        try? FileManager.default.removeItem(at: instanceFile)
        return nil
    }

    func registerInstance() -> Bool {
        let res = withConfigLock { () -> Bool in
            if let active = getActiveInstance(),
               let pid = active["pid"] as? Int32,
               pid != ProcessInfo.processInfo.processIdentifier {
                return false
            }
            let myPid = ProcessInfo.processInfo.processIdentifier
            let info: [String: Any] = [
                "pid": myPid,
                "entry": "app",
                "user": NSUserName(),
                "started_at": Date().timeIntervalSince1970
            ]
            if let data = try? JSONSerialization.data(withJSONObject: info, options: [.prettyPrinted]) {
                let tmp = configDir.appendingPathComponent("antienter_instance.tmp.\(myPid)")
                do {
                    try data.write(to: tmp, options: .atomic)
                    _ = try FileManager.default.replaceItemAt(instanceFile, withItemAt: tmp)
                    return true
                } catch {
                    return false
                }
            }
            return false
        }
        return res ?? false
    }

    func unregisterInstance() {
        _ = withConfigLock { () -> Void in
            if let active = getActiveInstance(),
               let pid = active["pid"] as? Int32,
               pid == ProcessInfo.processInfo.processIdentifier {
                try? FileManager.default.removeItem(at: instanceFile)
            }
        }
    }

    // MARK: - 资源安全音效播放
    func playCueSound() {
        guard playSound else { return }
        let theme = soundTheme.lowercased()

        if theme == "codex-notification" || theme == "codex" {
            var candidates: [String] = []
            if let resURL = Bundle.main.resourceURL {
                candidates.append(resURL.appendingPathComponent("sounds/codex-notification.wav").path)
            }
            let home = FileManager.default.homeDirectoryForCurrentUser
            candidates.append(home.appendingPathComponent("Library/Sounds/codex-notification.wav").path)
            candidates.append(Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/sounds/codex-notification.wav").path)
            candidates.append(Bundle.main.bundleURL.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("assets/sounds/codex-notification.wav").path)

            for path in candidates {
                if FileManager.default.fileExists(atPath: path) {
                    if let sound = NSSound(contentsOfFile: path, byReference: true) {
                        sound.play()
                        return
                    }
                }
            }
        }

        let soundPath: String
        switch theme {
        case "pop": soundPath = "/System/Library/Sounds/Pop.aiff"
        case "ping": soundPath = "/System/Library/Sounds/Ping.aiff"
        case "glass": soundPath = "/System/Library/Sounds/Glass.aiff"
        case "hero": soundPath = "/System/Library/Sounds/Hero.aiff"
        case "sosumi": soundPath = "/System/Library/Sounds/Sosumi.aiff"
        default: soundPath = "/System/Library/Sounds/Tink.aiff"
        }

        if FileManager.default.fileExists(atPath: soundPath) {
            if let sound = NSSound(contentsOfFile: soundPath, byReference: true) {
                sound.play()
                return
            }
        }
        NSSound(named: "Tink")?.play()
    }
}

// MARK: - Accessibility Helper & Target Identification
struct ConfirmationTarget {
    let window: AXUIElement
    let targetButton: AXUIElement?
    let matchedText: String
}

class AccessibilityService {
    static func isTrusted() -> Bool {
        return AXIsProcessTrusted()
    }

    static func promptAccessibility() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
    }

    static func windowContainsDangerContext(element: AXUIElement, depth: Int = 0) -> Bool {
        if depth > 10 { return false }
        let dangerIndicators = [
            "rm -rf", "rm -r", "rm -f", "rm ", "rmdir", "trash",
            "git reset --hard", "git reset", "git clean",
            "sudo ", "curl ", "sh ", "bash ",
            "mkfs", "dd if=", ":(){ :|:& };:", "> /dev/", "chmod -r 777", "chmod 777",
            "del /s", "del /f", "del /q", "del ", "rd /s", "rd /q", "rd /", "rd ",
            "remove-item", "format ", "diskpart",
            "shutdown", "reboot", "init 0", "kill -9",
            "/etc/", "/bin/", "/sbin/", "/usr/", "/system/", "/library/",
            "commandline", "run_command", "write_to_file", "replace_file_content"
        ]
        let attrs = [kAXTitleAttribute, kAXDescriptionAttribute, kAXValueAttribute]
        for attr in attrs {
            var valRef: CFTypeRef?
            if AXUIElementCopyAttributeValue(element, attr as CFString, &valRef) == .success,
               let valStr = valRef as? String {
                let lower = valStr.lowercased()
                if dangerIndicators.contains(where: { lower.contains($0) }) {
                    return true
                }
            }
        }
        var childrenRef: CFTypeRef?
        if AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &childrenRef) == .success,
           let children = childrenRef as? [AXUIElement] {
            for child in children {
                if windowContainsDangerContext(element: child, depth: depth + 1) {
                    return true
                }
            }
        }
        return false
    }

    static func detectWindowTool(element: AXUIElement, depth: Int = 0) -> String? {
        if depth > 10 { return nil }
        let attrs = [kAXTitleAttribute, kAXDescriptionAttribute, kAXValueAttribute]
        for attr in attrs {
            var valRef: CFTypeRef?
            if AXUIElementCopyAttributeValue(element, attr as CFString, &valRef) == .success,
               let valStr = valRef as? String {
                let lower = valStr.lowercased()
                if lower.contains("run_command") || lower.contains("run command") || lower.contains("commandline") {
                    return "run_command"
                }
                if lower.contains("write_to_file") || lower.contains("write to file") || lower.contains("targetfile") {
                    return "write_to_file"
                }
                if lower.contains("replace_file_content") || lower.contains("replace file content") {
                    return "replace_file_content"
                }
            }
        }
        var childrenRef: CFTypeRef?
        if AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &childrenRef) == .success,
           let children = childrenRef as? [AXUIElement] {
            for child in children {
                if let t = detectWindowTool(element: child, depth: depth + 1) {
                    return t
                }
            }
        }
        return nil
    }

    static func findConfirmationTarget(appElement: AXUIElement) -> ConfirmationTarget? {
        if AppState.shared.isHookPendingAsk() {
            return nil
        }
        var windowsRef: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(appElement, kAXWindowsAttribute as CFString, &windowsRef)
        guard result == .success, let windows = windowsRef as? [AXUIElement] else {
            return nil
        }

        for window in windows {
            if AppState.shared.safetyFuseEnabled && windowContainsDangerContext(element: window) {
                // 窗口中包含高危指令或敏感工具调用特征，高危熔断开启时拒绝自动点击
                continue
            }
            let expectedTool = detectWindowTool(element: window)
            if let target = scanElementForConfirmation(window, window: window, depth: 0, expectedTool: expectedTool) {
                return target
            }
        }
        return nil
    }

    private static func scanElementForConfirmation(_ element: AXUIElement, window: AXUIElement, depth: Int, expectedTool: String?) -> ConfirmationTarget? {
        if depth > 25 { return nil }

        var roleRef: CFTypeRef?
        let roleSuccess = AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &roleRef)
        let role = (roleSuccess == .success) ? (roleRef as? String ?? "") : ""

        // 明确排除文本输入框、正文视图与代码区域，绝不将编辑内容作为确认目标
        let excludedRoles: Set<String> = [
            kAXTextAreaRole as String,
            kAXTextFieldRole as String,
            kAXStaticTextRole as String,
            kAXScrollAreaRole as String,
            "AXWebArea",
            kAXOutlineRole as String,
            kAXTableRole as String,
            kAXRowRole as String
        ]

        let actionableRoles: Set<String> = [
            kAXButtonRole as String,
            kAXRadioButtonRole as String,
            kAXCheckBoxRole as String,
            kAXPopUpButtonRole as String
        ]

        if actionableRoles.contains(role) {
            // 校验控件是否可用（隐藏或禁用的控件不触发动作）
            var enabledRef: CFTypeRef?
            if AXUIElementCopyAttributeValue(element, kAXEnabledAttribute as CFString, &enabledRef) == .success,
               let isEnabled = enabledRef as? Bool, !isEnabled {
                // 控件处于禁用状态，跳过
            } else {
                // 仅从 Title 和 Description 提取按钮动作意图
                let textAttrs = [kAXTitleAttribute, kAXDescriptionAttribute]
                for attr in textAttrs {
                    var valRef: CFTypeRef?
                    if AXUIElementCopyAttributeValue(element, attr as CFString, &valRef) == .success,
                       let valStr = valRef as? String {
                        let trimmed = valStr.trimmingCharacters(in: .whitespacesAndNewlines)
                        if trimmed.isEmpty { continue }
                        let lower = trimmed.lowercased()

                        // 否定词排除（如 "Do not proceed", "Don't allow"）
                        if AppState.shared.negativeWords.contains(where: { lower.contains($0) }) {
                            return nil
                        }

                        var allowedPhrases: [String] = []
                        var allowedWords: Set<String> = []
                        if !AppState.shared.safetyFuseEnabled {
                            allowedPhrases = AppState.shared.safeFlowPhrases
                            allowedPhrases.append(contentsOf: AppState.shared.toolPermissionPhrases)
                            allowedWords.formUnion(AppState.shared.safeExactWords)
                            allowedWords.formUnion(AppState.shared.toolExactWords)
                        } else if AppState.shared.hasActiveHookAllowToken(expectedTool: expectedTool) {
                            // 仅当存在 Hook 产生的有效放行令牌且工具匹配时，才允许自动确认（含 Submit ↵ 及通用词）
                            allowedPhrases = AppState.shared.safeFlowPhrases
                            allowedWords.formUnion(AppState.shared.safeExactWords)
                        }

                        // 1. 强特征短语匹配
                        for phrase in allowedPhrases {
                            if lower.contains(phrase) {
                                return ConfirmationTarget(window: window, targetButton: element, matchedText: trimmed)
                            }
                        }

                        // 2. 精确按钮词匹配（排除诸如 "你好"、"Skip tutorial"）
                        if allowedWords.contains(lower) {
                            return ConfirmationTarget(window: window, targetButton: element, matchedText: trimmed)
                        }
                    }
                }
            }
        }

        // 若当前元素是可编辑文本控件，不进一步深入其 Value 匹配
        if excludedRoles.contains(role) {
            return nil
        }

        // 递归扫描子元素
        var childrenRef: CFTypeRef?
        if AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &childrenRef) == .success,
           let children = childrenRef as? [AXUIElement] {
            for child in children {
                if let matched = scanElementForConfirmation(child, window: window, depth: depth + 1, expectedTool: expectedTool) {
                    return matched
                }
            }
        }
        return nil
    }

    static func performActionOrReturn(target: ConfirmationTarget) {
        AppState.shared.markTokenConsumed()

        // 优先触发目标按钮的 Press Action
        if let button = target.targetButton {
            let pressRes = AXUIElementPerformAction(button, kAXPressAction as CFString)
            if pressRes == .success {
                return
            }
        }

        // 回退至发送 Return 键，但前提是当前焦点不能落在输入文本区
        var focusedRef: CFTypeRef?
        if AXUIElementCopyAttributeValue(target.window, kAXFocusedUIElementAttribute as CFString, &focusedRef) == .success,
           let focusedRaw = focusedRef,
           CFGetTypeID(focusedRaw) == AXUIElementGetTypeID() {
            let focused = focusedRaw as! AXUIElement
            var roleRef: CFTypeRef?
            if AXUIElementCopyAttributeValue(focused, kAXRoleAttribute as CFString, &roleRef) == .success,
               let role = roleRef as? String {
                if role == (kAXTextAreaRole as String) || role == (kAXTextFieldRole as String) {
                    // 焦点位于文本编辑区，禁止误发回车
                    return
                }
            }
        }

        sendReturn()
    }

    static func sendReturn() {
        let returnKey: CGKeyCode = 36
        let src = CGEventSource(stateID: .hidSystemState)
        if let down = CGEvent(keyboardEventSource: src, virtualKey: returnKey, keyDown: true),
           let up = CGEvent(keyboardEventSource: src, virtualKey: returnKey, keyDown: false) {
            down.post(tap: .cghidEventTap)
            usleep(30000)
            up.post(tap: .cghidEventTap)
        }
    }
}

// MARK: - Hook Manager
class HookManager {
    @discardableResult
    static func installHook() -> Bool {
        let hooksURL = AppState.shared.globalHooksFile
        let configDir = hooksURL.deletingLastPathComponent()
        do {
            try FileManager.default.createDirectory(at: configDir, withIntermediateDirectories: true)
        } catch {
            AppState.shared.log("创建 Hook 目录失败: \(error)")
            return false
        }

        let candidates = [
            "/Applications/AntiEnter.app/Contents/Resources/scripts/hook_handler.py",
            Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/scripts/hook_handler.py").path,
            Bundle.main.bundleURL.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("src/hook_handler.py").path,
            URL(fileURLWithPath: FileManager.default.currentDirectoryPath).appendingPathComponent("src/hook_handler.py").path
        ]
        var chosenPath = candidates[0]
        for c in candidates {
            if FileManager.default.fileExists(atPath: c) {
                chosenPath = c
                break
            }
        }

        var hooks: [String: Any] = [:]
        if FileManager.default.fileExists(atPath: hooksURL.path) {
            do {
                let data = try Data(contentsOf: hooksURL)
                let trimmed = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                if !trimmed.isEmpty {
                    guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                        AppState.shared.log("安装 Hook 失败: 现有 hooks.json 根结构不是字典，保留原文件不予覆盖。")
                        return false
                    }
                    hooks = json
                }
            } catch {
                AppState.shared.log("安装 Hook 失败: 现有 hooks.json 损坏或格式错误 (\(error.localizedDescription))，保留原文件不予覆盖。")
                return false
            }
        }

        hooks["antienter-auto-approver"] = [
            "enabled": true,
            "PreToolUse": [
                [
                    "matcher": "*",
                    "hooks": [
                        [
                            "type": "command",
                            "command": "python3 \"\(chosenPath)\"",
                            "timeout": 15
                        ]
                    ]
                ]
            ]
        ]

        do {
            let outputData = try JSONSerialization.data(withJSONObject: hooks, options: [.prettyPrinted])
            let tmp = configDir.appendingPathComponent("hooks.json.tmp.\(ProcessInfo.processInfo.processIdentifier)")
            try outputData.write(to: tmp, options: .atomic)
            _ = try FileManager.default.replaceItemAt(hooksURL, withItemAt: tmp)
            AppState.shared.log("Hook 已成功安装至 \(hooksURL.path)")
            return true
        } catch {
            AppState.shared.log("保存 Hook 配置失败: \(error.localizedDescription)")
            return false
        }
    }

    @discardableResult
    static func uninstallHook() -> Bool {
        let hooksURL = AppState.shared.globalHooksFile
        guard FileManager.default.fileExists(atPath: hooksURL.path) else { return true }

        do {
            let data = try Data(contentsOf: hooksURL)
            let trimmed = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if trimmed.isEmpty { return true }

            guard var hooks = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                AppState.shared.log("卸载 Hook 失败: 现有 hooks.json 根结构不是字典")
                return false
            }

            if hooks.removeValue(forKey: "antienter-auto-approver") != nil {
                let outputData = try JSONSerialization.data(withJSONObject: hooks, options: [.prettyPrinted])
                let configDir = hooksURL.deletingLastPathComponent()
                let tmp = configDir.appendingPathComponent("hooks.json.tmp.\(ProcessInfo.processInfo.processIdentifier)")
                try outputData.write(to: tmp, options: .atomic)
                _ = try FileManager.default.replaceItemAt(hooksURL, withItemAt: tmp)
                AppState.shared.log("Hook 已从全局配置移除")
            }
            return true
        } catch {
            AppState.shared.log("卸载 Hook 失败: \(error.localizedDescription)")
            return false
        }
    }

    static func isHookInstalled() -> Bool {
        let hooksURL = AppState.shared.globalHooksFile
        guard FileManager.default.fileExists(atPath: hooksURL.path),
              let data = try? Data(contentsOf: hooksURL),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let hook = json["antienter-auto-approver"] as? [String: Any] else {
            return false
        }
        return (hook["enabled"] as? Bool) ?? true
    }
}

// MARK: - Auto Update Service (事务级回滚集成)
class UpdateService {
    static let shared = UpdateService()
    let repo = "MingWangD/AntiEnter"

    func checkForUpdates(silentIfLatest: Bool = false) {
        guard let url = URL(string: "https://api.github.com/repos/\(repo)/releases/latest") else { return }
        var request = URLRequest(url: url)
        request.setValue("AntiEnter-App", forHTTPHeaderField: "User-Agent")
        request.timeoutInterval = 10

        let task = URLSession.shared.dataTask(with: request) { data, response, error in
            guard let data = data, error == nil else {
                if !silentIfLatest {
                    DispatchQueue.main.async {
                        let alert = NSAlert()
                        alert.messageText = "检查更新失败"
                        alert.informativeText = "无法连接至 GitHub，请检查网络连接。"
                        alert.alertStyle = .warning
                        alert.runModal()
                    }
                }
                return
            }

            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let tagName = json["tag_name"] as? String else {
                return
            }

            let releaseBody = (json["body"] as? String) ?? "暂无版本更新改动说明。"
            let assets = (json["assets"] as? [[String: Any]]) ?? []

            var downloadURLString: String? = nil
            for asset in assets {
                if let name = asset["name"] as? String, name.lowercased().contains("macos.zip"),
                   let urlStr = asset["browser_download_url"] as? String {
                    downloadURLString = urlStr
                    break
                }
            }

            let remoteVer = tagName.trimmingCharacters(in: CharacterSet(charactersIn: "vV"))
            let currentVer = AppState.shared.version

            if self.isVersion(remoteVer, greaterThan: currentVer) {
                DispatchQueue.main.async {
                    self.promptUpdate(version: tagName, body: releaseBody, downloadURLStr: downloadURLString)
                }
            } else if !silentIfLatest {
                DispatchQueue.main.async {
                    let alert = NSAlert()
                    alert.messageText = "已是最新版本"
                    alert.informativeText = "当前版本 v\(currentVer) 已是最新版，无需更新。"
                    alert.alertStyle = .informational
                    alert.runModal()
                }
            }
        }
        task.resume()
    }

    private func isVersion(_ v1: String, greaterThan v2: String) -> Bool {
        let parts1 = v1.split(separator: ".").compactMap { Int($0) }
        let parts2 = v2.split(separator: ".").compactMap { Int($0) }
        let maxCount = max(parts1.count, parts2.count)
        for i in 0..<maxCount {
            let p1 = i < parts1.count ? parts1[i] : 0
            let p2 = i < parts2.count ? parts2[i] : 0
            if p1 > p2 { return true }
            if p1 < p2 { return false }
        }
        return false
    }

    private func promptUpdate(version: String, body: String, downloadURLStr: String?) {
        let alert = NSAlert()
        alert.messageText = "🎉 AntiEnter 发现新版本 (\(version))"
        alert.informativeText = "【新版本改动】\n\(body)\n\n点击【确认自动更新】将下载并执行事务级安装，具备自动回滚保护。"
        alert.alertStyle = .informational
        alert.addButton(withTitle: "确认自动更新")
        alert.addButton(withTitle: "稍后再说")

        let response = alert.runModal()
        if response == .alertFirstButtonReturn {
            if let downloadURLStr = downloadURLStr, let downloadURL = URL(string: downloadURLStr) {
                applyUpdate(from: downloadURL, version: version)
            } else {
                let failAlert = NSAlert()
                failAlert.messageText = "未找到更新包"
                failAlert.informativeText = "该 Release 尚未包含 macOS 安装包资产，请稍候重试。"
                failAlert.runModal()
            }
        }
    }

    private func applyUpdate(from downloadURL: URL, version: String) {
        DispatchQueue.global(qos: .userInitiated).async {
            let tmpZip = URL(fileURLWithPath: "/tmp/AntiEnter_Update_\(ProcessInfo.processInfo.processIdentifier).zip")
            try? FileManager.default.removeItem(at: tmpZip)

            var request = URLRequest(url: downloadURL)
            request.setValue("AntiEnter-App", forHTTPHeaderField: "User-Agent")
            let semaphore = DispatchSemaphore(value: 0)
            var downloadSuccess = false

            let downloadTask = URLSession.shared.downloadTask(with: request) { tempLocalURL, _, error in
                if let tempLocalURL = tempLocalURL, error == nil {
                    try? FileManager.default.moveItem(at: tempLocalURL, to: tmpZip)
                    downloadSuccess = true
                }
                semaphore.signal()
            }
            downloadTask.resume()
            semaphore.wait()

            guard downloadSuccess && FileManager.default.fileExists(atPath: tmpZip.path) else {
                DispatchQueue.main.async {
                    let errAlert = NSAlert()
                    errAlert.messageText = "下载更新失败"
                    errAlert.informativeText = "下载新版本安装包超时或网络中断，请稍后重试。"
                    errAlert.runModal()
                }
                return
            }

            let runningAppPath = Bundle.main.bundleURL.path
            let currentPid = ProcessInfo.processInfo.processIdentifier

            // 查找共享的 Python 更新辅助程序
            let candidates = [
                Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/scripts/updater.py").path,
                Bundle.main.bundleURL.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("src/updater.py").path,
                URL(fileURLWithPath: FileManager.default.currentDirectoryPath).appendingPathComponent("src/updater.py").path
            ]
            var updaterPath = candidates[0]
            for c in candidates {
                if FileManager.default.fileExists(atPath: c) {
                    updaterPath = c
                    break
                }
            }

            // 使用 osascript 启动事务更新辅助程序并立即退出旧版应用
            let scriptCmd = "python3 \"\(updaterPath)\" --apply --target \"\(runningAppPath)\" --old-pid \(currentPid) --version \"\(version)\" --archive \"\(tmpZip.path)\""
            let osaProc = Process()
            osaProc.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
            osaProc.arguments = ["-e", "do shell script \"\(scriptCmd) > /tmp/antienter_update.log 2>&1 &\""]
            try? osaProc.run()
            osaProc.waitUntilExit()

            DispatchQueue.main.async {
                AppState.shared.log("已交接事务更新程序，正在退出旧版本...")
                NSApplication.shared.terminate(nil)
            }
        }
    }
}

// MARK: - App Delegate & Menu Bar Controller
class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    var statusItem: NSStatusItem!
    var timer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        AppState.shared.loadPersistentConfig()
        if !AppState.shared.registerInstance() {
            AppState.shared.log("检测到已有活跃 AntiEnter 实例运行中，正在退出当前重复进程")
            NSApplication.shared.terminate(nil)
            return
        }
        HookManager.installHook()
        setupStatusBar()
        startWatcherTimer()

        if !AccessibilityService.isTrusted() {
            AccessibilityService.promptAccessibility()
        }

        AppState.shared.log("AntiEnter.app (v\(AppState.shared.version)) 启动就绪")

        DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) {
            UpdateService.shared.checkForUpdates(silentIfLatest: true)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        AppState.shared.isEnabled = false
        AppState.shared.advanceGeneration()
        AppState.shared.savePersistentConfig()
        AppState.shared.unregisterInstance()
        HookManager.uninstallHook()
    }

    func setupStatusBar() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        let menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu
        updateStatusItemAppearance()
        buildMenu()
    }

    func menuWillOpen(_ menu: NSMenu) {
        buildMenu()
    }

    func updateStatusItemAppearance() {
        guard let button = statusItem.button else { return }
        if AppState.shared.isEnabled {
            button.title = "⚡⏎"
        } else {
            button.title = "⏸⏎"
        }
    }

    func buildMenu() {
        let menu = NSMenu()
        menu.delegate = self

        let statusTitle = AppState.shared.isEnabled ? "🟢 AntiEnter: 自动回车已激活 (v\(AppState.shared.version))" : "🔴 AntiEnter: 已暂停 (v\(AppState.shared.version))"
        let statusItemMenu = NSMenuItem(title: statusTitle, action: nil, keyEquivalent: "")
        statusItemMenu.isEnabled = false
        menu.addItem(statusItemMenu)
        menu.addItem(NSMenuItem.separator())

        let toggleTitle = AppState.shared.isEnabled ? "暂停自动回车" : "恢复自动回车"
        let toggleItem = NSMenuItem(title: toggleTitle, action: #selector(toggleEnabled), keyEquivalent: "t")
        toggleItem.target = self
        menu.addItem(toggleItem)

        menu.addItem(NSMenuItem.separator())

        let delayMenu = NSMenu()
        let delays = [0.5, 0.8, 1.0, 1.5, 2.0]
        for d in delays {
            let title = "\(d) 秒" + (d == 1.0 ? " (默认)" : "")
            let item = NSMenuItem(title: title, action: #selector(selectDelay(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = d
            item.state = (AppState.shared.bufferDelay == d) ? .on : .off
            delayMenu.addItem(item)
        }
        let delayItem = NSMenuItem(title: "回车缓冲延时", action: nil, keyEquivalent: "")
        delayItem.submenu = delayMenu
        menu.addItem(delayItem)

        let soundMenu = NSMenu()
        let themes = [
            ("codex-notification", "Codex 提示音 (codex-notification - 默认)"),
            ("tink", "清脆音 (Tink)"),
            ("pop", "水滴音 (Pop)"),
            ("ping", "高音提示 (Ping)"),
            ("glass", "玻璃碰撞音 (Glass)"),
            ("hero", "经典凯旋音 (Hero)"),
            ("sosumi", "经典警报音 (Sosumi)")
        ]
        for (th, title) in themes {
            let item = NSMenuItem(title: title, action: #selector(selectSoundTheme(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = th
            item.state = (AppState.shared.soundTheme == th) ? .on : .off
            soundMenu.addItem(item)
        }
        let soundMenuItem = NSMenuItem(title: "提示音音效选择", action: nil, keyEquivalent: "")
        soundMenuItem.submenu = soundMenu
        menu.addItem(soundMenuItem)

        let soundItem = NSMenuItem(title: "开启回车提示音", action: #selector(toggleSound), keyEquivalent: "")
        soundItem.target = self
        soundItem.state = AppState.shared.playSound ? .on : .off
        menu.addItem(soundItem)

        let fuseItem = NSMenuItem(title: "高危指令安全熔断 (拦截 rm -rf 等)", action: #selector(toggleFuse), keyEquivalent: "")
        fuseItem.target = self
        fuseItem.state = AppState.shared.safetyFuseEnabled ? .on : .off
        menu.addItem(fuseItem)

        menu.addItem(NSMenuItem.separator())

        let hookInstalled = HookManager.isHookInstalled()
        let hookTitle = hookInstalled ? "Antigravity Hook: 🟢 已生效" : "Antigravity Hook: 🔴 未安装"
        let hookItem = NSMenuItem(title: hookTitle, action: #selector(reinstallHook), keyEquivalent: "")
        hookItem.target = self
        menu.addItem(hookItem)

        menu.addItem(NSMenuItem.separator())

        let updateItem = NSMenuItem(title: "检查新版本 (自动更新)...", action: #selector(manualCheckUpdate), keyEquivalent: "u")
        updateItem.target = self
        menu.addItem(updateItem)

        let axItem = NSMenuItem(title: "请求 macOS 辅助功能权限...", action: #selector(requestAccessibility), keyEquivalent: "")
        axItem.target = self
        menu.addItem(axItem)

        let logItem = NSMenuItem(title: "查看运行日志...", action: #selector(openLogs), keyEquivalent: "")
        logItem.target = self
        menu.addItem(logItem)

        menu.addItem(NSMenuItem.separator())

        let aboutItem = NSMenuItem(title: "关于 AntiEnter...", action: #selector(showAbout), keyEquivalent: "")
        aboutItem.target = self
        menu.addItem(aboutItem)

        let quitItem = NSMenuItem(title: "退出 AntiEnter", action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        statusItem.menu = menu
    }

    @objc func toggleEnabled() {
        AppState.shared.isEnabled.toggle()
        AppState.shared.advanceGeneration()
        AppState.shared.savePersistentConfig()
        updateStatusItemAppearance()
        buildMenu()
        AppState.shared.log("切换运行状态为: \(AppState.shared.isEnabled ? "启用" : "停用")")
    }

    @objc func selectDelay(_ sender: NSMenuItem) {
        if let d = sender.representedObject as? Double {
            AppState.shared.bufferDelay = d
            AppState.shared.savePersistentConfig()
            buildMenu()
            AppState.shared.log("设置延时为: \(d) 秒")
        }
    }

    @objc func selectSoundTheme(_ sender: NSMenuItem) {
        if let theme = sender.representedObject as? String {
            AppState.shared.soundTheme = theme
            AppState.shared.savePersistentConfig()
            buildMenu()
            AppState.shared.playCueSound()
            AppState.shared.log("设置提示音为: \(theme)")
        }
    }

    @objc func toggleSound() {
        AppState.shared.playSound.toggle()
        AppState.shared.savePersistentConfig()
        buildMenu()
    }

    @objc func toggleFuse() {
        AppState.shared.safetyFuseEnabled.toggle()
        AppState.shared.advanceGeneration()
        AppState.shared.savePersistentConfig()
        buildMenu()
    }

    @objc func reinstallHook() {
        HookManager.installHook()
        buildMenu()
        let alert = NSAlert()
        alert.messageText = "Hook 已成功安装"
        alert.informativeText = "Antigravity 全局生命周期 Hook 已配置生效，桌面端与 CLI 工具调用将免审批。"
        alert.runModal()
    }

    @objc func manualCheckUpdate() {
        UpdateService.shared.checkForUpdates(silentIfLatest: false)
    }

    @objc func requestAccessibility() {
        AccessibilityService.promptAccessibility()
    }

    @objc func openLogs() {
        NSWorkspace.shared.open(AppState.shared.logFile)
    }

    @objc func showAbout() {
        let alert = NSAlert()
        alert.messageText = "AntiEnter v\(AppState.shared.version)"
        alert.informativeText = "Antigravity 自动回车与完全权限自主插件\n支持 Antigravity 桌面端与 CLI 全自动无人值守模式。\n具备事务级更新回滚、精确按钮判定与安全熔断。\n\nGitHub: https://github.com/MingWangD/AntiEnter"
        alert.runModal()
    }

    @objc func quitApp() {
        AppState.shared.isEnabled = false
        AppState.shared.advanceGeneration()
        AppState.shared.savePersistentConfig()
        AppState.shared.unregisterInstance()
        HookManager.uninstallHook()
        AppState.shared.log("AntiEnter 退出，已停用并恢复手动模式")
        NSApplication.shared.terminate(nil)
    }

    func startWatcherTimer() {
        timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            self?.checkActiveWindow()
        }
    }

    func checkActiveWindow() {
        guard AppState.shared.isEnabled else { return }
        guard let frontApp = NSWorkspace.shared.frontmostApplication else { return }

        let appName = frontApp.localizedName ?? ""
        let bundleId = frontApp.bundleIdentifier ?? ""

        let matched = AppState.shared.targetApps.contains { target in
            appName.localizedCaseInsensitiveContains(target) || bundleId.localizedCaseInsensitiveContains(target)
        }
        guard matched else { return }

        let now = Date().timeIntervalSince1970
        guard now - AppState.shared.lastTriggerTime > AppState.shared.cooldown else { return }

        let targetPid = frontApp.processIdentifier
        let appElement = AXUIElementCreateApplication(targetPid)

        if let target = AccessibilityService.findConfirmationTarget(appElement: appElement) {
            AppState.shared.lastTriggerTime = now
            let capturedGen = AppState.shared.currentGeneration
            let delay = AppState.shared.bufferDelay

            AppState.shared.log("检测到 [\(appName)] 明确确认目标 (\(target.matchedText))，开始 \(delay)s 缓冲倒计时...")
            AppState.shared.playCueSound()

            DispatchQueue.global().asyncAfter(deadline: .now() + delay) {
                // 执行前再次校验：启用状态、代次、前台应用与确认目标依然有效
                guard AppState.shared.isEnabled else {
                    AppState.shared.log("应用已暂停，丢弃排队动作")
                    return
                }
                guard AppState.shared.currentGeneration == capturedGen else {
                    AppState.shared.log("策略变更或已重置，丢弃排队动作")
                    return
                }
                guard let currentFront = NSWorkspace.shared.frontmostApplication,
                      currentFront.processIdentifier == targetPid else {
                    AppState.shared.log("前台应用已切换，取消动作")
                    return
                }

                let currentAppElement = AXUIElementCreateApplication(targetPid)
                guard let currentTarget = AccessibilityService.findConfirmationTarget(appElement: currentAppElement) else {
                    AppState.shared.log("确认目标已关闭或消失，取消动作")
                    return
                }

                AccessibilityService.performActionOrReturn(target: currentTarget)
                AppState.shared.lastTriggerTime = Date().timeIntervalSince1970
                AppState.shared.log("触发确认动作完成！")
            }
        }
    }
}

// MARK: - Main Application Entry
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
