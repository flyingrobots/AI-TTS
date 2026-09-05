// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (Swift application boundary with owned fakes)
// Test-Oracle: typed selection and document admission policy for interchangeable OS adapters

import Foundation
import XCTest

import AITTSApplication

final class SpeechApplicationTests: XCTestCase {
    override func setUp() {
        super.setUp()
        executionTimeAllowance = 15
    }

    func testDocumentEnqueueProjectsOneSelectedFileIntoConfidentialSpeech() throws {
        let selectedURL = URL(fileURLWithPath: "/selected/revenue.md")
        let documents = StubDocumentReader(
            document: SpeechDocument(
                filename: "revenue.md",
                text: "# Revenue\n\nThe exact source.",
                contentFormat: .markdown
            )
        )
        let speech = RecordingSpeechService()
        let enqueue = EnqueueDocument(
            documents: documents,
            speech: speech,
            sourcePrefix: "menubar-file"
        )

        try enqueue.enqueueDocument(at: selectedURL)

        XCTAssertEqual(documents.requestedURLs, [selectedURL])
        XCTAssertEqual(
            speech.submissions,
            [
                SpeechSubmission(
                    text: "# Revenue\n\nThe exact source.",
                    contentFormat: .markdown,
                    voice: nil,
                    speed: nil,
                    sensitivity: .confidential,
                    priority: .normal,
                    source: "menubar-file:revenue.md"
                )
            ]
        )
    }

    func testSelectionEnqueuePreservesExactLiteralTextAndOwnsAdmissionPolicy() throws {
        let speech = RecordingSpeechService()
        let enqueue = EnqueueSelection(speech: speech)
        let selectedText = "  # Release notes\n\nKeep **this** literal.\n"

        try enqueue.enqueueSelection(selectedText, source: "macos-service:text")

        XCTAssertEqual(
            speech.submissions,
            [
                SpeechSubmission(
                    text: selectedText,
                    contentFormat: .plainText,
                    voice: nil,
                    speed: nil,
                    sensitivity: .confidential,
                    priority: .normal,
                    source: "macos-service:text"
                )
            ]
        )
    }

    func testSelectionEnqueueRejectsWhitespaceWithoutSubmitting() throws {
        let speech = RecordingSpeechService()
        let enqueue = EnqueueSelection(speech: speech)

        XCTAssertThrowsError(
            try enqueue.enqueueSelection(" \n\t", source: "macos-service:text")
        ) { error in
            XCTAssertEqual(error as? SpeechSelectionError, .noSpeakableText)
            XCTAssertEqual(
                error.localizedDescription,
                "The selection contains no speakable text."
            )
        }
        XCTAssertEqual(speech.submissions, [])
    }
}

private final class StubDocumentReader: SpeechDocumentReaderPort, @unchecked Sendable {
    let document: SpeechDocument
    private(set) var requestedURLs: [URL] = []

    init(document: SpeechDocument) {
        self.document = document
    }

    func read(_ url: URL) throws -> SpeechDocument {
        requestedURLs.append(url)
        return document
    }
}

private final class RecordingSpeechService: SpeechServicePort, @unchecked Sendable {
    private(set) var submissions: [SpeechSubmission] = []

    func snapshot() throws -> Snapshot {
        throw TestFailure.unexpectedCall
    }

    func submit(_ submission: SpeechSubmission) throws {
        submissions.append(submission)
    }

    func perform(_ command: SpeechCommand) throws {
        throw TestFailure.unexpectedCall
    }

    func subscribe(shouldContinue: () -> Bool, onChange: () -> Void) throws {
        throw TestFailure.unexpectedCall
    }
}

private enum TestFailure: Error {
    case unexpectedCall
}
