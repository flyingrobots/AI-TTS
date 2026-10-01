// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned native status item and isolated preferences)
// Test-Oracle: a newly launched app remains visible when the daemon is unavailable

import AITTSApplication
import AppKit
import XCTest
@testable import AITTSMenuBar

final class StatusItemTests: XCTestCase {
    override func setUp() { super.setUp(); executionTimeAllowance = 15 }

    // Retire only with an equivalent native startup discoverability contract.
    @MainActor
    func testUnavailableDaemonStillRendersInitialStatusItem() throws {
        try withStatusItem { item in
            XCTAssertNotNil(item.button?.image,
                            "The unavailable state must render before any daemon update")
        }
    }

    // Test-Oracle: the native tray control exposes app identity and current status.
    // Retire only with an equivalent native accessibility discoverability contract.
    @MainActor
    func testStatusItemHasAnAccessibleNameAndState() throws {
        let cases: [(String?, String)] = [
            (nil, "AI-TTS: Needs attention"),
            ("idle", "AI-TTS: Ready"),
            ("playing", "AI-TTS: Speaking"),
            ("paused", "AI-TTS: Playback paused"),
            ("synthesizing", "AI-TTS: Preparing speech"),
        ]
        for (playbackState, label) in cases {
            try withStatusItem(playbackState: playbackState) { item in
                XCTAssertEqual(item.button?.accessibilityLabel(), label)
            }
        }
    }

    @MainActor
    private func withStatusItem(playbackState: String? = nil,
                                body: (NSStatusItem) throws -> Void) throws {
        _ = NSApplication.shared
        let name = "status-item-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        let ports = UnavailableStatusPorts()
        let state = AppState(speech: ports, documentEnqueuer: ports,
                             currentSelectionEnqueuer: ports, clipboardEnqueuer: ports,
                             defaults: defaults)
        defer { state.stopPolling() }
        if let playbackState {
            state.reachable = true
            state.status = DaemonStatus(playbackState: playbackState, current: nil,
                                        counts: [:], voice: "v", engine: "fake")
        }
        let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        defer { NSStatusBar.system.removeStatusItem(statusItem) }
        let controller = StatusController(state: state, defaults: defaults,
                                          statusItem: statusItem,
                                          applicationNotifications: NotificationCenter())
        try body(statusItem)
        withExtendedLifetime(controller) {}
    }
}

private struct UnavailableStatusPorts: SpeechServicePort, DocumentEnqueueing,
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
