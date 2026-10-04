import Foundation
import AppKit
import ApplicationServices

// MARK: - Configuration
struct Config {
    static var bufferDelay: TimeInterval = 1.0
    static var playSound: Bool = true
    static var targetApps: Set<String> = [
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
    static var confirmButtonKeywords: [String] = [
        "Yes, allow this time",
        "Allow this time",
        "Yes, and always allow",
        "Always allow",
        "Allow searching",
        "Allow pushing",
        "Allow running",
        "Allow editing",
        "Allow writing",
        "Skip",
        "Submit ↵",
        "Proceed",
        "Confirm",
        "确定",
        "允许",
        "好"
    ]
}

// MARK: - Audio Cue
func playAudioCue() {
    guard Config.playSound else { return }
    DispatchQueue.global(qos: .userInitiated).async {
        if let sound = NSSound(named: "Tink") {
            sound.play()
        } else {
            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: "/usr/bin/afplay")
            proc.arguments = ["/System/Library/Sounds/Tink.aiff"]
            try? proc.run()
        }
    }
}

// MARK: - Key Event Simulation
func sendReturnKey() {
    let returnKeyCode: CGKeyCode = 36 // macOS Virtual Key Code for Return
    let source = CGEventSource(stateID: .hidSystemState)
    
    if let eventDown = CGEvent(keyboardEventSource: source, virtualKey: returnKeyCode, keyDown: true),
       let eventUp = CGEvent(keyboardEventSource: source, virtualKey: returnKeyCode, keyDown: false) {
        eventDown.post(tap: .cghidEventTap)
        usleep(30000) // 30ms hold
        eventUp.post(tap: .cghidEventTap)
    }
}

// MARK: - Accessibility Helper
class AccessibilityChecker {
    static func isTrusted() -> Bool {
        return AXIsProcessTrusted()
    }
    
    static func requestPermissions() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
    }
    
    static func hasConfirmationDialog(appElement: AXUIElement) -> Bool {
        // 检查窗口或弹窗中是否有确认元素
        var windowsRef: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(appElement, kAXWindowsAttribute as CFString, &windowsRef)
        guard result == .success, let windows = windowsRef as? [AXUIElement] else {
            return false
        }
        
        for window in windows {
            if inspectElementForConfirmation(window, depth: 0) {
                return true
            }
        }
        return false
    }
    
    private static func inspectElementForConfirmation(_ element: AXUIElement, depth: Int) -> Bool {
        if depth > 25 { return false } // 增加深度至 25，适配 Electron/Web 深度嵌套 DOM
        
        // 1. 检查当前元素角色
        var roleRef: CFTypeRef?
        if AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &roleRef) == .success,
           let role = roleRef as? String {
            
            // 如果是弹窗对话框或者浮层
            if role == (kAXSheetRole as String) || role == (kAXDrawerRole as String) {
                return true
            }
        }
        
        // 检查 Title, Description, Value 是否包含弹窗特征
        let attrs = [kAXTitleAttribute, kAXDescriptionAttribute, kAXValueAttribute]
        for attr in attrs {
            var valRef: CFTypeRef?
            if AXUIElementCopyAttributeValue(element, attr as CFString, &valRef) == .success,
               let valStr = valRef as? String {
                let trimmed = valStr.trimmingCharacters(in: .whitespacesAndNewlines)
                for kw in Config.confirmButtonKeywords {
                    if trimmed.localizedCaseInsensitiveContains(kw) {
                        return true
                    }
                }
            }
        }
        
        // 2. 检查子元素
        var childrenRef: CFTypeRef?
        if AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &childrenRef) == .success,
           let children = childrenRef as? [AXUIElement] {
            for child in children {
                if inspectElementForConfirmation(child, depth: depth + 1) {
                    return true
                }
            }
        }
        
        return false
    }
}

// MARK: - Daemon Engine
class DaemonEngine {
    private var lastTriggerTime: TimeInterval = 0
    private let cooldownTime: TimeInterval = 2.0 // 触发后 2 秒冷却，防止连击
    
    func start() {
        print("[AntiEnter Daemon] 启动中...")
        print("[AntiEnter Daemon] 缓冲延时: \(Config.bufferDelay) 秒")
        print("[AntiEnter Daemon] 提示音: \(Config.playSound ? "开启" : "关闭")")
        
        if !AccessibilityChecker.isTrusted() {
            print("[警告] 尚未授予辅助功能权限 (Accessibility)！")
            print("[提示] 正在请求权限，请在 macOS 系统设置 -> 隐私与安全性 -> 辅助功能 中允许此程序。")
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
        guard let frontApp = NSWorkspace.shared.frontmostApplication else { return }
        let appName = frontApp.localizedName ?? ""
        let bundleId = frontApp.bundleIdentifier ?? ""
        
        // 检查前台应用是否为目标应用
        let matches = Config.targetApps.contains { target in
            appName.localizedCaseInsensitiveContains(target) || bundleId.localizedCaseInsensitiveContains(target)
        }
        
        guard matches else { return }
        
        let now = Date().timeIntervalSince1970
        guard now - lastTriggerTime > cooldownTime else { return }
        
        let appElement = AXUIElementCreateApplication(frontApp.processIdentifier)
        if AccessibilityChecker.hasConfirmationDialog(appElement: appElement) {
            lastTriggerTime = now // 立即锁定触发时间，避免轮询重复触发
            print("[AntiEnter] 检测到 [\(appName)] 中存在等待确认的对话框/按钮，开始 \(Config.bufferDelay)s 缓冲倒计时...")
            playAudioCue()
            
            DispatchQueue.global().asyncAfter(deadline: .now() + Config.bufferDelay) { [weak self] in
                // 再次确认前台未切走
                if let currentFront = NSWorkspace.shared.frontmostApplication,
                   currentFront.processIdentifier == frontApp.processIdentifier {
                    print("[AntiEnter] 触发 Return 回车确认！")
                    sendReturnKey()
                    self?.lastTriggerTime = Date().timeIntervalSince1970
                }
            }
        }
    }
}

// MARK: - Main
let engine = DaemonEngine()
engine.start()
