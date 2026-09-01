// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import XCTest

@testable import AITTSMenuBar

final class WireProtocolTests: XCTestCase {
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
        let utterance = Utterance(json: [
            "id": "utt_1", "text": "hello", "voice": "bm_daniel", "state": "Ready",
            "duration_ms": 1200,
        ])
        XCTAssertEqual(utterance?.id, "utt_1")
        XCTAssertEqual(utterance?.durationMs, 1200)
        XCTAssertNil(Utterance(json: ["id": "utt_2"]))
    }

    func testStatusParsesWireShape() {
        let status = DaemonStatus(json: [
            "state": "playing",
            "current": [
                "id": "utt_1", "text": "hi", "voice": "v", "state": "Playing",
            ],
            "counts": ["Queued": 2],
            "voice": "bm_daniel",
        ])
        XCTAssertEqual(status?.state, "playing")
        XCTAssertEqual(status?.current?.id, "utt_1")
        XCTAssertEqual(status?.counts["Queued"], 2)
    }

    func testIconStatePrecedence() {
        XCTAssertEqual(
            StatusController.symbolName(reachable: false, state: "playing"),
            "exclamationmark.bubble")
        XCTAssertEqual(
            StatusController.symbolName(reachable: true, state: "playing"), "waveform")
        XCTAssertEqual(
            StatusController.symbolName(reachable: true, state: "paused"), "pause.circle")
        XCTAssertEqual(
            StatusController.symbolName(reachable: true, state: "synthesizing"),
            "ellipsis.bubble")
        XCTAssertEqual(
            StatusController.symbolName(reachable: true, state: "idle"), "bubble.left")
    }
}
