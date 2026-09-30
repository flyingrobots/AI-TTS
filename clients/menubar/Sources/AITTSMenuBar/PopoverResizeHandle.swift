// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import AppKit
import SwiftUI

struct PopoverResizeHandle: NSViewRepresentable {
    let height: CGFloat
    let onResize: (CGFloat) -> Void

    func makeNSView(context: Context) -> PopoverResizeGrip { PopoverResizeGrip() }
    func updateNSView(_ view: PopoverResizeGrip, context: Context) {
        view.height = height
        view.onResize = onResize
    }
}

final class PopoverResizeGrip: NSView {
    var height: CGFloat = 500
    var onResize: (CGFloat) -> Void = { _ in }
    private var startY: CGFloat = 0
    private var startHeight: CGFloat = 0

    override init(frame: NSRect) {
        super.init(frame: frame)
        toolTip = "Drag to resize the menu height"
        setAccessibilityLabel("Resize menu height")
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func resetCursorRects() { addCursorRect(bounds, cursor: .resizeUpDown) }
    override func draw(_ dirtyRect: NSRect) {
        NSColor.tertiaryLabelColor.setFill()
        NSBezierPath(roundedRect: NSRect(x: bounds.midX - 18, y: bounds.midY - 2,
                                         width: 36, height: 4), xRadius: 2, yRadius: 2).fill()
    }
    override func mouseDown(with event: NSEvent) {
        startY = window?.convertPoint(toScreen: event.locationInWindow).y ?? 0
        startHeight = height
    }
    override func mouseDragged(with event: NSEvent) {
        guard let window else { return }
        let screenY = window.convertPoint(toScreen: event.locationInWindow).y
        onResize(startHeight + startY - screenY)
    }
}
