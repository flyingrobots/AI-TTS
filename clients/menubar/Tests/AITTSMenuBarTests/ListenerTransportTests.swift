// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned Unix-socket transport fake)
// Test-Oracle: the daemon wire contract for chunk stepping, listener interrupts,
// and the per-client voice register

import Foundation
import XCTest

import AITTSApplication

@testable import AITTSMacAdapters
@testable import AITTSMenuBar

final class ListenerTransportTests: XCTestCase {
    override func setUp() {
        super.setUp()
        executionTimeAllowance = 15
    }

    // MARK: - Commands out

    func testChunkAndInterruptCommandsMapToExactDaemonRequests() throws {
        let transport = ListenerTransport()
        let service = UnixSocketSpeechService(transport: transport)

        try service.perform(.nextSegment)
        try service.perform(.previousSegment)
        try service.perform(.resumeWhenInputIdle)
        try service.perform(.setInputInterruptEnabled(false))
        try service.perform(.setInputInterruptResume(.whenIdle))

        XCTAssertEqual(
            try transport.canonicalRequests(),
            [
                #"{"op":"next_segment"}"#,
                #"{"op":"previous_segment"}"#,
                #"{"op":"resume_when_input_idle"}"#,
                #"{"op":"settings","set":{"input_interrupt_enabled":false}}"#,
                #"{"op":"settings","set":{"input_interrupt_resume":"when_idle"}}"#,
            ]
        )
    }

    func testVoiceAssignmentCommandsMapToExactDaemonRequests() throws {
        let transport = ListenerTransport()
        let service = UnixSocketSpeechService(transport: transport)

        try service.perform(.assignVoice(source: "claude-code", voice: "af_heart"))
        try service.perform(.releaseVoice(source: "claude-code"))

        XCTAssertEqual(
            try transport.canonicalRequests(),
            [
                #"{"op":"assign_voice","source":"claude-code","voice":"af_heart"}"#,
                // Releasing is stated rather than implied by an absent voice.
                #"{"op":"assign_voice","release":true,"source":"claude-code"}"#,
            ]
        )
    }

    // MARK: - Snapshot in

    func testSnapshotCarriesInterruptionAndVoiceRegister() throws {
        let transport = ListenerTransport(responses: [Self.snapshotJSON])
        let service = UnixSocketSpeechService(transport: transport)

        let snapshot = try service.snapshot()

        XCTAssertEqual(snapshot.status.inputActive, true)
        let interruption = try XCTUnwrap(snapshot.status.interruption)
        XCTAssertEqual(interruption.reason, "listener_speaking")
        XCTAssertEqual(interruption.at, 1_788_000_000, accuracy: 0.001)
        XCTAssertTrue(interruption.resumeArmed)

        XCTAssertEqual(snapshot.inputInterruptEnabled, true)
        XCTAssertEqual(snapshot.inputInterruptResume, .whenIdle)
        XCTAssertEqual(
            snapshot.voiceAssignments,
            [
                VoiceAssignment(
                    source: "an-agent",
                    voice: "bm_daniel",
                    pinned: false,
                    assignedAt: 1_788_000_001
                ),
                VoiceAssignment(
                    source: "codex",
                    voice: "bm_george",
                    pinned: true,
                    assignedAt: 1_788_000_002
                ),
            ]
        )
    }

    func testSnapshotWithoutTheNewFieldsKeepsWorking() throws {
        // An older daemon says nothing about interrupts or the register; the
        // client must still render rather than refusing the response.
        let transport = ListenerTransport(responses: [
            [
                "ok": true,
                "status": [
                    "playback_state": "playing", "current": NSNull(),
                    "counts": [:], "voice": "bf_emma", "engine": "kokoro",
                ],
            ]
        ])
        let service = UnixSocketSpeechService(transport: transport)

        let snapshot = try service.snapshot()

        XCTAssertNil(snapshot.status.inputActive)
        XCTAssertNil(snapshot.status.interruption)
        XCTAssertEqual(snapshot.voiceAssignments, [])
        XCTAssertEqual(snapshot.inputInterruptResume, .manual)
        XCTAssertTrue(snapshot.inputInterruptEnabled)
    }

    func testAnInterruptionMissingItsReasonIsIgnored() throws {
        let transport = ListenerTransport(responses: [
            [
                "ok": true,
                "status": [
                    "playback_state": "paused", "current": NSNull(),
                    "counts": [:], "voice": "bf_emma", "engine": "kokoro",
                    "interruption": ["at": 1.0, "resume_armed": false],
                ],
            ]
        ])
        let service = UnixSocketSpeechService(transport: transport)

        XCTAssertNil(try service.snapshot().status.interruption)
    }

    // MARK: - Reading a clip in full

    func testTheFullTextSubjectCarriesTheWholeClip() {
        let long = String(repeating: "sentence. ", count: 400)
        let subject = FullTextSubject(
            id: "utt_1",
            text: long,
            voice: "af_heart",
            source: "claude-code",
            segmentCount: 4,
            activeSegmentText: "sentence."
        )

        // Captions show one chunk and the popover shows three lines; this is
        // the only surface carrying all of it.
        XCTAssertEqual(subject.text, long)
        XCTAssertTrue(subject.isChunked)
        XCTAssertEqual(FullTextWindowController.title(for: subject), "Full text — claude-code")
    }

    func testAnUnsourcedClipStillGetsAWindowTitle() {
        let subject = FullTextSubject(
            id: "utt_2",
            text: "short",
            voice: "af_heart",
            source: nil,
            segmentCount: 1,
            activeSegmentText: nil
        )

        XCTAssertFalse(subject.isChunked)
        XCTAssertEqual(FullTextWindowController.title(for: subject), "Full text")
    }

    // MARK: - Grouping 41 voices

    func testVoicesGroupByLanguageInAStableOrder() {
        let groups = VoiceLanguage.groups(of: [
            "im_nicola", "af_heart", "bm_daniel", "ef_dora", "af_bella",
        ])

        XCTAssertEqual(
            groups.map(\.name),
            ["American English", "British English", "Spanish", "Italian"]
        )
        XCTAssertEqual(groups.first?.voices, ["af_bella", "af_heart"])
    }

    func testAnUnknownVoicePrefixStillGroups() {
        let groups = VoiceLanguage.groups(of: ["qq_mystery"])

        XCTAssertEqual(groups.map(\.name), ["Other"])
    }

    private static let snapshotJSON: [String: Any] = [
        "ok": true,
        "status": [
            "playback_state": "paused",
            "current": NSNull(),
            "counts": ["Played": 3],
            "voice": "bf_emma",
            "engine": "kokoro",
            "input_active": true,
            "interruption": [
                "reason": "listener_speaking",
                "at": 1_788_000_000,
                "resume_armed": true,
            ],
        ],
        "plan": [],
        "input": [],
        "history": [],
        "voices": ["bf_emma", "bm_daniel", "bm_george"],
        "voice_assignments": [
            [
                "source": "an-agent", "voice": "bm_daniel",
                "pinned": false, "assigned_at": 1_788_000_001,
            ],
            [
                "source": "codex", "voice": "bm_george",
                "pinned": true, "assigned_at": 1_788_000_002,
            ],
        ],
        "settings": [
            "speed": 1.0,
            "playback_rate": 1.0,
            "captions_enabled": false,
            "captions_enabled_configured": true,
            "input_interrupt_enabled": true,
            "input_interrupt_resume": "when_idle",
        ],
    ]
}

private final class ListenerTransport: DaemonTransport, @unchecked Sendable {
    private(set) var requests: [[String: Any]] = []
    private var responses: [[String: Any]]

    init(responses: [[String: Any]] = []) {
        self.responses = responses
    }

    func request(_ payload: [String: Any]) throws -> [String: Any] {
        requests.append(payload)
        return responses.isEmpty ? ["ok": true] : responses.removeFirst()
    }

    func subscribe(shouldContinue: () -> Bool, onEvent: (Data) -> Void) throws {
        _ = shouldContinue()
    }

    func canonicalRequests() throws -> [String] {
        try requests.map { payload in
            let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
            return try XCTUnwrap(String(data: data, encoding: .utf8))
        }
    }
}

extension ListenerTransportTests {

    // MARK: - An unavailable microphone reading

    func testAnAbsentInputReadingDecodesAsUnknownRatherThanQuiet() throws {
        let transport = ListenerTransport(responses: [
            [
                "ok": true,
                "status": [
                    "playback_state": "playing", "current": NSNull(),
                    "counts": [:], "voice": "bf_emma", "engine": "kokoro",
                    "input_active": NSNull(),
                ],
            ]
        ])
        let service = UnixSocketSpeechService(transport: transport)

        // Quiet and unanswerable are different states, and collapsing them
        // tells the listener their voice takes precedence when nothing is
        // watching for it.
        XCTAssertNil(try service.snapshot().status.inputActive)
    }

    func testAReadableQuietInputDecodesAsFalse() throws {
        let transport = ListenerTransport(responses: [
            [
                "ok": true,
                "status": [
                    "playback_state": "playing", "current": NSNull(),
                    "counts": [:], "voice": "bf_emma", "engine": "kokoro",
                    "input_active": false,
                ],
            ]
        ])
        let service = UnixSocketSpeechService(transport: transport)

        XCTAssertEqual(try service.snapshot().status.inputActive, false)
    }
}

extension ListenerTransportTests {

    // MARK: - Accessibility is a value, not a modifier somebody remembers

    func testEveryTransportActionCarriesASpokenLabelAndAKey() {
        // An icon-only button discards its text label from the accessibility
        // tree, and this is a tool for people who are listening. A missing
        // label here is a control that cannot be found by voice.
        XCTAssertEqual(TransportAction.allCases.count, 5)
        var seenKeys: Set<String> = []
        for action in TransportAction.allCases {
            XCTAssertFalse(action.label.isEmpty, "\(action.rawValue) has no label")
            XCTAssertFalse(action.systemImage.isEmpty, "\(action.rawValue) has no icon")
            let key = String(describing: action.shortcut.character)
            XCTAssertFalse(
                seenKeys.contains(key),
                "\(action.rawValue) reuses the key \(key)"
            )
            seenKeys.insert(key)
        }
    }

    func testOnlyTheChunkControlsClaimToNeedChunks() {
        let needing = TransportAction.allCases.filter(\.needsChunks)

        XCTAssertEqual(Set(needing), [.previousChunk, .nextChunk])
    }
}
