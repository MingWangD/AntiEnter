import Cocoa
import ApplicationServices

// MARK: - App Configuration
class AppState {
    static let shared = AppState()
    
    let version: String = "1.2.0"
    var isEnabled: Bool = true
    var bufferDelay: Double = 1.0
    var playSound: Bool = true
    var soundTheme: String = "tink"
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
    
    // 精准匹配确认授权弹窗关键词，排除 IDE 常驻按钮 (如 Run/Submit/Continue)
    let confirmKeywords: [String] = [
        "Submit ↵", "Yes, allow this time", "Yes, and always allow", "Always allow",
        "Allow this time", "Proceed", "Confirm", "确定", "允许", "好"
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
    
    func playCueSound() {
        guard playSound else { return }
        let soundPath: String
        switch soundTheme {
        case "pop": soundPath = "/System/Library/Sounds/Pop.aiff"
        case "ping": soundPath = "/System/Library/Sounds/Ping.aiff"
        case "glass": soundPath = "/System/Library/Sounds/Glass.aiff"
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

// MARK: - Auto Update Service
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
        alert.informativeText = "【新版本改动】\n\(body)\n\n点击【确认自动更新】将全自动下载并升级最新版，无需前往 GitHub 手动下载。"
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
            let tmpZip = URL(fileURLWithPath: "/tmp/AntiEnter_Update.zip")
            let tmpDir = URL(fileURLWithPath: "/tmp/AntiEnter_Update_Dir")
            try? FileManager.default.removeItem(at: tmpZip)
            try? FileManager.default.removeItem(at: tmpDir)
            
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
            
            let unzipProc = Process()
            unzipProc.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
            unzipProc.arguments = ["-xk", tmpZip.path, tmpDir.path]
            try? unzipProc.run()
            unzipProc.waitUntilExit()
            
            let extractedApp = tmpDir.appendingPathComponent("AntiEnter.app")
            guard FileManager.default.fileExists(atPath: extractedApp.path) else {
                DispatchQueue.main.async {
                    let errAlert = NSAlert()
                    errAlert.messageText = "解压更新失败"
                    errAlert.informativeText = "未在更新包内找到 AntiEnter.app。"
                    errAlert.runModal()
                }
                return
            }
            
            let runningAppPath = Bundle.main.bundleURL.path
            let targetAppPath = runningAppPath.contains("/Applications/") ? runningAppPath : "/Applications/AntiEnter.app"
            
            let scriptPath = "/tmp/antienter_restart.sh"
            let scriptContent = """
            #!/bin/bash
            sleep 1
            rm -rf "\(targetAppPath)"
            cp -R "\(extractedApp.path)" "\(targetAppPath)"
            xattr -cr "\(targetAppPath)" 2>/dev/null || true
            open "\(targetAppPath)"
            rm -rf /tmp/AntiEnter_Update.zip /tmp/AntiEnter_Update_Dir /tmp/antienter_restart.sh
            """
            try? scriptContent.write(toFile: scriptPath, atomically: true, encoding: .utf8)
            
            let chmodProc = Process()
            chmodProc.executableURL = URL(fileURLWithPath: "/bin/chmod")
            chmodProc.arguments = ["+x", scriptPath]
            try? chmodProc.run()
            chmodProc.waitUntilExit()
            
            let relaunchProc = Process()
            relaunchProc.executableURL = URL(fileURLWithPath: "/bin/bash")
            relaunchProc.arguments = [scriptPath]
            try? relaunchProc.run()
            
            DispatchQueue.main.async {
                AppState.shared.log("自动更新至 \(version) 成功，正在重启...")
                NSApplication.shared.terminate(nil)
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
        if depth > 25 { return false } // 搜索深度扩大至 25 层，支持深度嵌套 Web/Electron 视图
        
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
        
        AppState.shared.log("AntiEnter.app (v\(AppState.shared.version)) 启动就绪")
        
        // 启动 3 秒后静默后台检测更新
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) {
            UpdateService.shared.checkForUpdates(silentIfLatest: true)
        }
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
        let statusTitle = AppState.shared.isEnabled ? "🟢 AntiEnter: 自动回车已激活 (v\(AppState.shared.version))" : "🔴 AntiEnter: 已暂停 (v\(AppState.shared.version))"
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
        
        // 音效选择子菜单
        let soundMenu = NSMenu()
        let themes = [
            ("tink", "清脆音 (Tink - 默认)"),
            ("pop", "水滴音 (Pop)"),
            ("ping", "高音提示 (Ping)"),
            ("glass", "玻璃碰撞音 (Glass)")
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
        
        // 提示音开关
        let soundItem = NSMenuItem(title: "开启回车提示音", action: #selector(toggleSound), keyEquivalent: "")
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
        
        // 自动更新检测
        let updateItem = NSMenuItem(title: "检查新版本 (自动更新)...", action: #selector(manualCheckUpdate), keyEquivalent: "u")
        updateItem.target = self
        menu.addItem(updateItem)
        
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
    
    @objc func selectSoundTheme(_ sender: NSMenuItem) {
        if let theme = sender.representedObject as? String {
            AppState.shared.soundTheme = theme
            buildMenu()
            AppState.shared.playCueSound()
            AppState.shared.log("设置提示音为: \(theme)")
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
        alert.informativeText = "Antigravity 自动回车与完全权限自主插件\n支持 Antigravity 桌面端与 CLI 全自动无人值守模式。\n包含自动更新、深层无障碍探测与高危指令熔断功能。\n\nGitHub: https://github.com/MingWangD/AntiEnter"
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
            AppState.shared.lastTriggerTime = now // 立即锁定触发时间，防止 0.5s 轮询重复触发
            AppState.shared.log("检测到 [\(appName)] 等待确认界面，开始 \(AppState.shared.bufferDelay)s 缓冲倒计时...")
            AppState.shared.playCueSound()
            
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
app.setActivationPolicy(.accessory)
app.run()
