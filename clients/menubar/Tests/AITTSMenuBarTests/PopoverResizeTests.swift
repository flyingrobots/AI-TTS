// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned AppKit view/window, controlled pointer events)
// Test-Oracle: dragging the bottom edge changes height by screen displacement, without compounding

import AITTSApplication
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

    // Test-Oracle: a height accepted on a tall display survives reconstruction unchanged.
    @MainActor
    func testTallDisplayHeightSurvivesRelaunch() throws {
        let name = "resize-tall-display-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        let sizing = PopoverSizing(defaults: defaults)
        sizing.maximumHeight = 1800
        sizing.resize(to: 1500)
        XCTAssertEqual(sizing.height, 1500)
        XCTAssertEqual(PopoverSizing(defaults: defaults).height, 1500)
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
    // Test-Oracle: keyboard and accessibility users can adjust the same height value as dragging.
    @MainActor
    func testGripSupportsKeyboardAndAccessibilityAdjustment() throws {
        _ = NSApplication.shared
        let grip = PopoverResizeGrip(frame: NSRect(x: 0, y: 0, width: 368, height: 16))
        var requests: [CGFloat] = []
        grip.onResize = { requests.append($0) }
        grip.height = 500
        XCTAssertTrue(grip.isAccessibilityElement())
        XCTAssertEqual(grip.accessibilityRole(), .slider)
        XCTAssertEqual(grip.accessibilityValue() as? CGFloat, 500)
        XCTAssertEqual(grip.accessibilityMinValue() as? CGFloat, 360)
        XCTAssertEqual(grip.accessibilityMaxValue() as? CGFloat, 1200)
        grip.maximumHeight = 300
        XCTAssertEqual(grip.accessibilityMinValue() as? CGFloat, 300)
        XCTAssertEqual(grip.accessibilityMaxValue() as? CGFloat, 300)
        grip.maximumHeight = 1200
        XCTAssertTrue(grip.acceptsFirstResponder)
        XCTAssertTrue(grip.accessibilityPerformIncrement())
        XCTAssertTrue(grip.accessibilityPerformDecrement())
        for key: UInt16 in [126, 125] {
            let event = try XCTUnwrap(NSEvent.keyEvent(with: .keyDown, location: .zero,
                modifierFlags: [], timestamp: 0, windowNumber: 0, context: nil,
                characters: "", charactersIgnoringModifiers: "", isARepeat: false, keyCode: key))
            grip.keyDown(with: event)
        }
        XCTAssertEqual(requests, [520, 480, 520, 480])
    }

    // Test-Oracle: the production grip drives the actual popover size and durable preference.
    @MainActor
    func testProductionGripChangesPopoverSizeAndSavedPreference() throws {
        _ = NSApplication.shared
        let name = "resize-wiring-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        let ports = ResizeTestPorts()
        let state = AppState(speech: ports, documentEnqueuer: ports,
                             currentSelectionEnqueuer: ports, clipboardEnqueuer: ports,
                             defaults: defaults)
        defer { state.stopPolling() }
        let popover = NSPopover()
        let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        defer { NSStatusBar.system.removeStatusItem(statusItem) }
        let controller = StatusController(state: state, defaults: defaults,
                                          popover: popover, statusItem: statusItem)
        let content = try XCTUnwrap(popover.contentViewController?.view)
        let window = NSWindow(contentRect: NSRect(x: 100, y: 300, width: 368, height: 500),
                              styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = content
        window.orderFront(nil)
        content.layoutSubtreeIfNeeded()
        window.displayIfNeeded()
        defer { window.close() }
        func descendants(_ view: NSView) -> [NSView] {
            view.subviews + view.subviews.flatMap { descendants($0) }
        }
        let grip = try XCTUnwrap(descendants(content).compactMap { $0 as? PopoverResizeGrip }.first,
                                "Production popover must contain the resize grip")
        func event(_ type: NSEvent.EventType, _ y: CGFloat) throws -> NSEvent {
            try XCTUnwrap(NSEvent.mouseEvent(with: type, location: NSPoint(x: 150, y: y),
                modifierFlags: [], timestamp: 0, windowNumber: window.windowNumber,
                context: nil, eventNumber: 1, clickCount: 1, pressure: 1))
        }
        grip.mouseDown(with: try event(.leftMouseDown, 10))
        grip.mouseDragged(with: try event(.leftMouseDragged, -70))
        XCTAssertEqual(popover.contentSize, NSSize(width: 368, height: 580))
        XCTAssertEqual(defaults.double(forKey: "menuCardHeight"), 580)
        withExtendedLifetime(controller) {}
    }

}

private struct ResizeTestPorts: SpeechServicePort, DocumentEnqueueing,
    CurrentSelectionEnqueueing, ClipboardEnqueueing {
    func snapshot() throws -> Snapshot { throw SpeechServiceError.unavailable }
    func submit(_ submission: SpeechSubmission) throws { throw SpeechServiceError.unavailable }
    func perform(_ command: SpeechCommand) throws { throw SpeechServiceError.unavailable }
    func purgeCachedAudio() throws -> CachePurgeReceipt { throw SpeechServiceError.unavailable }
    func subscribe(shouldContinue: () -> Bool, onChange: () -> Void) throws {
        throw SpeechServiceError.unavailable
    }
    func enqueueDocument(at url: URL) throws { throw SpeechServiceError.unavailable }
    func enqueueCurrentSelection(from processIdentifier: Int32?) throws {
        throw SpeechServiceError.unavailable
    }
    func enqueueClipboard() throws { throw SpeechServiceError.unavailable }
}
