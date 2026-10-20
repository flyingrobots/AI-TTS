// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium
// Test-Oracle: status tray context menu item actions and gating

import AppKit
import XCTest

import AITTSApplication
@testable import AITTSMacAdapters
@testable import AITTSMenuBar

private struct ContextMenuTestPorts: SpeechServicePort, DocumentEnqueueing,
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
final class ContextMenuTests: XCTestCase {
    private var state: AppState!
    private var controller: StatusController!
    private var suiteName: String!
    private var defaults: UserDefaults!

    deinit {}

    override func setUp() {
        super.setUp()
        executionTimeAllowance = 15
        suiteName = "ai-tts-context-menu-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suiteName)!
        let ports = ContextMenuTestPorts()
        state = AppState(
            speech: ports,
            documentEnqueuer: ports,
            currentSelectionEnqueuer: ports,
            clipboardEnqueuer: ports,
            defaults: defaults
        )
        controller = StatusController(state: state)
    }

    override func tearDown() {
        state.stopPolling()
        defaults.removePersistentDomain(forName: suiteName)
        state = nil
        controller = nil
        defaults = nil
        super.tearDown()
    }

    func testContextMenuContainsRequiredActions() {
        let menu = controller.buildContextMenu()
        let titles = menu.items.compactMap { $0.isSeparatorItem ? nil : $0.title }

        XCTAssertEqual(titles, ["Play", "Next Part", "Next", "Clear", "Quit"])
    }

    func testContextMenuTitlesReflectPlaybackState() throws {
        // Paused state -> "Play"
        let pausedSnapshot = try XCTUnwrap(Snapshot(daemonJSON: [
            "status": [
                "playback_state": "paused",
                "state": "idle",
            ]
        ]))
        state.applySnapshot(pausedSnapshot)
        var menu = controller.buildContextMenu()
        XCTAssertEqual(menu.items.first?.title, "Play")

        // Playing state -> "Pause"
        let playingSnapshot = try XCTUnwrap(Snapshot(daemonJSON: [
            "status": [
                "playback_state": "playing",
                "state": "active",
            ]
        ]))
        state.applySnapshot(playingSnapshot)
        menu = controller.buildContextMenu()
        XCTAssertEqual(menu.items.first?.title, "Pause")
    }

    func testNextPartEnabledOnlyWhenCurrentClipHasMultipleChunks() throws {
        // Clip with 1 chunk -> Next Part disabled
        let singleChunkSnapshot = try XCTUnwrap(Snapshot(daemonJSON: [
            "status": [
                "playback_state": "playing",
                "current": [
                    "id": "utt-1",
                    "text": "Hello",
                    "voice": "af_alloy",
                    "state": "Playing",
                    "segment_count": 1,
                ],
            ]
        ]))
        state.applySnapshot(singleChunkSnapshot)
        var menu = controller.buildContextMenu()
        let nextPartSingle = menu.items.first { $0.title == "Next Part" }
        XCTAssertEqual(nextPartSingle?.isEnabled, false)

        // Clip with 5 chunks -> Next Part enabled
        let multiChunkSnapshot = try XCTUnwrap(Snapshot(daemonJSON: [
            "status": [
                "playback_state": "playing",
                "current": [
                    "id": "utt-2",
                    "text": "Hello world",
                    "voice": "af_alloy",
                    "state": "Playing",
                    "segment_count": 5,
                ],
            ]
        ]))
        state.applySnapshot(multiChunkSnapshot)
        menu = controller.buildContextMenu()
        let nextPartMulti = menu.items.first { $0.title == "Next Part" }
        XCTAssertEqual(nextPartMulti?.isEnabled, true)
    }

    func testMenuDisablesAutomaticItemValidationToPreserveManualGating() throws {
        let singleChunkSnapshot = try XCTUnwrap(Snapshot(daemonJSON: [
            "status": [
                "playback_state": "playing",
                "current": [
                    "id": "utt-1",
                    "text": "Hello",
                    "voice": "af_alloy",
                    "state": "Playing",
                    "segment_count": 1,
                ],
            ]
        ]))
        state.applySnapshot(singleChunkSnapshot)
        let menu = controller.buildContextMenu()
        XCTAssertFalse(menu.autoenablesItems)

        menu.update()
        let nextPartItem = menu.items.first { $0.title == "Next Part" }
        XCTAssertEqual(nextPartItem?.isEnabled, false)
    }
}
