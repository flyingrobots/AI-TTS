// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned AppKit view/window, controlled pointer events)
// Test-Oracle: dragging the bottom edge changes height by screen displacement, without compounding

import AppKit
import XCTest
@testable import AITTSMenuBar

final class PopoverResizeTests: XCTestCase {
    override func setUp() { super.setUp(); executionTimeAllowance = 15 }

    // Test-Oracle: an explicit preferred height survives a new sizing instance.
    @MainActor
    func testExplicitHeightPersistsAcrossReconstruction() throws {
        let name = "resize-persistence-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        let sizing = PopoverSizing(defaults: defaults)
        sizing.resize(to: 650)
        XCTAssertEqual(PopoverSizing(defaults: defaults).height, 650)
    }

    // Test-Oracle: ordinary displays clamp requested heights to 360...available height.
    @MainActor
    func testRequestedHeightIsClampedToUsableBounds() throws {
        let name = "resize-bounds-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        let sizing = PopoverSizing(defaults: defaults)
        sizing.maximumHeight = 700
        sizing.resize(to: 900)
        XCTAssertEqual(sizing.height, 700)
        sizing.resize(to: 10)
        XCTAssertEqual(sizing.height, 360)
    }

    // Test-Oracle: a screen shorter than the normal minimum takes precedence over it.
    @MainActor
    func testShortScreenTakesPrecedenceOverMinimumHeight() throws {
        let name = "resize-short-screen-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        let sizing = PopoverSizing(defaults: defaults)
        sizing.maximumHeight = 300
        sizing.resize(to: 600)
        XCTAssertEqual(sizing.height, 300)
    }

    @MainActor
    func testDragUsesScreenDisplacementEvenWhenWindowMoves() throws {
        _ = NSApplication.shared
        let window = NSWindow(contentRect: NSRect(x: 100, y: 300, width: 368, height: 500),
                              styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        defer { window.close() }
        let grip = PopoverResizeGrip(frame: NSRect(x: 0, y: 0, width: 368, height: 16))
        window.contentView = grip
        var heights: [CGFloat] = []
        grip.onResize = { heights.append($0); grip.height = $0 }
        func event(_ type: NSEvent.EventType, _ y: CGFloat) throws -> NSEvent {
            try XCTUnwrap(NSEvent.mouseEvent(with: type, location: NSPoint(x: 150, y: y),
                modifierFlags: [], timestamp: 0, windowNumber: window.windowNumber,
                context: nil, eventNumber: 1, clickCount: 1, pressure: 1))
        }
        grip.mouseDown(with: try event(.leftMouseDown, 10)) // screen y=310
        grip.mouseDragged(with: try event(.leftMouseDragged, -70)) // screen y=230
        window.setFrameOrigin(NSPoint(x: 100, y: 220))
        grip.mouseDragged(with: try event(.leftMouseDragged, -10)) // screen y=210
        grip.mouseDragged(with: try event(.leftMouseDragged, 110)) // screen y=330
        XCTAssertEqual(heights, [580, 600, 480])
    }
}
