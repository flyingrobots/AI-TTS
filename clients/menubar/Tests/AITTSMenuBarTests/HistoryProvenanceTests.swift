// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned AppKit window hosting one SwiftUI history row)
// Test-Oracle: provenance is an accessible button whose activation requests clip details

import AITTSApplication
import AppKit
import SwiftUI
import XCTest
@testable import AITTSMacAdapters
@testable import AITTSMenuBar

final class HistoryProvenanceTests: XCTestCase {
    override func setUp() {
        super.setUp()
        executionTimeAllowance = 15
    }

    @MainActor
    func testProvenanceButtonOpensDetailsForItsClip() throws {
        _ = NSApplication.shared
        let item = try XCTUnwrap(Utterance(daemonJSON: [
            "id": "clip", "text": "Controlled test text", "voice": "v", "state": "Played"
        ]))
        let ports = ProvenanceTestPorts()
        let suite = "ai-tts-provenance-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let state = AppState(speech: ports, documentEnqueuer: ports,
                             currentSelectionEnqueuer: ports, clipboardEnqueuer: ports,
                             defaults: defaults, evidenceExporter: ports)
        let hosting = NSHostingView(rootView: HistoryRow(item: item).environmentObject(state))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 368, height: 400),
                              styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = hosting
        window.orderFront(nil)
        hosting.layoutSubtreeIfNeeded()
        window.displayIfNeeded()
        defer { window.close() }
        let controls = descendants(hosting).compactMap { $0 as? NSButton }
        XCTAssertFalse(controls.isEmpty, "The hosted History row must contain native controls")
        let button = try XCTUnwrap(controls.first {
            $0.title == "Show provenance" || $0.accessibilityLabel() == "Show provenance"
        }, "History must expose a real, clearly labeled provenance button")
        button.performClick(nil)
        let deadline = Date().addingTimeInterval(1)
        while state.provenanceDetails[item.id] != "Source: CLI; clip: clip" && Date() < deadline {
            _ = RunLoop.main.run(mode: .default, before: deadline)
        }
        XCTAssertEqual(state.provenanceDetails[item.id], "Source: CLI; clip: clip")
    }

    @MainActor
    private func descendants(_ view: NSView) -> [NSView] {
        view.subviews + view.subviews.flatMap { descendants($0) }
    }

}

private struct ProvenanceTestPorts: SpeechServicePort, DocumentEnqueueing,
    CurrentSelectionEnqueueing, ClipboardEnqueueing, EvidenceExporting {
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
    func exportEvidence(id: String, destination: URL) throws -> [String] { [] }
    func provenance(id: String) throws -> String { "Source: CLI; clip: \(id)" }
    func restartModel() throws {}
}
