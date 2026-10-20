// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned preferences and serialized speech-service fake)
// Test-Oracle: language selection reflects each click immediately and never sends an empty pool

import AITTSApplication
import AppKit
import Combine
import XCTest
@testable import AITTSMenuBar

final class VoiceLanguageSettingsTests: XCTestCase {
    override func setUp() { super.setUp(); executionTimeAllowance = 15 }

    @MainActor
    private func makeState(_ ports: LanguageSettingsPorts) throws -> AppState {
        _ = NSApplication.shared
        let name = "voice-language-settings-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        addTeardownBlock { defaults.removePersistentDomain(forName: name) }
        return AppState(speech: ports, documentEnqueuer: ports,
                        currentSelectionEnqueuer: ports, clipboardEnqueuer: ports,
                        defaults: defaults)
    }

    @MainActor
    func testRapidSelectionsAccumulateBeforeAcknowledgement() throws {
        let ports = LanguageSettingsPorts()
        let state = try makeState(ports)
        state.setVoiceLanguages(["en", "es"])
        XCTAssertEqual(state.voiceLanguages, ["en", "es"])
        state.setVoiceLanguages((Set(state.voiceLanguages).union(["fr"])).sorted())
        XCTAssertEqual(state.voiceLanguages, ["en", "es", "fr"])
    }

    @MainActor
    func testSnapshotRequestedBeforeSelectionDoesNotRevertIt() async throws {
        let ports = LanguageSettingsPorts()
        ports.holdFirstSnapshot = true
        let performStarted = expectation(description: "language change reached the port")
        ports.performStarted = performStarted
        // Unblock the fake's transport on every exit path so the queued work cannot outlive the test.
        addTeardownBlock { ports.releaseFirstSnapshot(); ports.releasePerform() }
        let state = try makeState(ports)
        let staleApplied = expectation(description: "the stale snapshot was applied")
        let observation = state.$reachable.first(where: { $0 }).sink { _ in staleApplied.fulfill() }
        defer { observation.cancel() }
        state.refresh()
        state.setVoiceLanguages(["en", "fr"])
        ports.releaseFirstSnapshot()
        await fulfillment(of: [performStarted, staleApplied], timeout: 1)
        XCTAssertEqual(state.voiceLanguages, ["en", "fr"])
    }

    @MainActor
    func testEmptySelectionSendsNoInvalidSetting() async throws {
        let ports = LanguageSettingsPorts()
        let marker = expectation(description: "later command crossed the serialized port")
        ports.marker = marker
        let state = try makeState(ports)
        state.setVoiceLanguages([])
        state.setEarconEnabled(true)
        await fulfillment(of: [marker], timeout: 1)
        XCTAssertEqual(ports.commands(), [.setEarconEnabled(true)])
        XCTAssertEqual(state.voiceLanguages, ["en"])
    }
}

private final class LanguageSettingsPorts: SpeechServicePort, DocumentEnqueueing,
    CurrentSelectionEnqueueing, ClipboardEnqueueing, @unchecked Sendable {
    private let lock = NSLock()
    private var recorded: [SpeechCommand] = []
    private var daemonLanguages = ["en"]
    private let firstSnapshotGate = DispatchSemaphore(value: 0)
    private let performGate = DispatchSemaphore(value: 0)
    private var snapshotCount = 0
    var marker: XCTestExpectation?
    var holdFirstSnapshot = false
    var performStarted: XCTestExpectation?
    func commands() -> [SpeechCommand] { lock.withLock { recorded } }
    func releaseFirstSnapshot() { firstSnapshotGate.signal() }
    func releasePerform() { performGate.signal() }
    func snapshot() throws -> Snapshot {
        guard holdFirstSnapshot else { throw SpeechServiceError.unavailable }
        let first = lock.withLock { snapshotCount += 1; return snapshotCount == 1 }
        if first { firstSnapshotGate.wait() }
        let languages = lock.withLock { daemonLanguages }
        return Snapshot(status: DaemonStatus(playbackState: "idle", current: nil, counts: [:],
                                             voice: "v", engine: "fake"),
                        plan: [], input: [], history: [], voices: ["v"], speed: 1,
                        playbackRate: 1, voiceLanguages: languages)
    }
    func submit(_ submission: SpeechSubmission) throws { throw SpeechServiceError.unavailable }
    func perform(_ command: SpeechCommand) throws {
        lock.withLock { recorded.append(command) }
        if command == .setEarconEnabled(true) { marker?.fulfill() }
        if case let .setVoiceLanguages(languages) = command, holdFirstSnapshot {
            performStarted?.fulfill()
            performGate.wait()
            lock.withLock { daemonLanguages = languages }
        }
    }
    func purgeCachedAudio() throws -> CachePurgeReceipt { throw SpeechServiceError.unavailable }
    func subscribe(shouldContinue: () -> Bool, onChange: () -> Void) throws {}
    func enqueueDocument(at url: URL) throws { throw SpeechServiceError.unavailable }
    func enqueueCurrentSelection(from processIdentifier: Int32?) throws { throw SpeechServiceError.unavailable }
    func enqueueClipboard() throws { throw SpeechServiceError.unavailable }
}
