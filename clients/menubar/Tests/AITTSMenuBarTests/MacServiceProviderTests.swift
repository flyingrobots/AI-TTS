// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (isolated macOS Services pasteboards with owned fakes)
// Test-Oracle: native Services inputs delegate exactly once or return a typed refusal

import AppKit
import Foundation
import XCTest

import AITTSApplication
@testable import AITTSMacEntryPoints

final class MacServiceProviderTests: XCTestCase {
    override func setUp() {
        super.setUp()
        executionTimeAllowance = 15
    }

    func testSelectedTextDelegatesExactPasteboardStringToApplicationPort() throws {
        let selections = RecordingSelectionEnqueuer()
        let documents = RecordingDocumentEnqueuer()
        let provider = MacServiceProvider(
            selectionEnqueuer: selections,
            documentEnqueuer: documents
        )
        let pasteboard = makePasteboard()
        let selectedText = "  # Release notes\n\nKeep **this** literal.\n"
        XCTAssertTrue(pasteboard.setString(selectedText, forType: .string))

        try provider.enqueueSelectedText(from: pasteboard)

        XCTAssertEqual(
            selections.requests,
            [SelectionRequest(text: selectedText, source: "macos-service:text")]
        )
        XCTAssertEqual(documents.urls, [])
    }

    func testMissingTextReturnsActionableServiceErrorWithoutDelegating() {
        let selections = RecordingSelectionEnqueuer()
        let provider = MacServiceProvider(
            selectionEnqueuer: selections,
            documentEnqueuer: RecordingDocumentEnqueuer()
        )
        let pasteboard = makePasteboard()
        var serviceError: NSString?

        provider.readSelection(pasteboard, userData: nil, error: &serviceError)

        XCTAssertEqual(
            serviceError as String?,
            "Select text before choosing Read Selection with AI-TTS."
        )
        XCTAssertEqual(selections.requests, [])
    }

    func testSingleFileURLDelegatesToDocumentApplicationPort() throws {
        let documents = RecordingDocumentEnqueuer()
        let provider = MacServiceProvider(
            selectionEnqueuer: RecordingSelectionEnqueuer(),
            documentEnqueuer: documents
        )
        let pasteboard = makePasteboard()
        let selectedURL = URL(fileURLWithPath: "/selected/revenue.md")
        XCTAssertTrue(pasteboard.writeObjects([selectedURL as NSURL]))

        try provider.enqueueSelectedFile(from: pasteboard)

        XCTAssertEqual(documents.urls, [selectedURL])
    }

    func testMissingFileReturnsTypedRefusalWithoutDelegating() {
        let documents = RecordingDocumentEnqueuer()
        let provider = MacServiceProvider(
            selectionEnqueuer: RecordingSelectionEnqueuer(),
            documentEnqueuer: documents
        )
        let pasteboard = makePasteboard()

        XCTAssertThrowsError(try provider.enqueueSelectedFile(from: pasteboard)) { error in
            XCTAssertEqual(
                error as? MacServiceInputError,
                .requiresSingleFile(actualCount: 0)
            )
        }
        XCTAssertEqual(documents.urls, [])
    }

    func testMultipleFilesReturnTypedRefusalWithoutPartialDelegation() {
        let documents = RecordingDocumentEnqueuer()
        let provider = MacServiceProvider(
            selectionEnqueuer: RecordingSelectionEnqueuer(),
            documentEnqueuer: documents
        )
        let pasteboard = makePasteboard()
        let firstURL = URL(fileURLWithPath: "/selected/one.txt")
        let secondURL = URL(fileURLWithPath: "/selected/two.pdf")
        XCTAssertTrue(pasteboard.writeObjects([firstURL as NSURL, secondURL as NSURL]))

        XCTAssertThrowsError(try provider.enqueueSelectedFile(from: pasteboard)) { error in
            XCTAssertEqual(
                error as? MacServiceInputError,
                .requiresSingleFile(actualCount: 2)
            )
        }
        XCTAssertEqual(documents.urls, [])
    }

    func testProviderExportsSelectorsDeclaredByBundleMetadata() {
        let provider = MacServiceProvider(
            selectionEnqueuer: RecordingSelectionEnqueuer(),
            documentEnqueuer: RecordingDocumentEnqueuer()
        )

        XCTAssertTrue(provider.responds(to: NSSelectorFromString("readSelection:userData:error:")))
        XCTAssertTrue(provider.responds(to: NSSelectorFromString("readFile:userData:error:")))
    }

    private func makePasteboard() -> NSPasteboard {
        let name = NSPasteboard.Name("ai-tts-service-tests-\(UUID().uuidString)")
        let pasteboard = NSPasteboard(name: name)
        pasteboard.clearContents()
        return pasteboard
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

private final class RecordingDocumentEnqueuer: DocumentEnqueueing, @unchecked Sendable {
    private(set) var urls: [URL] = []

    func enqueueDocument(at url: URL) throws {
        urls.append(url)
    }
}
