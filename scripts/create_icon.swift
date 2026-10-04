import Cocoa

let size = NSSize(width: 1024, height: 1024)
let image = NSImage(size: size)

image.lockFocus()

// 背景：现代深色圆角矩形渐变（科技深蓝到蓝紫色）
let rect = NSRect(origin: .zero, size: size)
let roundedPath = NSBezierPath(roundedRect: rect.insetBy(dx: 40, dy: 40), xRadius: 220, yRadius: 220)

let gradient = NSGradient(colors: [
    NSColor(red: 0.10, green: 0.12, blue: 0.22, alpha: 1.0),
    NSColor(red: 0.18, green: 0.22, blue: 0.45, alpha: 1.0),
    NSColor(red: 0.12, green: 0.35, blue: 0.70, alpha: 1.0)
])!
gradient.draw(in: roundedPath, angle: -45)

// 外边框微光
NSColor(white: 1.0, alpha: 0.15).setStroke()
roundedPath.lineWidth = 12
roundedPath.stroke()

// 中间绘制闪电与回车符号
let text = "⚡⏎"
let font = NSFont.systemFont(ofSize: 420, weight: .bold)
let textAttributes: [NSAttributedString.Key: Any] = [
    .font: font,
    .foregroundColor: NSColor(red: 0.30, green: 0.85, blue: 1.0, alpha: 1.0)
]

let textSize = text.size(withAttributes: textAttributes)
let textRect = NSRect(
    x: (size.width - textSize.width) / 2,
    y: (size.height - textSize.height) / 2 - 20,
    width: textSize.width,
    height: textSize.height
)
text.draw(in: textRect, withAttributes: textAttributes)

image.unlockFocus()

guard let tiffData = image.tiffRepresentation,
      let rep = NSBitmapImageRep(data: tiffData),
      let pngData = rep.representation(using: .png, properties: [:]) else {
    fatalError("无法导出 PNG")
}

let outputPath = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "icon_1024.png"
try! pngData.write(to: URL(fileURLWithPath: outputPath))
print("成功生成高分辨率图标: \(outputPath)")
