// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium
// Test-Oracle: playback card width bound and linear progress computation

import AppKit
import SwiftUI
import XCTest

import AITTSApplication
@testable import AITTSMacAdapters
@testable import AITTSMenuBar

private struct PlaybackLayoutTestPorts: SpeechServicePort, DocumentEnqueueing,
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

@MainActor
final class PlaybackCardLayoutTests: XCTestCase {
    private var state: AppState!
    private var suiteName: String!
    private var defaults: UserDefaults!

    deinit {}

    override func setUp() {
        super.setUp()
        executionTimeAllowance = 15
        suiteName = "ai-tts-layout-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suiteName)!
        let ports = PlaybackLayoutTestPorts()
        state = AppState(
            speech: ports,
            documentEnqueuer: ports,
            currentSelectionEnqueuer: ports,
            clipboardEnqueuer: ports,
            defaults: defaults
        )
    }

    override func tearDown() {
        state.stopPolling()
        defaults.removePersistentDomain(forName: suiteName)
        state = nil
        defaults = nil
        super.tearDown()
    }

    func testLinearProgressUsesZeroBasedIndexAgainstSegmentCount() {
        let firstSegment = ActiveSegment(index: 0, number: 1, count: 50, text: "Intro", state: "Playing", durationMs: 1000, positionMs: 0)
        let (val0, tot0) = CurrentPlaybackCard.linearProgress(active: firstSegment, segmentCount: 50)
        XCTAssertEqual(val0, 0.0)
        XCTAssertEqual(tot0, 50.0)

        let midSegment = ActiveSegment(index: 10, number: 11, count: 50, text: "Middle", state: "Playing", durationMs: 1000, positionMs: 0)
        let (val10, tot10) = CurrentPlaybackCard.linearProgress(active: midSegment, segmentCount: 50)
        XCTAssertEqual(val10, 10.0)
        XCTAssertEqual(tot10, 50.0)

        let lastSegment = ActiveSegment(index: 49, number: 50, count: 50, text: "Outro", state: "Playing", durationMs: 1000, positionMs: 0)
        let (val49, tot49) = CurrentPlaybackCard.linearProgress(active: lastSegment, segmentCount: 50)
        XCTAssertEqual(val49, 49.0)
        XCTAssertEqual(tot49, 50.0)
    }

    func testPlaybackCardWithManyChunksFitsWithinStandardPopoverWidth() throws {
        let snapshot = try XCTUnwrap(Snapshot(daemonJSON: [
            "status": [
                "playback_state": "playing",
                "current": [
                    "id": "utt-long",
                    "text": "Extensive reading with many chunks",
                    "voice": "af_alloy",
                    "state": "Playing",
                    "segment_count": 100,
                    "active_segment": [
                        "index": 42,
                        "number": 43,
                        "count": 100,
                        "text": "Chunk forty-two",
                        "position_ms": 1000,
                        "duration_ms": 3000,
                    ],
                ],
            ]
        ]))
        state.applySnapshot(snapshot)

        let card = CurrentPlaybackCard().environmentObject(state)
        let hostingView = NSHostingView(rootView: card)
        hostingView.layoutSubtreeIfNeeded()
        let fittingWidth = hostingView.fittingSize.width

        // Standard popover width is 368pt; card must fit inside without horizontal blowout
        XCTAssertLessThanOrEqual(fittingWidth, 368.0)
    }
}
