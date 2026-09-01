// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// The tray icon family from docs/design/mockups/tray-icon-states.svg:
// one container (a speech bubble) and five marks — only what is inside the
// bubble changes. Idle is the only outlined state, so weight alone answers
// "is it doing anything". Only synthesizing and playing animate, so motion in
// the menu bar always means work in flight.

import AppKit

enum TrayState: Equatable {
    case error  // daemon unreachable, or the daemon reports trouble
    case playing
    case paused
    case synthesizing
    case idle

    static func from(reachable: Bool, daemonState: String?) -> TrayState {
        guard reachable, let daemonState else { return .error }
        switch daemonState {
        case "playing": return .playing
        case "paused": return .paused
        case "synthesizing": return .synthesizing
        default: return .idle
        }
    }

    var animates: Bool { self == .playing || self == .synthesizing }
}

enum TrayIcon {
    static let size = NSSize(width: 18, height: 18)
    static let phases = 3

    /// Render one template-image frame for a state. `phase` drives animation.
    static func frame(state: TrayState, phase: Int = 0) -> NSImage {
        let image = NSImage(size: size, flipped: false) { _ in
            draw(state: state, phase: phase)
            return true
        }
        image.isTemplate = true
        return image
    }

    // MARK: - Drawing (18 × 18 pt, origin bottom-left)

    private static func bubblePath() -> NSBezierPath {
        let path = NSBezierPath(
            roundedRect: NSRect(x: 1.2, y: 4.6, width: 15.6, height: 11.8),
            xRadius: 3.2, yRadius: 3.2)
        let tail = NSBezierPath()
        tail.move(to: NSPoint(x: 4.2, y: 5.2))
        tail.line(to: NSPoint(x: 3.2, y: 1.2))
        tail.line(to: NSPoint(x: 8.4, y: 5.0))
        tail.close()
        path.append(tail)
        return path
    }

    private static func draw(state: TrayState, phase: Int) {
        let bubble = bubblePath()
        if state == .idle {
            // Outlined: the only stroked member of the family.
            NSColor.black.setStroke()
            bubble.lineWidth = 1.5
            bubble.stroke()
            return
        }
        NSColor.black.setFill()
        bubble.fill()
        // Knock the mark out of the filled bubble so the template alpha
        // carries the shape whatever the bar tint is.
        NSGraphicsContext.current?.compositingOperation = .destinationOut
        switch state {
        case .synthesizing: drawDots(phase: phase)
        case .playing: drawBars(phase: phase)
        case .paused: drawPause()
        case .error: drawExclamation()
        case .idle: break
        }
        NSGraphicsContext.current?.compositingOperation = .sourceOver
    }

    private static func drawDots(phase: Int) {
        let midY: CGFloat = 10.2
        for (index, x) in [CGFloat(5.4), 9.0, 12.6].enumerated() {
            let radius: CGFloat = index == phase % 3 ? 1.6 : 1.05
            NSBezierPath(
                ovalIn: NSRect(
                    x: x - radius, y: midY - radius, width: radius * 2, height: radius * 2)
            ).fill()
        }
    }

    private static func drawBars(phase: Int) {
        let heights: [[CGFloat]] = [
            [3.2, 6.6, 4.4, 7.4],
            [5.6, 4.0, 7.2, 4.6],
            [4.2, 7.4, 3.4, 6.2],
        ]
        let midY: CGFloat = 10.4
        for (index, x) in [CGFloat(4.6), 7.6, 10.6, 13.6].enumerated() {
            let height = heights[phase % heights.count][index]
            NSBezierPath(
                rect: NSRect(x: x - 0.8, y: midY - height / 2, width: 1.6, height: height)
            ).fill()
        }
    }

    private static func drawPause() {
        for x in [CGFloat(6.6), 10.4] {
            NSBezierPath(rect: NSRect(x: x, y: 7.2, width: 1.9, height: 6.2)).fill()
        }
    }

    private static func drawExclamation() {
        NSBezierPath(
            roundedRect: NSRect(x: 8.1, y: 8.6, width: 1.9, height: 5.2),
            xRadius: 0.95, yRadius: 0.95
        ).fill()
        NSBezierPath(ovalIn: NSRect(x: 8.0, y: 6.0, width: 2.1, height: 2.1)).fill()
    }
}
