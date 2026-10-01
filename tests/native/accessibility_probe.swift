// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Read only the explicitly selected application; press/set require explicit arguments.
import Foundation
import ApplicationServices
let args = CommandLine.arguments
guard AXIsProcessTrusted() else { fatalError("Accessibility access is required") }
let app = AXUIElementCreateApplication(Int32(args[1])!)
AXUIElementSetMessagingTimeout(app, 2)
if args.count > 2, args[2] == "press" {
    AXUIElementSetAttributeValue(app, kAXFrontmostAttribute as CFString, kCFBooleanTrue)
}
func read(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else { return nil }
    return value
}
if args.count > 2, args[2] == "windows" {
    print((read(app, "AXWindows") as? [AXUIElement] ?? []).count)
    exit(0)
}
var seen: [AXUIElement] = []
var rows: [[String: String]] = []
var matched = false
func walk(_ element: AXUIElement, _ depth: Int) {
    guard depth < 20, rows.count < 1000, !seen.contains(where: { CFEqual($0, element) }) else { return }
    seen.append(element)
    var row: [String: String] = [:]
    for key in ["AXRole", "AXTitle", "AXDescription", "AXHelp", "AXValue"] {
        if let text = read(element, key) as? String { row[key] = text }
    }
    rows.append(row)
    if args.count > 3, !matched,
       [row["AXTitle"], row["AXDescription"], row["AXHelp"]].contains(args[3]) {
        if args[2] == "press" {
            matched = AXUIElementPerformAction(element, kAXPressAction as CFString) == .success
        } else if args[2] == "set" {
            matched = AXUIElementSetAttributeValue(element, kAXValueAttribute as CFString, args[4] as CFString) == .success
        }
        if matched { return }
    }
    for key in ["AXChildren", "AXWindows", "AXMenuBar", "AXShownMenuUIElement", "AXVisibleChildren", "AXSelectedChildren", "AXContents"] {
        if let children = read(element, key) as? [AXUIElement] {
            for child in children { walk(child, depth + 1) }
        } else if let child = read(element, key), CFGetTypeID(child) == AXUIElementGetTypeID() {
            walk(unsafeBitCast(child, to: AXUIElement.self), depth + 1)
        }
    }
}
walk(app, 0)
let data = try JSONSerialization.data(withJSONObject: rows, options: [.prettyPrinted, .sortedKeys])
print(String(decoding: data, as: UTF8.self))
if args.count > 2, args[2] != "dump", !matched { exit(2) }
