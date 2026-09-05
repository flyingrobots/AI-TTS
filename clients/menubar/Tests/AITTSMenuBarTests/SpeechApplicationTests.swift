// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (Swift application boundary with owned fakes)
// Test-Oracle: typed text, clipboard, and document admission policy for interchangeable OS adapters

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

    func testCurrentSelectionPreservesProcessTextAndConfiguredSource() throws {
        let reader = StubSelectedTextReader(text: "Exact selected text.")
        let selections = RecordingSelectionEnqueuer()
        let enqueue = EnqueueCurrentSelection(
            reader: reader,
            selectionEnqueuer: selections,
            source: "macos-accessibility:text"
        )

        try enqueue.enqueueCurrentSelection(from: 8675)

        XCTAssertEqual(reader.requestedProcessIdentifiers, [8675])
        XCTAssertEqual(
            selections.requests,
            [SelectionRequest(text: "Exact selected text.", source: "macos-accessibility:text")]
        )
    }

    func testCurrentSelectionRejectsMissingPriorApplicationBeforeReading() {
        let reader = StubSelectedTextReader(text: "must not be read")
        let selections = RecordingSelectionEnqueuer()
        let enqueue = EnqueueCurrentSelection(
            reader: reader,
            selectionEnqueuer: selections,
            source: "macos-accessibility:text"
        )

        XCTAssertThrowsError(try enqueue.enqueueCurrentSelection(from: nil)) { error in
            XCTAssertEqual(error as? CurrentSelectionError, .noPriorApplication)
        }
        XCTAssertEqual(reader.requestedProcessIdentifiers, [])
        XCTAssertEqual(selections.requests, [])
    }

    func testClipboardPreservesReaderTextAndConfiguredSource() throws {
        let reader = StubClipboardTextReader(text: "Exact clipboard text.")
        let selections = RecordingSelectionEnqueuer()
        let enqueue = EnqueueClipboard(
            reader: reader,
            selectionEnqueuer: selections,
            source: "macos-clipboard:text"
        )

        try enqueue.enqueueClipboard()

        XCTAssertEqual(reader.readCount, 1)
        XCTAssertEqual(
            selections.requests,
            [SelectionRequest(text: "Exact clipboard text.", source: "macos-clipboard:text")]
        )
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

private final class StubSelectedTextReader: SelectedTextReaderPort, @unchecked Sendable {
    private let text: String
    private(set) var requestedProcessIdentifiers: [Int32] = []

    init(text: String) {
        self.text = text
    }

    func readSelectedText(from processIdentifier: Int32) throws -> String {
        requestedProcessIdentifiers.append(processIdentifier)
        return text
    }
}

private final class StubClipboardTextReader: ClipboardTextReaderPort, @unchecked Sendable {
    private let text: String
    private(set) var readCount = 0

    init(text: String) {
        self.text = text
    }

    func readClipboardText() throws -> String {
        readCount += 1
        return text
    }
}

private struct SelectionRequest: Equatable {
    let text: String
    let source: String
}

private final class RecordingSelectionEnqueuer: SelectionEnqueueing, @unchecked Sendable {
    private(set) var requests: [SelectionRequest] = []

    func enqueueSelection(_ text: String, source: String) throws {
        requests.append(SelectionRequest(text: text, source: source))
    }
}

private enum TestFailure: Error {
    case unexpectedCall
}
