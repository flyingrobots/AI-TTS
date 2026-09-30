// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (in-memory composer, owned ports, event-driven completion)
// Test-Oracle: imports remain editable until explicit submit; rejection retains the draft and explains failure

import AITTSApplication
import Foundation
import XCTest
@testable import AITTSMenuBar

final class SpeechComposerTests: XCTestCase {
    override func setUp() { super.setUp(); executionTimeAllowance = 15 }

    @MainActor
    func testImportsDoNotSpeakUntilExplicitSubmission() throws {
        let ports = ComposerPorts()
        let composer = SpeechComposer(speech: ports, documents: ports, clipboard: ports, selection: ports)
        composer.priorApplication = 42
        drain { await composer.attach(URL(fileURLWithPath: "/owned/source.md")) }
        drain { await composer.pasteClipboard() }
        drain { await composer.importSelection() }
        XCTAssertEqual(composer.draft.text, "# File\n\nClipboard\n\nSelection 42")
        XCTAssertEqual(ports.submissions, [])
        composer.draft.text += "\nEdited."
        composer.draft.voice = "af_heart"
        composer.draft.engine = "kokoro"
        drain { await composer.submit(playbackHeld: true) }
        XCTAssertEqual(ports.submissions, [SpeechSubmission(
            text: "# File\n\nClipboard\n\nSelection 42\nEdited.", contentFormat: .markdown,
            voice: "af_heart", speed: nil, sensitivity: .confidential, priority: .normal,
            source: "menubar-composer:file:source.md+clipboard+selection", engine: "kokoro")])
        XCTAssertEqual(composer.draft.text, "")
        XCTAssertEqual(composer.notice, "Queued. Playback is paused; use Resume when you’re ready.")
        XCTAssertFalse(composer.busy)
    }

    @MainActor
    func testRejectedSubmissionKeepsDraftAndShowsDaemonReason() {
        let ports = ComposerPorts(reject: true)
        let composer = SpeechComposer(speech: ports, documents: ports, clipboard: ports, selection: ports)
        composer.draft.text = "Do not lose my draft."
        drain { await composer.submit(playbackHeld: false) }
        XCTAssertEqual(composer.draft.text, "Do not lose my draft.")
        XCTAssertEqual(composer.error, "Selected model unavailable")
        XCTAssertNil(composer.notice)
        XCTAssertFalse(composer.busy)
    }

    @MainActor
    private func drain(_ operation: @escaping @MainActor () async -> Void) {
        let finished = expectation(description: "Composer operation completed")
        Task { await operation(); finished.fulfill() }
        wait(for: [finished], timeout: 2)
    }
}

private final class ComposerPorts: SpeechServicePort, SpeechDocumentReaderPort,
    ClipboardTextReaderPort, SelectedTextReaderPort, @unchecked Sendable {
    private let lock = NSLock()
    private var recorded: [SpeechSubmission] = []
    private let reject: Bool
    init(reject: Bool = false) { self.reject = reject }
    var submissions: [SpeechSubmission] {
        lock.lock(); defer { lock.unlock() }; return recorded
    }
    func submit(_ submission: SpeechSubmission) throws {
        if reject { throw SpeechServiceError.rejected(type: "bad_request", message: "Selected model unavailable") }
        lock.lock(); defer { lock.unlock() }; recorded.append(submission)
    }
    func read(_ url: URL) throws -> SpeechDocument {
        SpeechDocument(filename: url.lastPathComponent, text: "# File", contentFormat: .markdown)
    }
    func readClipboardText() throws -> String { "Clipboard" }
    func readSelectedText(from processIdentifier: Int32) throws -> String { "Selection \(processIdentifier)" }
    func snapshot() throws -> Snapshot { throw SpeechServiceError.unavailable }
    func perform(_ command: SpeechCommand) throws { throw SpeechServiceError.unavailable }
    func purgeCachedAudio() throws -> CachePurgeReceipt { throw SpeechServiceError.unavailable }
    func subscribe(shouldContinue: () -> Bool, onChange: () -> Void) throws {}
}
