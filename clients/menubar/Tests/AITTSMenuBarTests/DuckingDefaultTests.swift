// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned app state and isolated preferences, no daemon or audio)
// Test-Oracle: James's 2026-10-02 decision that other-app ducking is opt-in and off by default, while a saved opt-in is honored

import AITTSApplication
import XCTest
@testable import AITTSMenuBar

final class DuckingDefaultTests: XCTestCase {
    override func setUp() { super.setUp(); executionTimeAllowance = 15 }

    func testSnapshotWithoutADuckingPreferenceIsOff() {
        let snapshot = Snapshot(status: DaemonStatus(playbackState: "idle", current: nil,
                                                     counts: [:], voice: "v", engine: "fake"),
                                plan: [], input: [], history: [], voices: ["v"],
                                speed: 1, playbackRate: 1)
        XCTAssertFalse(snapshot.duckingEnabled)
    }

    @MainActor
    func testAppStateStartsOffAndHonorsASavedOptIn() throws {
        let suite = "ducking-default-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let ports = UnavailableDuckingPorts()
        let state = AppState(speech: ports, documentEnqueuer: ports,
                             currentSelectionEnqueuer: ports, clipboardEnqueuer: ports,
                             defaults: defaults)
        defer { state.stopPolling() }
        XCTAssertFalse(state.duckingEnabled)
        state.applySnapshot(Snapshot(status: DaemonStatus(playbackState: "idle", current: nil,
                                                          counts: [:], voice: "v", engine: "fake"),
                                     plan: [], input: [], history: [], voices: ["v"],
                                     speed: 1, playbackRate: 1, duckingEnabled: true))
        XCTAssertTrue(state.duckingEnabled)
    }
}

private struct UnavailableDuckingPorts: SpeechServicePort, DocumentEnqueueing,
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
