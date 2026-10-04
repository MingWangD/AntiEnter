import Foundation
import AppKit
import ApplicationServices

// MARK: - Configuration & Dynamic State
class DaemonConfig {
    static let shared = DaemonConfig()

    var enabled: Bool = true
    var bufferDelay: TimeInterval = 1.0
    var playSound: Bool = true
    var soundTheme: String = "codex-notification"
    var safetyFuseEnabled: Bool = true
    var currentGeneration: Int = 1

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

    // 通用安全流程短语（问答、提交等）
    let safeFlowPhrases: [String] = [
        "submit ↵"
    ]

    // 工具权限授权短语（高危熔断开启时禁止 UI 自动按键）
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

    // 精确按钮词
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

    // 否定词排除
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

    var decisionFile: URL {
        return configDir.appendingPathComponent("antienter_decision.json")
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

    func reload() {
        guard FileManager.default.fileExists(atPath: configFile.path),
              let data = try? Data(contentsOf: configFile),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return
        }
        if let en = json["enabled"] as? Bool { enabled = en }
        if let d = json["buffer_delay"] as? Double, d >= 0 { bufferDelay = d }
        if let ps = json["play_sound"] as? Bool { playSound = ps }
        if let st = json["sound_theme"] as? String { soundTheme = st }
        if let sf = json["safety_fuse_enabled"] as? Bool { safetyFuseEnabled = sf }
        if let gen = json["generation"] as? Int { currentGeneration = gen }
    }
}

// MARK: - Audio Cue
func playAudioCue() {
    guard DaemonConfig.shared.playSound else { return }
    let theme = DaemonConfig.shared.soundTheme.lowercased()

    DispatchQueue.global(qos: .userInitiated).async {
        if theme == "codex-notification" || theme == "codex" {
            let home = FileManager.default.homeDirectoryForCurrentUser
            let execPath = URL(fileURLWithPath: CommandLine.arguments[0])
            let candidates = [
                Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/sounds/codex-notification.wav").path,
                home.appendingPathComponent("Library/Sounds/codex-notification.wav").path,
                execPath.deletingLastPathComponent().appendingPathComponent("../assets/sounds/codex-notification.wav").path,
                URL(fileURLWithPath: FileManager.default.currentDirectoryPath).appendingPathComponent("assets/sounds/codex-notification.wav").path
            ]
            for p in candidates {
                if FileManager.default.fileExists(atPath: p),
                   let sound = NSSound(contentsOfFile: p, byReference: true) {
                    sound.play()
                    return
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

        if FileManager.default.fileExists(atPath: soundPath),
           let sound = NSSound(contentsOfFile: soundPath, byReference: true) {
            sound.play()
        } else {
            NSSound(named: "Tink")?.play()
        }
    }
}

// MARK: - Key Event Simulation
func sendReturnKey() {
    let returnKeyCode: CGKeyCode = 36
    let source = CGEventSource(stateID: .hidSystemState)

    if let eventDown = CGEvent(keyboardEventSource: source, virtualKey: returnKeyCode, keyDown: true),
       let eventUp = CGEvent(keyboardEventSource: source, virtualKey: returnKeyCode, keyDown: false) {
        eventDown.post(tap: .cghidEventTap)
        usleep(30000)
        eventUp.post(tap: .cghidEventTap)
    }
}

// MARK: - Accessibility Helper
struct DaemonConfirmationTarget {
    let window: AXUIElement
    let targetButton: AXUIElement?
    let matchedText: String
}

class AccessibilityChecker {
    static func isTrusted() -> Bool {
        return AXIsProcessTrusted()
    }

    static func requestPermissions() {
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

    static func findConfirmationTarget(appElement: AXUIElement) -> DaemonConfirmationTarget? {
        if DaemonConfig.shared.isHookPendingAsk() {
            return nil
        }
        var windowsRef: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(appElement, kAXWindowsAttribute as CFString, &windowsRef)
        guard result == .success, let windows = windowsRef as? [AXUIElement] else {
            return nil
        }

        for window in windows {
            if DaemonConfig.shared.safetyFuseEnabled && windowContainsDangerContext(element: window) {
                // 窗口包含高危指令或敏感工具调用特征，高危熔断开启时拒绝自动点击
                continue
            }
            let expectedTool = detectWindowTool(element: window)
            if let target = inspectElementForConfirmation(window, window: window, depth: 0, expectedTool: expectedTool) {
                return target
            }
        }
        return nil
    }

    private static func inspectElementForConfirmation(_ element: AXUIElement, window: AXUIElement, depth: Int, expectedTool: String?) -> DaemonConfirmationTarget? {
        if depth > 25 { return nil }

        var roleRef: CFTypeRef?
        let roleSuccess = AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &roleRef)
        let role = (roleSuccess == .success) ? (roleRef as? String ?? "") : ""

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
            var enabledRef: CFTypeRef?
            if AXUIElementCopyAttributeValue(element, kAXEnabledAttribute as CFString, &enabledRef) == .success,
               let isEnabled = enabledRef as? Bool, !isEnabled {
                // 控件处于禁用状态
            } else {
                let textAttrs = [kAXTitleAttribute, kAXDescriptionAttribute]
                for attr in textAttrs {
                    var valRef: CFTypeRef?
                    if AXUIElementCopyAttributeValue(element, attr as CFString, &valRef) == .success,
                       let valStr = valRef as? String {
                        let trimmed = valStr.trimmingCharacters(in: .whitespacesAndNewlines)
                        if trimmed.isEmpty { continue }
                        let lower = trimmed.lowercased()

                        // 否定词排除
                        if DaemonConfig.shared.negativeWords.contains(where: { lower.contains($0) }) {
                            return nil
                        }

                        var allowedPhrases: [String] = []
                        var allowedWords: Set<String> = []
                        if !DaemonConfig.shared.safetyFuseEnabled {
                            allowedPhrases = DaemonConfig.shared.safeFlowPhrases
                            allowedPhrases.append(contentsOf: DaemonConfig.shared.toolPermissionPhrases)
                            allowedWords.formUnion(DaemonConfig.shared.safeExactWords)
                            allowedWords.formUnion(DaemonConfig.shared.toolExactWords)
                        } else if DaemonConfig.shared.hasActiveHookAllowToken(expectedTool: expectedTool) {
                            // 仅当存在 Hook 产生的有效放行令牌且工具匹配时，才允许自动确认（含 Submit ↵ 及通用词）
                            allowedPhrases = DaemonConfig.shared.safeFlowPhrases
                            allowedWords.formUnion(DaemonConfig.shared.safeExactWords)
                        }

                        // 1. 强特征短语
                        for phrase in allowedPhrases {
                            if lower.contains(phrase) {
                                return DaemonConfirmationTarget(window: window, targetButton: element, matchedText: trimmed)
                            }
                        }

                        // 2. 精确按钮词
                        if allowedWords.contains(lower) {
                            return DaemonConfirmationTarget(window: window, targetButton: element, matchedText: trimmed)
                        }
                    }
                }
            }
        }

        if excludedRoles.contains(role) {
            return nil
        }

        var childrenRef: CFTypeRef?
        if AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &childrenRef) == .success,
           let children = childrenRef as? [AXUIElement] {
            for child in children {
                if let target = inspectElementForConfirmation(child, window: window, depth: depth + 1, expectedTool: expectedTool) {
                    return target
                }
            }
        }
        return nil
    }

    static func performAction(target: DaemonConfirmationTarget) {
        DaemonConfig.shared.markTokenConsumed()

        if let button = target.targetButton {
            if AXUIElementPerformAction(button, kAXPressAction as CFString) == .success {
                return
            }
        }

        var focusedRef: CFTypeRef?
        if AXUIElementCopyAttributeValue(target.window, kAXFocusedUIElementAttribute as CFString, &focusedRef) == .success,
           let focusedRaw = focusedRef,
           CFGetTypeID(focusedRaw) == AXUIElementGetTypeID() {
            let focused = focusedRaw as! AXUIElement
            var roleRef: CFTypeRef?
            if AXUIElementCopyAttributeValue(focused, kAXRoleAttribute as CFString, &roleRef) == .success,
               let role = roleRef as? String {
                if role == (kAXTextAreaRole as String) || role == (kAXTextFieldRole as String) {
                    return
                }
            }
        }

        sendReturnKey()
    }
}

// MARK: - Daemon Engine
class DaemonEngine {
    private var lastTriggerTime: TimeInterval = 0
    private let cooldownTime: TimeInterval = 2.0

    func start() {
        DaemonConfig.shared.reload()
        print("[AntiEnter Daemon] 启动中...")
        print("[AntiEnter Daemon] 全局状态: \(DaemonConfig.shared.enabled ? "启用" : "暂停")")
        print("[AntiEnter Daemon] 缓冲延时: \(DaemonConfig.shared.bufferDelay) 秒")
        print("[AntiEnter Daemon] 提示音: \(DaemonConfig.shared.playSound ? "开启" : "关闭") (\(DaemonConfig.shared.soundTheme))")
        print("[AntiEnter Daemon] 高危熔断: \(DaemonConfig.shared.safetyFuseEnabled ? "开启" : "关闭")")

        if !AccessibilityChecker.isTrusted() {
            print("[警告] 尚未授予辅助功能权限 (Accessibility)！")
            AccessibilityChecker.requestPermissions()
        } else {
            print("[AntiEnter Daemon] 辅助功能权限已就绪。")
        }

        let timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            self?.tick()
        }
        RunLoop.current.add(timer, forMode: .default)
        RunLoop.current.run()
    }

    private func tick() {
        DaemonConfig.shared.reload()
        guard DaemonConfig.shared.enabled else { return }
        guard let frontApp = NSWorkspace.shared.frontmostApplication else { return }

        let appName = frontApp.localizedName ?? ""
        let bundleId = frontApp.bundleIdentifier ?? ""

        let matches = DaemonConfig.shared.targetApps.contains { target in
            appName.localizedCaseInsensitiveContains(target) || bundleId.localizedCaseInsensitiveContains(target)
        }
        guard matches else { return }

        let now = Date().timeIntervalSince1970
        guard now - lastTriggerTime > cooldownTime else { return }

        let targetPid = frontApp.processIdentifier
        let appElement = AXUIElementCreateApplication(targetPid)

        if let target = AccessibilityChecker.findConfirmationTarget(appElement: appElement) {
            lastTriggerTime = now
            let capturedGen = DaemonConfig.shared.currentGeneration
            let delay = DaemonConfig.shared.bufferDelay

            print("[AntiEnter] 检测到 [\(appName)] 明确确认目标 (\(target.matchedText))，开始 \(delay)s 缓冲倒计时...")
            playAudioCue()

            DispatchQueue.global().asyncAfter(deadline: .now() + delay) { [weak self] in
                DaemonConfig.shared.reload()
                guard DaemonConfig.shared.enabled else {
                    print("[AntiEnter] 已暂停，丢弃排队动作")
                    return
                }
                guard DaemonConfig.shared.currentGeneration == capturedGen else {
                    print("[AntiEnter] 策略变更或代次失效，丢弃排队动作")
                    return
                }
                guard let currentFront = NSWorkspace.shared.frontmostApplication,
                      currentFront.processIdentifier == targetPid else {
                    print("[AntiEnter] 前台已切换，取消动作")
                    return
                }

                let curAppElem = AXUIElementCreateApplication(targetPid)
                guard let curTarget = AccessibilityChecker.findConfirmationTarget(appElement: curAppElem) else {
                    print("[AntiEnter] 确认目标已消失，取消动作")
                    return
                }

                print("[AntiEnter] 触发确认动作完成！")
                AccessibilityChecker.performAction(target: curTarget)
                self?.lastTriggerTime = Date().timeIntervalSince1970
            }
        }
    }
}

// MARK: - Main
let engine = DaemonEngine()
engine.start()
