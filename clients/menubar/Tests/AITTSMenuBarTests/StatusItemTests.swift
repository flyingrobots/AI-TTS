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
        _ = NSApplication.shared
        let name = "status-item-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        let ports = UnavailableStatusPorts()
        let state = AppState(speech: ports, documentEnqueuer: ports,
                             currentSelectionEnqueuer: ports, clipboardEnqueuer: ports,
                             defaults: defaults)
        defer { state.stopPolling() }
        let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        defer { NSStatusBar.system.removeStatusItem(statusItem) }
        let controller = StatusController(state: state, defaults: defaults,
                                          statusItem: statusItem,
                                          applicationNotifications: NotificationCenter())
        XCTAssertNotNil(statusItem.button?.image,
                        "The unavailable state must render before any daemon update")
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
