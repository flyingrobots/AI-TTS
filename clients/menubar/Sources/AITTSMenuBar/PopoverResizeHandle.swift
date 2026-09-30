// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import AppKit
import SwiftUI

struct PopoverResizeHandle: NSViewRepresentable {
    let height: CGFloat
    var maximumHeight: CGFloat = 1200
    let onResize: (CGFloat) -> Void

    func makeNSView(context: Context) -> PopoverResizeGrip { PopoverResizeGrip() }
    func updateNSView(_ view: PopoverResizeGrip, context: Context) {
        view.height = height
        view.maximumHeight = maximumHeight
        view.onResize = onResize
    }
}

final class PopoverResizeGrip: NSView {
    var height: CGFloat = 500
    var maximumHeight: CGFloat = 1200
    var onResize: (CGFloat) -> Void = { _ in }
    private var startY: CGFloat = 0
    private var startHeight: CGFloat = 0

    override init(frame: NSRect) {
        super.init(frame: frame)
        toolTip = "Drag or use Up/Down arrows to resize the menu height"
        setAccessibilityElement(true)
        setAccessibilityRole(.slider)
        setAccessibilityLabel("Resize menu height")
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override var acceptsFirstResponder: Bool { true }
    override func accessibilityValue() -> Any? { height }
    override func accessibilityMinValue() -> Any? { min(360, maximumHeight) }
    override func accessibilityMaxValue() -> Any? { maximumHeight }
    override func accessibilityPerformIncrement() -> Bool {
        onResize(height + 20)
        return true
    }
    override func accessibilityPerformDecrement() -> Bool {
        onResize(height - 20)
        return true
    }
    override func keyDown(with event: NSEvent) {
        switch event.keyCode {
        case 126: _ = accessibilityPerformIncrement()
        case 125: _ = accessibilityPerformDecrement()
        default: super.keyDown(with: event)
        }
    }

    override func resetCursorRects() { addCursorRect(bounds, cursor: .resizeUpDown) }
    override func draw(_ dirtyRect: NSRect) {
        NSColor.tertiaryLabelColor.setFill()
        NSBezierPath(roundedRect: NSRect(x: bounds.midX - 18, y: bounds.midY - 2,
                                         width: 36, height: 4), xRadius: 2, yRadius: 2).fill()
    }
    override func mouseDown(with event: NSEvent) {
        window?.makeFirstResponder(self)
        startY = window?.convertPoint(toScreen: event.locationInWindow).y ?? 0
        startHeight = height
    }
    override func mouseDragged(with event: NSEvent) {
        guard let window else { return }
        let screenY = window.convertPoint(toScreen: event.locationInWindow).y
        onResize(startHeight + startY - screenY)
    }
}
