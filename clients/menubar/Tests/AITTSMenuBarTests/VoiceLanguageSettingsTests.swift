// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned preferences and serialized speech-service fake)
// Test-Oracle: language selection reflects each click immediately and never sends an empty pool

import AITTSApplication
import AppKit
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
    var marker: XCTestExpectation?
    func commands() -> [SpeechCommand] { lock.withLock { recorded } }
    func snapshot() throws -> Snapshot { throw SpeechServiceError.unavailable }
    func submit(_ submission: SpeechSubmission) throws { throw SpeechServiceError.unavailable }
    func perform(_ command: SpeechCommand) throws {
        lock.withLock { recorded.append(command) }
        if command == .setEarconEnabled(true) { marker?.fulfill() }
    }
    func purgeCachedAudio() throws -> CachePurgeReceipt { throw SpeechServiceError.unavailable }
    func subscribe(shouldContinue: () -> Bool, onChange: () -> Void) throws {}
    func enqueueDocument(at url: URL) throws { throw SpeechServiceError.unavailable }
    func enqueueCurrentSelection(from processIdentifier: Int32?) throws { throw SpeechServiceError.unavailable }
    func enqueueClipboard() throws { throw SpeechServiceError.unavailable }
}
