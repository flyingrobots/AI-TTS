// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned Unix-socket transport fake)
// Test-Oracle: typed speech operations map exactly to the approved daemon protocol

import Foundation
import XCTest

import AITTSApplication
@testable import AITTSMacAdapters

final class UnixSocketSpeechServiceTests: XCTestCase {
    override func setUp() {
        super.setUp()
        executionTimeAllowance = 15
    }

    func testTypedSubmissionAndCommandsMapToExactDaemonRequests() throws {
        let transport = RecordingDaemonTransport()
        let service = UnixSocketSpeechService(transport: transport)

        try service.submit(
            SpeechSubmission(
                text: "Exact text",
                contentFormat: .markdown,
                voice: "bm_george",
                speed: 1.25,
                sensitivity: .internal,
                priority: .urgent,
                source: "finder-service"
            )
        )
        let commands: [SpeechCommand] = [
            .pause,
            .resume,
            .skip,
            .rewind(to: nil),
            .rewind(to: "utt_previous"),
            .cancel(id: "utt_cancel"),
            .clearQueue,
            .clearHistory,
            .removeHistory(id: "utt_old"),
            .requeue(id: "utt_retry", priority: .urgent),
            .reorder(ids: ["utt_2", "utt_1"]),
            .setVoice("bf_emma"),
            .setSynthesisSpeed(0.9),
            .setPlaybackRate(2.0),
            .setCaptionsEnabled(true),
        ]
        for command in commands { try service.perform(command) }

        XCTAssertEqual(
            try transport.canonicalRequests(),
            try canonicalize([
                [
                    "op": "submit", "text": "Exact text", "voice": "bm_george",
                    "speed": 1.25, "sensitivity": "internal", "priority": "urgent",
                    "source": "finder-service", "content_format": "markdown",
                ],
                ["op": "pause"],
                ["op": "resume"],
                ["op": "skip"],
                ["op": "rewind"],
                ["op": "rewind", "to": "utt_previous"],
                ["op": "cancel", "id": "utt_cancel"],
                ["op": "clear", "queue": "queue"],
                ["op": "clear", "queue": "history"],
                ["op": "remove_history", "id": "utt_old"],
                ["op": "requeue", "id": "utt_retry", "priority": "urgent"],
                ["op": "reorder", "ids": ["utt_2", "utt_1"]],
                ["op": "settings", "set": ["voice": "bf_emma"]],
                ["op": "settings", "set": ["speed": 0.9]],
                ["op": "settings", "set": ["playback_rate": 2.0]],
                ["op": "settings", "set": ["captions_enabled": true]],
            ])
        )
    }

    func testSubmissionOmitsUnspecifiedOverrides() throws {
        let transport = RecordingDaemonTransport()
        let service = UnixSocketSpeechService(transport: transport)

        try service.submit(
            SpeechSubmission(
                text: "Use daemon defaults",
                contentFormat: .plainText,
                voice: nil,
                speed: nil,
                sensitivity: .confidential,
                priority: .normal,
                source: nil
            )
        )

        XCTAssertEqual(
            try transport.canonicalRequests(),
            try canonicalize([
                [
                    "op": "submit", "text": "Use daemon defaults",
                    "sensitivity": "confidential", "priority": "normal",
                    "content_format": "plain_text",
                ]
            ])
        )
    }

    func testSnapshotTranslatesDaemonResponseIntoApplicationModel() throws {
        let transport = RecordingDaemonTransport(responses: [snapshotResponse])
        let service = UnixSocketSpeechService(transport: transport)

        let snapshot = try service.snapshot()

        XCTAssertEqual(try transport.canonicalRequests(), try canonicalize([["op": "snapshot"]]))
        XCTAssertEqual(snapshot.status.playbackState, "playing")
        XCTAssertEqual(snapshot.status.current?.activeSegment?.text, "Clean spoken text.")
        XCTAssertEqual(snapshot.plan.map(\.id), ["utt_1", "utt_2"])
        XCTAssertEqual(snapshot.plan.last?.priority, .urgent)
        XCTAssertEqual(snapshot.voices, ["bm_george", "bf_emma"])
        XCTAssertEqual(snapshot.speed, 1.25)
        XCTAssertEqual(snapshot.playbackRate, 1.5)
        XCTAssertTrue(snapshot.captionsEnabled)
    }

    func testMalformedSnapshotBecomesTypedApplicationError() {
        let transport = RecordingDaemonTransport(responses: [["ok": true]])
        let service = UnixSocketSpeechService(transport: transport)

        XCTAssertThrowsError(try service.snapshot()) { error in
            XCTAssertEqual(error as? SpeechServiceError, .invalidResponse)
        }
    }

    func testDaemonRejectionBecomesTypedApplicationError() {
        let transport = RecordingDaemonTransport(
            requestError: WireError.daemon(type: "bad_request", message: "No such item")
        )
        let service = UnixSocketSpeechService(transport: transport)

        XCTAssertThrowsError(try service.perform(.cancel(id: "missing"))) { error in
            XCTAssertEqual(
                error as? SpeechServiceError,
                .rejected(type: "bad_request", message: "No such item")
            )
        }
    }

    func testSubscriptionProjectsTransportEventsAsChangeSignals() throws {
        let transport = RecordingDaemonTransport(subscriptionEventCount: 2)
        let service = UnixSocketSpeechService(transport: transport)
        var changes = 0

        try service.subscribe(
            shouldContinue: { true },
            onChange: { changes += 1 }
        )

        XCTAssertEqual(transport.subscriptionCount, 1)
        XCTAssertEqual(changes, 2)
    }

    private var snapshotResponse: [String: Any] {
        [
            "ok": true,
            "status": [
                "playback_state": "playing",
                "current": [
                    "id": "utt_1", "text": "source", "voice": "bm_george",
                    "state": "Playing", "position_ms": 42,
                    "active_segment": [
                        "index": 0, "number": 1, "count": 2,
                        "text": "Clean spoken text.", "state": "Playing",
                    ],
                ],
                "counts": ["Queued": 1],
                "voice": "bm_george",
                "engine": "kokoro",
            ],
            "plan": [
                ["id": "utt_1", "text": "source", "voice": "bm_george", "state": "Playing"],
                [
                    "id": "utt_2", "text": "next", "voice": "bm_george",
                    "state": "Ready", "priority": "urgent",
                ],
            ],
            "input": [],
            "history": [],
            "voices": ["bm_george", "bf_emma"],
            "settings": [
                "speed": 1.25, "playback_rate": 1.5, "captions_enabled": true,
            ],
        ]
    }

    private func canonicalize(_ payloads: [[String: Any]]) throws -> [String] {
        try payloads.map(canonicalJSON)
    }

    private func canonicalJSON(_ payload: [String: Any]) throws -> String {
        let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        return try XCTUnwrap(String(data: data, encoding: .utf8))
    }
}

private final class RecordingDaemonTransport: DaemonTransport, @unchecked Sendable {
    private(set) var requests: [[String: Any]] = []
    private(set) var subscriptionCount = 0
    private var responses: [[String: Any]]
    private let requestError: Error?
    private let subscriptionEventCount: Int

    init(
        responses: [[String: Any]] = [],
        requestError: Error? = nil,
        subscriptionEventCount: Int = 0
    ) {
        self.responses = responses
        self.requestError = requestError
        self.subscriptionEventCount = subscriptionEventCount
    }

    func request(_ payload: [String: Any]) throws -> [String: Any] {
        requests.append(payload)
        if let requestError { throw requestError }
        return responses.isEmpty ? ["ok": true] : responses.removeFirst()
    }

    func subscribe(shouldContinue: () -> Bool, onEvent: (Data) -> Void) throws {
        subscriptionCount += 1
        guard shouldContinue() else { return }
        for _ in 0..<subscriptionEventCount { onEvent(Data("{}".utf8)) }
    }

    func canonicalRequests() throws -> [String] {
        try requests.map { payload in
            let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
            guard let json = String(data: data, encoding: .utf8) else {
                throw RecordingError.invalidUTF8
            }
            return json
        }
    }
}

private enum RecordingError: Error {
    case invalidUTF8
}
