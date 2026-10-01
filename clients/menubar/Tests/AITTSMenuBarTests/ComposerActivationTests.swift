// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned notification center/defaults, no Accessibility or workspace subscription)
// Test-Oracle: Import Selection targets the latest external activation; unknown targets clear and retired observers stop

import AITTSApplication
import AppKit
import XCTest
@testable import AITTSMenuBar

final class ComposerActivationTests: XCTestCase {
    override func setUp() { super.setUp(); executionTimeAllowance = 15 }

    @MainActor
    private func makeState() throws -> AppState {
        _ = NSApplication.shared
        let name = "composer-activation-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        addTeardownBlock { defaults.removePersistentDomain(forName: name) }
        let ports = ActivationTestPorts()
        return AppState(speech: ports, documentEnqueuer: ports,
                        currentSelectionEnqueuer: ports, clipboardEnqueuer: ports,
                        defaults: defaults)
    }

    @MainActor
    func testExternalActivationReplacesTheSelectionTargetUntilObserverRetires() throws {
        let state = try makeState()
        let notifications = NotificationCenter()
        state.capturePriorApplication(processIdentifier: 42)
        var controller: SpeechSelectionTracker? = SpeechSelectionTracker(
            state: state, applicationNotifications: notifications, ownProcessIdentifier: -1)
        // This owned test process stands for an external app; the controller's own PID is injected.
        notifications.post(name: NSWorkspace.didActivateApplicationNotification, object: nil,
                           userInfo: [NSWorkspace.applicationUserInfoKey: NSRunningApplication.current])
        XCTAssertEqual(state.composer.priorApplication, ProcessInfo.processInfo.processIdentifier)
        notifications.post(name: NSWorkspace.didActivateApplicationNotification, object: nil)
        XCTAssertNil(state.composer.priorApplication)
        withExtendedLifetime(controller) {}
        controller = nil
        state.capturePriorApplication(processIdentifier: 303)
        notifications.post(name: NSWorkspace.didActivateApplicationNotification, object: nil,
                           userInfo: [NSWorkspace.applicationUserInfoKey: NSRunningApplication.current])
        XCTAssertEqual(state.composer.priorApplication, 303)
    }

    @MainActor
    func testOwnActivationKeepsTheExternalTargetButUnknownCaptureClearsIt() throws {
        let state = try makeState()
        let notifications = NotificationCenter()
        let controller = SpeechSelectionTracker(
            state: state, applicationNotifications: notifications)
        state.capturePriorApplication(processIdentifier: 42)
        notifications.post(name: NSWorkspace.didActivateApplicationNotification, object: nil,
                           userInfo: [NSWorkspace.applicationUserInfoKey: NSRunningApplication.current])
        XCTAssertEqual(state.composer.priorApplication, 42)
        state.capturePriorApplication(processIdentifier: nil)
        XCTAssertNil(state.composer.priorApplication)
        withExtendedLifetime(controller) {}
    }
}

private struct ActivationTestPorts: SpeechServicePort, DocumentEnqueueing,
    CurrentSelectionEnqueueing, ClipboardEnqueueing {
    func snapshot() throws -> Snapshot { throw SpeechServiceError.unavailable }
    func submit(_ submission: SpeechSubmission) throws { throw SpeechServiceError.unavailable }
    func perform(_ command: SpeechCommand) throws { throw SpeechServiceError.unavailable }
    func purgeCachedAudio() throws -> CachePurgeReceipt { throw SpeechServiceError.unavailable }
    func subscribe(shouldContinue: () -> Bool, onChange: () -> Void) throws {}
    func enqueueDocument(at url: URL) throws { throw SpeechServiceError.unavailable }
    func enqueueCurrentSelection(from processIdentifier: Int32?) throws {
        throw SpeechServiceError.unavailable
    }
    func enqueueClipboard() throws { throw SpeechServiceError.unavailable }
}
