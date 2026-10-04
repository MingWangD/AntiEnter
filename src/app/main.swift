import Cocoa
import ApplicationServices

// MARK: - App Configuration
class AppState {
    static let shared = AppState()
    
    var isEnabled: Bool = true
    var bufferDelay: Double = 1.0
    var playSound: Bool = true
    var safetyFuseEnabled: Bool = true
    
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
    
    let confirmKeywords: [String] = [
        "Proceed", "Allow", "Run", "Submit", "Continue", "Confirm", "Yes", "OK",
        "确定", "允许", "继续", "执行", "好"
    ]
    
    var configDir: URL {
        let home = FileManager.default.homeDirectoryForCurrentUser
        return home.appendingPathComponent(".gemini")
    }
    
    var globalHooksFile: URL {
        let home = FileManager.default.homeDirectoryForCurrentUser
        return home.appendingPathComponent(".gemini/config/hooks.json")
    }
    
    var logFile: URL {
        return configDir.appendingPathComponent("antienter.log")
    }
    
    func log(_ message: String) {
        let timestamp = ISO8601DateFormatter().string(from: Date())
        let line = "[\(timestamp)] \(message)\n"
        if let data = line.data(using: .utf8) {
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
}

// MARK: - Accessibility Helper
class AccessibilityService {
    static func isTrusted() -> Bool {
        return AXIsProcessTrusted()
    }
    
    static func promptAccessibility() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
    }
    
    static func hasConfirmationDialog(appElement: AXUIElement) -> Bool {
        var windowsRef: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(appElement, kAXWindowsAttribute as CFString, &windowsRef)
        guard result == .success, let windows = windowsRef as? [AXUIElement] else {
            return false
        }
        
        for window in windows {
            if scanElement(window, depth: 0) {
                return true
            }
        }
        return false
    }
    
    private static func scanElement(_ element: AXUIElement, depth: Int) -> Bool {
        if depth > 5 { return false }
        
        var roleRef: CFTypeRef?
        if AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &roleRef) == .success,
           let role = roleRef as? String {
            
            if role == (kAXSheetRole as String) || role == (kAXDrawerRole as String) {
                return true
            }
            
            if role == (kAXButtonRole as String) {
                var titleRef: CFTypeRef?
                if AXUIElementCopyAttributeValue(element, kAXTitleAttribute as CFString, &titleRef) == .success,
                   let title = titleRef as? String {
                    let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
                    for kw in AppState.shared.confirmKeywords {
                        if trimmed.caseInsensitiveCompare(kw) == .orderedSame || trimmed.contains(kw) {
                            return true
                        }
                    }
                }
            }
        }
        
        var childrenRef: CFTypeRef?
        if AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &childrenRef) == .success,
           let children = childrenRef as? [AXUIElement] {
            for child in children {
                if scanElement(child, depth: depth + 1) {
                    return true
                }
            }
        }
        return false
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
    static func installHook() {
        let hooksURL = AppState.shared.globalHooksFile
        let configDir = hooksURL.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: configDir, withIntermediateDirectories: true)
        
        // 优先使用标准安装目录或工作区固定路径，避免 AppTranslocation 临时随机路径
        var chosenPath = "/Applications/AntiEnter.app/Contents/Resources/scripts/hook_handler.py"
        if !FileManager.default.fileExists(atPath: chosenPath) {
            let workspacePath = "/Users/myw/Desktop/AntiEnter/src/hook_handler.py"
            if FileManager.default.fileExists(atPath: workspacePath) {
                chosenPath = workspacePath
            } else {
                chosenPath = Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/scripts/hook_handler.py").path
            }
        }
        
        var hooks: [String: Any] = [:]
        if let data = try? Data(contentsOf: hooksURL),
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            hooks = json
        }
        
        hooks["antienter-auto-approver"] = [
            "enabled": true,
            "PreToolUse": [
                [
                    "matcher": "*",
                    "hooks": [
                        [
                            "type": "command",
                            "command": "python3 \(chosenPath)",
                            "timeout": 15
                        ]
                    ]
                ]
            ]
        ]
        
        if let outputData = try? JSONSerialization.data(withJSONObject: hooks, options: [.prettyPrinted]) {
            try? outputData.write(to: hooksURL)
            AppState.shared.log("Hook 已成功安装/更新至 \(hooksURL.path) (指向 \(chosenPath))")
        }
    }
    
    static func uninstallHook() {
        let hooksURL = AppState.shared.globalHooksFile
        guard FileManager.default.fileExists(atPath: hooksURL.path) else { return }
        
        if let data = try? Data(contentsOf: hooksURL),
           var hooks = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            hooks.removeValue(forKey: "antienter-auto-approver")
            if let outputData = try? JSONSerialization.data(withJSONObject: hooks, options: [.prettyPrinted]) {
                try? outputData.write(to: hooksURL)
                AppState.shared.log("Hook 已从全局配置移除")
            }
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

// MARK: - App Delegate & Menu Bar Controller
class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    var statusItem: NSStatusItem!
    var timer: Timer?
    
    func applicationDidFinishLaunching(_ notification: Notification) {
        HookManager.installHook()
        setupStatusBar()
        startWatcherTimer()
        
        if !AccessibilityService.isTrusted() {
            AccessibilityService.promptAccessibility()
        }
        
        AppState.shared.log("AntiEnter.app 启动就绪")
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
        
        // 状态标题项
        let statusTitle = AppState.shared.isEnabled ? "🟢 AntiEnter: 自动回车已激活" : "🔴 AntiEnter: 已暂停"
        let statusItemMenu = NSMenuItem(title: statusTitle, action: nil, keyEquivalent: "")
        statusItemMenu.isEnabled = false
        menu.addItem(statusItemMenu)
        menu.addItem(NSMenuItem.separator())
        
        // 启用/停用开关
        let toggleTitle = AppState.shared.isEnabled ? "暂停自动回车" : "恢复自动回车"
        let toggleItem = NSMenuItem(title: toggleTitle, action: #selector(toggleEnabled), keyEquivalent: "t")
        toggleItem.target = self
        menu.addItem(toggleItem)
        
        menu.addItem(NSMenuItem.separator())
        
        // 缓冲延迟子菜单
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
        
        // 提示音开关
        let soundItem = NSMenuItem(title: "播放回车提示音 (Tink)", action: #selector(toggleSound), keyEquivalent: "")
        soundItem.target = self
        soundItem.state = AppState.shared.playSound ? .on : .off
        menu.addItem(soundItem)
        
        // 安全熔断开关
        let fuseItem = NSMenuItem(title: "高危指令安全熔断 (拦截 rm -rf 等)", action: #selector(toggleFuse), keyEquivalent: "")
        fuseItem.target = self
        fuseItem.state = AppState.shared.safetyFuseEnabled ? .on : .off
        menu.addItem(fuseItem)
        
        menu.addItem(NSMenuItem.separator())
        
        // Hook 状态
        let hookInstalled = HookManager.isHookInstalled()
        let hookTitle = hookInstalled ? "Antigravity Hook: 🟢 已生效" : "Antigravity Hook: 🔴 未安装"
        let hookItem = NSMenuItem(title: hookTitle, action: #selector(reinstallHook), keyEquivalent: "")
        hookItem.target = self
        menu.addItem(hookItem)
        
        menu.addItem(NSMenuItem.separator())
        
        // 辅助功能授权检测
        let axItem = NSMenuItem(title: "请求 macOS 辅助功能权限...", action: #selector(requestAccessibility), keyEquivalent: "")
        axItem.target = self
        menu.addItem(axItem)
        
        // 日志查看
        let logItem = NSMenuItem(title: "查看运行日志...", action: #selector(openLogs), keyEquivalent: "")
        logItem.target = self
        menu.addItem(logItem)
        
        menu.addItem(NSMenuItem.separator())
        
        // 关于
        let aboutItem = NSMenuItem(title: "关于 AntiEnter...", action: #selector(showAbout), keyEquivalent: "")
        aboutItem.target = self
        menu.addItem(aboutItem)
        
        // 退出
        let quitItem = NSMenuItem(title: "退出 AntiEnter", action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)
        
        statusItem.menu = menu
    }
    
    @objc func toggleEnabled() {
        AppState.shared.isEnabled.toggle()
        updateStatusItemAppearance()
        buildMenu()
        AppState.shared.log("切换运行状态为: \(AppState.shared.isEnabled ? "启用" : "停用")")
    }
    
    @objc func selectDelay(_ sender: NSMenuItem) {
        if let d = sender.representedObject as? Double {
            AppState.shared.bufferDelay = d
            buildMenu()
            AppState.shared.log("设置延时为: \(d) 秒")
        }
    }
    
    @objc func toggleSound() {
        AppState.shared.playSound.toggle()
        buildMenu()
    }
    
    @objc func toggleFuse() {
        AppState.shared.safetyFuseEnabled.toggle()
        buildMenu()
    }
    
    @objc func reinstallHook() {
        HookManager.installHook()
        buildMenu()
        let alert = NSAlert()
        alert.messageText = "Hook 已成功安装"
        alert.informativeText = "Antigravity 全局生命周期 Hook 已配置生效，桌面端与 CLI 工具调用将全部免审批。"
        alert.runModal()
    }
    
    @objc func requestAccessibility() {
        AccessibilityService.promptAccessibility()
    }
    
    @objc func openLogs() {
        NSWorkspace.shared.open(AppState.shared.logFile)
    }
    
    @objc func showAbout() {
        let alert = NSAlert()
        alert.messageText = "AntiEnter v1.0.0"
        alert.informativeText = "Antigravity 自动回车与完全权限自主插件\n支持 Antigravity 桌面端与 CLI 全自动无人值守模式。\n\nGitHub 开源项目。"
        alert.runModal()
    }
    
    @objc func quitApp() {
        AppState.shared.log("AntiEnter 退出")
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
        
        let appElement = AXUIElementCreateApplication(frontApp.processIdentifier)
        if AccessibilityService.hasConfirmationDialog(appElement: appElement) {
            AppState.shared.log("检测到 [\(appName)] 等待确认界面，开始 \(AppState.shared.bufferDelay)s 缓冲倒计时...")
            
            if AppState.shared.playSound {
                if let sound = NSSound(named: "Tink") {
                    sound.play()
                }
            }
            
            DispatchQueue.global().asyncAfter(deadline: .now() + AppState.shared.bufferDelay) {
                if let current = NSWorkspace.shared.frontmostApplication,
                   current.processIdentifier == frontApp.processIdentifier {
                    AccessibilityService.sendReturn()
                    AppState.shared.lastTriggerTime = Date().timeIntervalSince1970
                    AppState.shared.log("触发 Return 回车确认完成！")
                }
            }
        }
    }
}

// MARK: - Main Application Entry
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory) // 菜单栏常驻模式，不在 Dock 栏显眼占用
app.run()
