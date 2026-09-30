// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned AppKit window hosting one SwiftUI history row)
// Test-Oracle: accessible provenance action; removed history retains no details or late responses

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
        let loader = ControlledProvenanceLoader()
        let suite = "ai-tts-provenance-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let state = AppState(speech: ports, documentEnqueuer: ports,
                             currentSelectionEnqueuer: ports, clipboardEnqueuer: ports,
                             defaults: defaults, evidenceExporter: ports, provenanceLoader: loader)
        state.history = [item]
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
        let completion = try XCTUnwrap(loader.completions[item.id],
                                       "Click must request provenance for this clip")
        completion("Source: CLI; clip: clip")
        XCTAssertEqual(state.provenanceDetails[item.id], "Source: CLI; clip: clip")
    }

    @MainActor
    func testRemovedHistoryDiscardsCachedAndLateProvenance() throws {
        let ports = ProvenanceTestPorts()
        let loader = ControlledProvenanceLoader()
        let suite = "ai-tts-provenance-lifetime-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let state = AppState(speech: ports, documentEnqueuer: ports,
                             currentSelectionEnqueuer: ports, clipboardEnqueuer: ports,
                             defaults: defaults, provenanceLoader: loader)
        let clips = try ["removed", "kept", "pending"].map { id in
            try XCTUnwrap(Utterance(daemonJSON: [
                "id": id, "text": "Controlled text", "voice": "v", "state": "Played"
            ]))
        }
        func snapshot(_ history: [Utterance]) -> Snapshot {
            Snapshot(status: DaemonStatus(playbackState: "idle", current: nil,
                                           counts: [:], voice: "v", engine: "fake"),
                     plan: [], input: [], history: history, voices: ["v"],
                     speed: 1, playbackRate: 1, captionsEnabledConfigured: true)
        }
        state.applySnapshot(snapshot(clips))
        for clip in clips { state.loadProvenance(clip.id) }
        try XCTUnwrap(loader.completions["removed"])("removed details")
        try XCTUnwrap(loader.completions["kept"])("kept details")
        XCTAssertEqual(state.provenanceDetails, [
            "removed": "removed details", "kept": "kept details", "pending": "Loading…"
        ])

        state.applySnapshot(snapshot([clips[1]]))
        XCTAssertEqual(state.provenanceDetails, ["kept": "kept details"])
        try XCTUnwrap(loader.completions["pending"])("late private details")
        XCTAssertEqual(state.provenanceDetails, ["kept": "kept details"])
        state.applySnapshot(snapshot([]))
        XCTAssertTrue(state.provenanceDetails.isEmpty)
    }

    @MainActor
    func testBackgroundLoaderDeliversDetailsAndFailureOnTheMainActor() {
        let loader = BackgroundProvenanceLoader(exporter: ProvenanceTestPorts())
        for (id, expected) in [
            ("clip", "Source: CLI; clip: clip"),
            ("failure", "Provenance is unavailable. Close and reopen these details to retry.")
        ] {
            let delivered = expectation(description: "provenance completion for \(id)")
            var result: String?
            loader.load(id) { text in
                MainActor.assertIsolated()
                result = text
                delivered.fulfill()
            }
            wait(for: [delivered], timeout: 1)
            XCTAssertEqual(result, expected)
        }
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
    func provenance(id: String) throws -> String {
        if id == "failure" { throw SpeechServiceError.unavailable }
        return "Source: CLI; clip: \(id)"
    }
    func restartModel() throws {}
}

@MainActor
private final class ControlledProvenanceLoader: ProvenanceLoading {
    var completions: [String: @MainActor (String) -> Void] = [:]
    func load(_ id: String, completion: @escaping @MainActor (String) -> Void) {
        completions[id] = completion
    }
}
