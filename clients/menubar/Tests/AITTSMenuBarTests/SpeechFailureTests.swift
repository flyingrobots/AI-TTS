// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (typed snapshot projection on the main actor; no real daemon)
// Test-Oracle: a newly failed clip becomes a visible error once; old history does not alert

import AITTSApplication
import Foundation
import XCTest
@testable import AITTSMacAdapters
@testable import AITTSMenuBar

final class SpeechFailureTests: XCTestCase {
    override func setUp() {
        super.setUp()
        executionTimeAllowance = 15
    }

    @MainActor
    func testNewFailureIsSurfacedOnceWithoutReannouncingOldHistory() throws {
        let old = try XCTUnwrap(Utterance(daemonJSON: [
            "id": "old", "text": "private old text", "voice": "v", "state": "Failed",
            "error": "old failure"
        ]))
        let failed = try XCTUnwrap(Utterance(daemonJSON: [
            "id": "new", "text": "private new text", "voice": "v", "state": "Failed",
            "error": "segment failed: phonemizer mismatch"
        ]))
        let port = FailureSnapshots(histories: [[old], [failed, old], [failed, old]])
        let suite = "ai-tts-failure-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let state = AppState(speech: port, documentEnqueuer: port,
                             currentSelectionEnqueuer: port, clipboardEnqueuer: port,
                             defaults: defaults)
        let expected: [String?] = [nil, "Speech failed: segment failed: phonemizer mismatch", nil]
        let expectedNotices: [SpeechFailureNotice?] = [
            nil, SpeechFailureNotice(id: "new", detail: "segment failed: phonemizer mismatch"), nil
        ]
        for (index, message) in expected.enumerated() {
            if index == 2 { state.dismissError() }
            state.applySnapshot(try port.snapshot())
            XCTAssertEqual(state.lastError, message)
            XCTAssertEqual(state.failureNotice, expectedNotices[index])
        }
        state.dismissError()
        XCTAssertNil(state.failureNotice)
        XCTAssertNil(state.lastError)
    }

    // Test-Oracle: the toast's History action leaves History rendered, not hidden by the composer.
    // Retire only when History and the inline composer stop sharing the popover body.
    @MainActor
    func testRevealingHistoryCollapsesTheInlineComposerAndKeepsTheDraft() throws {
        let port = FailureSnapshots(histories: [])
        let suite = "ai-tts-reveal-history-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let state = AppState(speech: port, documentEnqueuer: port,
                             currentSelectionEnqueuer: port, clipboardEnqueuer: port,
                             defaults: defaults)
        state.selectedTab = .queue
        state.showingComposer = true
        state.composer.draft.text = "unsent draft"
        state.revealHistory()
        XCTAssertEqual(state.selectedTab, .history)
        XCTAssertFalse(state.showingComposer, "History is not rendered while the composer is open")
        XCTAssertEqual(state.composer.draft.text, "unsent draft")
    }
}

private final class FailureSnapshots: SpeechServicePort, DocumentEnqueueing,
    CurrentSelectionEnqueueing, ClipboardEnqueueing, @unchecked Sendable {
    private let lock = NSLock()
    private var histories: [[Utterance]]
    init(histories: [[Utterance]]) { self.histories = histories }
    func snapshot() throws -> Snapshot {
        lock.lock()
        defer { lock.unlock() }
        return Snapshot(status: DaemonStatus(playbackState: "idle", current: nil,
                                             counts: [:], voice: "v", engine: "fake"),
                        plan: [], input: [], history: histories.removeFirst(), voices: ["v"],
                        speed: 1, playbackRate: 1, captionsEnabledConfigured: true)
    }
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
