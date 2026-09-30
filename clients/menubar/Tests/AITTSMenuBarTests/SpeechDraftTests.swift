// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (application/wire boundaries, no ambient input or daemon)
// Test-Oracle: edited source, chosen voice/model, confidential policy, and imports survive submission

import AITTSApplication
import Foundation
import XCTest
@testable import AITTSMacAdapters

final class SpeechDraftTests: XCTestCase {
    override func setUp() { super.setUp(); executionTimeAllowance = 15 }

    func testEditedDraftAndChoicesReachDaemon() throws {
        var draft = SpeechDraft()
        draft.text = "Typed introduction."
        try draft.append("# Attached text", origin: "file:notes.md", format: .markdown)
        draft.text += "\nAn edit before submitting."
        draft.voice = "af_heart"
        draft.engine = "kokoro"
        let transport = DraftTransport()
        try UnixSocketSpeechService(transport: transport).submit(draft.submission())
        let sent = try XCTUnwrap(transport.sent)
        XCTAssertEqual(sent["text"] as? String, "Typed introduction.\n\n# Attached text\nAn edit before submitting.")
        XCTAssertEqual(sent["voice"] as? String, "af_heart")
        XCTAssertEqual(sent["engine"] as? String, "kokoro")
        XCTAssertEqual(sent["content_format"] as? String, "markdown")
        XCTAssertEqual(sent["sensitivity"] as? String, "confidential")
        XCTAssertEqual(sent["source"] as? String, "menubar-composer:file:notes.md")
    }

    func testInvalidDraftNeverProducesSubmissionAndOversizedImportPreservesEdits() throws {
        var draft = SpeechDraft()
        draft.text = " \n\t"
        XCTAssertThrowsError(try draft.submission())
        draft.text = "Keep this."
        XCTAssertThrowsError(try draft.append(String(repeating: "é", count: 262144),
                                             origin: "clipboard", format: .plainText))
        XCTAssertEqual(draft.text, "Keep this.")
        XCTAssertEqual(draft.origins, [])
        draft.text = String(repeating: "é", count: 262145)
        XCTAssertThrowsError(try draft.submission())
    }
}

private final class DraftTransport: DaemonTransport, @unchecked Sendable {
    var sent: [String: Any]?
    func request(_ payload: [String: Any]) throws -> [String: Any] {
        sent = payload
        return ["ok": true]
    }
    func subscribe(shouldContinue: () -> Bool, onEvent: (Data) -> Void) throws {}
}
