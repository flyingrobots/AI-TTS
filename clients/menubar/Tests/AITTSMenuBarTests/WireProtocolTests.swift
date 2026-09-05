// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (AppKit rendering and main-actor state)
// Test-Oracle: daemon wire contract and approved menu-bar interaction design

import Combine
import XCTest

import AITTSApplication
@testable import AITTSMacAdapters
@testable import AITTSMenuBar

final class WireProtocolTests: XCTestCase {
    override func setUp() {
        super.setUp()
        executionTimeAllowance = 15
    }

    func testOnlyOneMenuBarInstanceCanHoldLock() throws {
        let lockURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("ai-tts-single-instance-\(UUID().uuidString).lock")
        defer { try? FileManager.default.removeItem(at: lockURL) }

        var first: SingleInstanceLock? = try XCTUnwrap(SingleInstanceLock(url: lockURL))
        withExtendedLifetime(first) {
            XCTAssertNil(SingleInstanceLock(url: lockURL))
        }
        first = nil
        XCTAssertNotNil(SingleInstanceLock(url: lockURL))
    }

    func testEncodeAppendsNewline() throws {
        let data = try WireProtocol.encode(["op": "status"])
        XCTAssertEqual(data.last, 0x0A)
        let object =
            try JSONSerialization.jsonObject(with: data.dropLast()) as? [String: Any]
        XCTAssertEqual(object?["op"] as? String, "status")
    }

    func testParseOkResponse() throws {
        let line = Data(#"{"ok": true, "state": "idle"}"#.utf8)
        let json = try WireProtocol.parseResponse(line)
        XCTAssertEqual(json["state"] as? String, "idle")
    }

    func testParseErrorResponseThrowsTyped() {
        let line = Data(
            #"{"ok": false, "error": {"type": "bad_request", "message": "no"}}"#.utf8)
        XCTAssertThrowsError(try WireProtocol.parseResponse(line)) { error in
            XCTAssertEqual(
                error as? WireError, .daemon(type: "bad_request", message: "no"))
        }
    }

    func testParseGarbageThrowsMalformed() {
        XCTAssertThrowsError(try WireProtocol.parseResponse(Data("junk".utf8))) { error in
            XCTAssertEqual(error as? WireError, .malformed)
        }
    }

    func testUtteranceParsesWireShape() {
        let utterance = Utterance(daemonJSON: [
            "id": "utt_1", "text": "hello", "voice": "bm_daniel", "state": "Ready",
            "duration_ms": 1200, "position_ms": 300, "finished_at": 1_756_700_000.5,
            "source": "menubar", "priority": "urgent", "segment_count": 3,
            "completed_segments": 1,
            "active_segment": [
                "index": 1, "number": 2, "count": 3, "text": "Clean spoken text.",
                "state": "Playing", "duration_ms": 500, "position_ms": 125,
            ],
        ])
        XCTAssertEqual(utterance?.id, "utt_1")
        XCTAssertEqual(utterance?.durationMs, 1200)
        XCTAssertEqual(utterance?.positionMs, 300)
        XCTAssertEqual(utterance?.finishedAt, 1_756_700_000.5)
        XCTAssertEqual(utterance?.source, "menubar")
        XCTAssertEqual(utterance?.priority, .urgent)
        XCTAssertEqual(utterance?.segmentCount, 3)
        XCTAssertEqual(utterance?.completedSegments, 1)
        XCTAssertEqual(
            utterance?.activeSegment,
            ActiveSegment(
                index: 1, number: 2, count: 3, text: "Clean spoken text.",
                state: "Playing", durationMs: 500, positionMs: 125))
        XCTAssertNil(Utterance(daemonJSON: ["id": "utt_2"]))
    }

    func testSnapshotParsesWireShape() {
        let snapshot = Snapshot(daemonJSON: [
            "status": [
                "state": "accepting",
                "playback_state": "playing",
                "accepting_speech": true,
                "current": [
                    "id": "utt_1", "text": "hi", "voice": "v", "state": "Playing",
                    "position_ms": 42,
                ],
                "counts": ["Queued": 2],
                "voice": "bm_daniel",
                "engine": "kokoro",
            ],
            "plan": [
                ["id": "utt_1", "text": "hi", "voice": "v", "state": "Playing"],
                ["id": "utt_2", "text": "next", "voice": "v", "state": "Queued"],
            ],
            "input": [["id": "utt_2", "text": "next", "voice": "v", "state": "Queued"]],
            "history": [],
            "voices": ["bm_daniel"],
            "settings": [
                "voice": "bm_daniel", "speed": 1.25, "playback_rate": 1.5,
                "captions_enabled": true,
            ],
        ])
        XCTAssertEqual(snapshot?.status.playbackState, "playing")
        XCTAssertEqual(snapshot?.status.current?.positionMs, 42)
        XCTAssertEqual(snapshot?.plan.count, 2)
        XCTAssertEqual(snapshot?.plan.last?.state, "Queued")
        XCTAssertEqual(snapshot?.speed, 1.25)
        XCTAssertEqual(snapshot?.playbackRate, 1.5)
        XCTAssertEqual(snapshot?.captionsEnabled, true)
        XCTAssertEqual(snapshot?.status.engine, "kokoro")
    }

    func testPlaybackRateChoicesMatchTransportContract() {
        XCTAssertEqual(PlaybackRate.allCases.map(\.rawValue), [0.5, 0.75, 1, 1.5, 2, 3])
        XCTAssertEqual(PlaybackRate.allCases.map(\.label), ["0.5×", "0.75×", "1×", "1.5×", "2×", "3×"])
    }

    func testCaptionPresentationIsOptInAndRequiresAnActiveSegment() throws {
        let active = try XCTUnwrap(DaemonStatus(daemonJSON: [
            "playback_state": "playing",
            "current": [
                "id": "utt_1", "text": "source", "voice": "v", "state": "Playing",
                "active_segment": [
                    "index": 0, "number": 1, "count": 2, "text": "spoken",
                    "state": "Playing",
                ],
            ],
        ]))
        let idle = try XCTUnwrap(DaemonStatus(daemonJSON: ["playback_state": "idle"]))

        XCTAssertTrue(
            CaptionPresentation.shouldShow(enabled: true, reachable: true, status: active))
        XCTAssertFalse(
            CaptionPresentation.shouldShow(enabled: false, reachable: true, status: active))
        XCTAssertFalse(
            CaptionPresentation.shouldShow(enabled: true, reachable: false, status: active))
        XCTAssertFalse(
            CaptionPresentation.shouldShow(enabled: true, reachable: true, status: idle))
    }

    @MainActor
    func testCaptionPreferenceFollowsDaemonAndPushesChangesWithoutChangingWatchdog() async throws {
        let suite = "ai-tts-caption-preference-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defaults.removePersistentDomain(forName: suite)
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set(false, forKey: "captionsEnabled")
        let speech = RecordingCaptionSpeechPort(
            captionsEnabled: true,
            captionsEnabledConfigured: true
        )
        let ports = InertApplicationPorts()
        let state = AppState(
            speech: speech,
            documentEnqueuer: ports,
            currentSelectionEnqueuer: ports,
            clipboardEnqueuer: ports,
            defaults: defaults
        )
        defer { state.stopPolling() }

        XCTAssertFalse(state.captionsEnabled)
        XCTAssertEqual(state.backgroundPollingInterval, 5.0)
        let daemonPreferenceApplied = expectation(description: "daemon preference applied")
        let observation = state.$captionsEnabled.dropFirst().sink { enabled in
            if enabled { daemonPreferenceApplied.fulfill() }
        }

        state.refresh()
        await fulfillment(of: [daemonPreferenceApplied], timeout: 1)
        XCTAssertTrue(state.captionsEnabled)
        XCTAssertTrue(defaults.bool(forKey: "captionsEnabled"))
        XCTAssertEqual(state.backgroundPollingInterval, 5.0)

        state.setCaptionsEnabled(false)
        await fulfillment(of: [speech.commandPerformed], timeout: 1)
        XCTAssertFalse(state.captionsEnabled)
        XCTAssertFalse(defaults.bool(forKey: "captionsEnabled"))
        XCTAssertEqual(speech.commands, [.setCaptionsEnabled(false)])
        XCTAssertEqual(state.backgroundPollingInterval, 5.0)
        withExtendedLifetime(observation) {}
    }

    @MainActor
    func testLegacyCaptionPreferenceMigratesWhenDaemonHasNoValue() async throws {
        let suite = "ai-tts-caption-migration-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defaults.removePersistentDomain(forName: suite)
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set(true, forKey: "captionsEnabled")
        let speech = RecordingCaptionSpeechPort(
            captionsEnabled: false,
            captionsEnabledConfigured: false
        )
        let ports = InertApplicationPorts()
        let state = AppState(
            speech: speech,
            documentEnqueuer: ports,
            currentSelectionEnqueuer: ports,
            clipboardEnqueuer: ports,
            defaults: defaults
        )

        state.refresh()
        await fulfillment(of: [speech.commandPerformed], timeout: 1)

        XCTAssertTrue(state.captionsEnabled)
        XCTAssertEqual(speech.commands, [.setCaptionsEnabled(true)])
    }

    @MainActor
    func testMenuBarCachePurgePublishesTheTypedReceipt() async throws {
        let suite = "ai-tts-cache-purge-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let speech = RecordingCaptionSpeechPort(
            captionsEnabled: false,
            captionsEnabledConfigured: true
        )
        let ports = InertApplicationPorts()
        let state = AppState(
            speech: speech,
            documentEnqueuer: ports,
            currentSelectionEnqueuer: ports,
            clipboardEnqueuer: ports,
            defaults: defaults
        )
        let receiptPublished = expectation(description: "cache purge receipt published")
        let observation = state.$cachePurgeReceipt.dropFirst().sink { receipt in
            if receipt != nil { receiptPublished.fulfill() }
        }

        state.purgeCachedAudio()
        await fulfillment(of: [receiptPublished], timeout: 1)

        XCTAssertEqual(state.cachePurgeReceipt, speech.cachePurgeReceipt)
        XCTAssertFalse(state.purgingCachedAudio)
        withExtendedLifetime(observation) {}
    }

    func testDaemonStatusFallsBackToLegacyState() {
        let status = DaemonStatus(daemonJSON: ["state": "paused"])
        XCTAssertEqual(status?.playbackState, "paused")
    }

    func testPopoverStoresExternalApplicationBeforeActivation() {
        var events: [String] = []
        var storedProcessIdentifier: Int32?

        PopoverOpenSequence.capturePriorApplicationThenActivate(
            frontmostProcessIdentifier: {
                events.append("observed")
                return 4_242
            },
            ownProcessIdentifier: 7_777,
            store: {
                storedProcessIdentifier = $0
                events.append("stored")
            },
            activate: { events.append("activated") }
        )

        XCTAssertEqual(storedProcessIdentifier, 4_242)
        XCTAssertEqual(events, ["observed", "stored", "activated"])
    }

    func testPopoverDoesNotTreatItselfAsPriorApplication() {
        var storedProcessIdentifier: Int32? = 1

        PopoverOpenSequence.capturePriorApplicationThenActivate(
            frontmostProcessIdentifier: { 7_777 },
            ownProcessIdentifier: 7_777,
            store: { storedProcessIdentifier = $0 },
            activate: {}
        )

        XCTAssertNil(storedProcessIdentifier)
    }

    @MainActor
    func testMenuBarSelectionActionUsesCapturedApplication() async {
        let selection = RecordingCurrentSelectionEnqueuer()
        let clipboard = RecordingClipboardEnqueuer()
        let ports = InertApplicationPorts()
        let state = AppState(
            speech: ports,
            documentEnqueuer: ports,
            currentSelectionEnqueuer: selection,
            clipboardEnqueuer: clipboard,
            defaults: .standard
        )

        state.capturePriorApplication(processIdentifier: 4_242)
        state.enqueueCurrentSelection()

        await fulfillment(of: [selection.called], timeout: 1)
        XCTAssertEqual(selection.processIdentifier, 4_242)
        XCTAssertEqual(clipboard.callCount, 0)
    }

    @MainActor
    func testMenuBarClipboardActionCallsOnlyClipboardPort() async {
        let selection = RecordingCurrentSelectionEnqueuer()
        let clipboard = RecordingClipboardEnqueuer()
        let ports = InertApplicationPorts()
        let state = AppState(
            speech: ports,
            documentEnqueuer: ports,
            currentSelectionEnqueuer: selection,
            clipboardEnqueuer: clipboard,
            defaults: .standard
        )

        state.enqueueClipboard()

        await fulfillment(of: [clipboard.called], timeout: 1)
        XCTAssertEqual(clipboard.callCount, 1)
        XCTAssertNil(selection.processIdentifier)
    }

    @MainActor
    func testUnifiedQueueContainsEveryUpcomingStateExactlyOnce() throws {
        let current = try XCTUnwrap(Utterance(daemonJSON: [
            "id": "utt_current", "text": "Speaking", "voice": "bm_daniel",
            "state": "Playing", "priority": "normal",
        ]))
        let preview = try XCTUnwrap(Utterance(daemonJSON: [
            "id": "utt_preview",
            "text": "Hello. This is the voice bm daniel.",
            "voice": "bm_daniel",
            "state": "Ready",
            "source": "menubar-preview",
            "priority": "urgent",
        ]))
        let synthesizing = try XCTUnwrap(Utterance(daemonJSON: [
            "id": "utt_synth", "text": "Generating", "voice": "bm_daniel",
            "state": "Synthesizing", "priority": "normal",
        ]))
        let queued = try XCTUnwrap(Utterance(daemonJSON: [
            "id": "utt_queued", "text": "Waiting", "voice": "bm_daniel",
            "state": "Queued", "priority": "normal",
        ]))
        let ports = InertApplicationPorts()
        let state = AppState(
            speech: ports,
            documentEnqueuer: ports,
            currentSelectionEnqueuer: ports,
            clipboardEnqueuer: ports,
            defaults: .standard
        )
        state.plan = [current, preview, synthesizing, queued]

        XCTAssertEqual(state.upcoming, [preview, synthesizing, queued])
        XCTAssertEqual(Set(state.upcoming.map(\.id)).count, state.upcoming.count)
        XCTAssertEqual(preview.priority, .urgent)
        XCTAssertEqual(PlaybackTab.allCases.map(\.rawValue), ["Queue", "History"])
        XCTAssertEqual(RequeuePriority.normal.actionDescription, "Add to end of Queue")
        XCTAssertEqual(RequeuePriority.urgent.actionDescription, "Play next after current")
    }

    func testTrayStatePrecedence() {
        XCTAssertEqual(TrayState.from(reachable: false, daemonState: "playing"), .error)
        XCTAssertEqual(TrayState.from(reachable: true, daemonState: "playing"), .playing)
        XCTAssertEqual(TrayState.from(reachable: true, daemonState: "paused"), .paused)
        XCTAssertEqual(
            TrayState.from(reachable: true, daemonState: "synthesizing"), .synthesizing)
        XCTAssertEqual(TrayState.from(reachable: true, daemonState: "idle"), .idle)
        XCTAssertTrue(TrayState.playing.animates)
        XCTAssertTrue(TrayState.synthesizing.animates)
        XCTAssertFalse(TrayState.paused.animates)
        XCTAssertFalse(TrayState.idle.animates)
    }

    func testTrayIconFramesAreTemplateAndDistinct() throws {
        let idle = TrayIcon.frame(state: .idle)
        let playing = TrayIcon.frame(state: .playing)
        XCTAssertTrue(idle.isTemplate)
        XCTAssertTrue(playing.isTemplate)
        XCTAssertEqual(idle.size, TrayIcon.size)
        let idleData = try XCTUnwrap(idle.tiffRepresentation)
        let playingData = try XCTUnwrap(playing.tiffRepresentation)
        XCTAssertNotEqual(idleData, playingData)
        // Animation frames differ too: motion in the menu bar means work in flight.
        let frame0 = try XCTUnwrap(TrayIcon.frame(state: .playing, phase: 0).tiffRepresentation)
        let frame1 = try XCTUnwrap(TrayIcon.frame(state: .playing, phase: 1).tiffRepresentation)
        XCTAssertNotEqual(frame0, frame1)
    }
}

private struct InertApplicationPorts: SpeechServicePort, DocumentEnqueueing,
    CurrentSelectionEnqueueing, ClipboardEnqueueing, Sendable
{
    func snapshot() throws -> Snapshot { throw InertError.unexpectedCall }
    func submit(_ submission: SpeechSubmission) throws { throw InertError.unexpectedCall }
    func perform(_ command: SpeechCommand) throws { throw InertError.unexpectedCall }
    func purgeCachedAudio() throws -> CachePurgeReceipt { throw InertError.unexpectedCall }

    func subscribe(shouldContinue: () -> Bool, onChange: () -> Void) throws {
        throw InertError.unexpectedCall
    }

    func enqueueDocument(at url: URL) throws { throw InertError.unexpectedCall }
    func enqueueCurrentSelection(from processIdentifier: Int32?) throws {
        throw InertError.unexpectedCall
    }
    func enqueueClipboard() throws { throw InertError.unexpectedCall }
}

private final class RecordingCaptionSpeechPort: SpeechServicePort, @unchecked Sendable {
    let commandPerformed = XCTestExpectation(description: "caption command performed")
    private let snapshotValue: Snapshot
    private let lock = NSLock()
    private var recordedCommands: [SpeechCommand] = []
    let cachePurgeReceipt = CachePurgeReceipt(
        removedFiles: 2,
        removedBytes: 13,
        protectedFiles: 1,
        protectedBytes: 6,
        failedFiles: 0,
        failedBytes: 0
    )

    init(captionsEnabled: Bool, captionsEnabledConfigured: Bool) {
        snapshotValue = Snapshot(
            status: DaemonStatus(
                playbackState: "idle", current: nil, counts: [:], voice: "bm_george",
                engine: "fake"),
            plan: [],
            input: [],
            history: [],
            voices: ["bm_george"],
            speed: 1,
            playbackRate: 1,
            captionsEnabled: captionsEnabled,
            captionsEnabledConfigured: captionsEnabledConfigured
        )
    }

    var commands: [SpeechCommand] {
        lock.lock()
        defer { lock.unlock() }
        return recordedCommands
    }

    func snapshot() throws -> Snapshot { snapshotValue }
    func submit(_ submission: SpeechSubmission) throws { throw InertError.unexpectedCall }

    func perform(_ command: SpeechCommand) throws {
        lock.lock()
        recordedCommands.append(command)
        lock.unlock()
        commandPerformed.fulfill()
    }

    func purgeCachedAudio() throws -> CachePurgeReceipt { cachePurgeReceipt }

    func subscribe(shouldContinue: () -> Bool, onChange: () -> Void) throws {
        throw InertError.unexpectedCall
    }
}

private final class RecordingCurrentSelectionEnqueuer: CurrentSelectionEnqueueing,
    @unchecked Sendable
{
    let called = XCTestExpectation(description: "current selection enqueue called")
    private let lock = NSLock()
    private var recordedProcessIdentifier: Int32?

    var processIdentifier: Int32? {
        lock.lock()
        defer { lock.unlock() }
        return recordedProcessIdentifier
    }

    func enqueueCurrentSelection(from processIdentifier: Int32?) throws {
        lock.lock()
        recordedProcessIdentifier = processIdentifier
        lock.unlock()
        called.fulfill()
    }
}

private final class RecordingClipboardEnqueuer: ClipboardEnqueueing, @unchecked Sendable {
    let called = XCTestExpectation(description: "clipboard enqueue called")
    private let lock = NSLock()
    private var recordedCallCount = 0

    var callCount: Int {
        lock.lock()
        defer { lock.unlock() }
        return recordedCallCount
    }

    func enqueueClipboard() throws {
        lock.lock()
        recordedCallCount += 1
        lock.unlock()
        called.fulfill()
    }
}

private enum InertError: Error {
    case unexpectedCall
}
