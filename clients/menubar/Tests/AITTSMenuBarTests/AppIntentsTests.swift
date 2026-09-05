// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (App Intents parameter wrappers and application ports)
// Test-Oracle: accepted native automation contract in docs/design/os-integration.md section 9

import XCTest

import AITTSApplication
import AppIntents
@testable import AITTSMenuBar

final class AppIntentsTests: XCTestCase {
    func testReadTextPreservesLiteralTextAndIntentProvenance() throws {
        let ports = RecordingAppIntentPorts()
        let intent = ReadTextIntent()
        intent.text = "# literal **selection**\n"

        try intent.perform(using: dependencies(ports))

        XCTAssertEqual(
            ports.selections,
            [RecordedIntentSelection(text: "# literal **selection**\n", source: "macos-intent:text")]
        )
        XCTAssertTrue(ports.documents.isEmpty)
        XCTAssertTrue(ports.commands.isEmpty)
    }

    func testReadFileDelegatesExactAvailableURL() throws {
        let ports = RecordingAppIntentPorts()
        let url = URL(fileURLWithPath: "/private/tmp/ai-tts-intent.md")
        let intent = ReadFileIntent()
        intent.file = IntentFile(fileURL: url)

        try intent.perform(using: dependencies(ports))

        XCTAssertEqual(ports.documents, [url])
        XCTAssertTrue(ports.selections.isEmpty)
        XCTAssertTrue(ports.commands.isEmpty)
    }

    func testReadFileRejectsUnavailableFileBeforeDelegating() {
        let ports = RecordingAppIntentPorts()
        let intent = ReadFileIntent()

        XCTAssertThrowsError(
            try intent.perform(fileURL: nil, using: dependencies(ports))
        ) { error in
            XCTAssertEqual(error as? AITTSAppIntentError, .fileUnavailable)
        }
        XCTAssertTrue(ports.documents.isEmpty)
    }

    func testTransportIntentsDelegateExactCommands() throws {
        let ports = RecordingAppIntentPorts()
        let dependencies = dependencies(ports)

        try PauseSpeechIntent().perform(using: dependencies)
        try ResumeSpeechIntent().perform(using: dependencies)
        try SkipSpeechIntent().perform(using: dependencies)

        XCTAssertEqual(ports.commands, [.pause, .resume, .skip])
        XCTAssertTrue(ports.selections.isEmpty)
        XCTAssertTrue(ports.documents.isEmpty)
    }

    func testPlaybackSpeedIntentMapsEverySupportedRateToLivePlayback() throws {
        let ports = RecordingAppIntentPorts()
        let dependencies = dependencies(ports)

        for speed in IntentPlaybackRate.allCases {
            let intent = SetPlaybackSpeedIntent()
            intent.speed = speed
            try intent.perform(using: dependencies)
        }

        XCTAssertEqual(
            IntentPlaybackRate.allCases.map(\.rawValue),
            [0.5, 0.75, 1, 1.5, 2, 3]
        )
        XCTAssertEqual(
            ports.commands,
            [0.5, 0.75, 1, 1.5, 2, 3].map { .setPlaybackRate($0) }
        )
    }

    func testCatalogContainsTheSixDesignedBackgroundActions() {
        XCTAssertEqual(AITTSAppShortcuts.appShortcuts.count, 6)
        XCTAssertEqual(
            [
                String(localized: ReadTextIntent.title),
                String(localized: ReadFileIntent.title),
                String(localized: PauseSpeechIntent.title),
                String(localized: ResumeSpeechIntent.title),
                String(localized: SkipSpeechIntent.title),
                String(localized: SetPlaybackSpeedIntent.title),
            ],
            ["Read Text", "Read File", "Pause", "Resume", "Skip", "Set Playback Speed"]
        )
        XCTAssertFalse(ReadTextIntent.openAppWhenRun)
        XCTAssertFalse(ReadFileIntent.openAppWhenRun)
        XCTAssertFalse(PauseSpeechIntent.openAppWhenRun)
        XCTAssertFalse(ResumeSpeechIntent.openAppWhenRun)
        XCTAssertFalse(SkipSpeechIntent.openAppWhenRun)
        XCTAssertFalse(SetPlaybackSpeedIntent.openAppWhenRun)
    }

    private func dependencies(
        _ ports: RecordingAppIntentPorts
    ) -> AITTSAppIntentDependencies {
        AITTSAppIntentDependencies(
            selectionEnqueuer: ports,
            documentEnqueuer: ports,
            speech: ports
        )
    }
}

private struct RecordedIntentSelection: Equatable {
    let text: String
    let source: String
}

private final class RecordingAppIntentPorts: SelectionEnqueueing, DocumentEnqueueing,
    SpeechServicePort, @unchecked Sendable
{
    private let lock = NSLock()
    private var recordedSelections: [RecordedIntentSelection] = []
    private var recordedDocuments: [URL] = []
    private var recordedCommands: [SpeechCommand] = []

    var selections: [RecordedIntentSelection] {
        withLock { recordedSelections }
    }

    var documents: [URL] {
        withLock { recordedDocuments }
    }

    var commands: [SpeechCommand] {
        withLock { recordedCommands }
    }

    func enqueueSelection(_ text: String, source: String) throws {
        withLock {
            recordedSelections.append(RecordedIntentSelection(text: text, source: source))
        }
    }

    func enqueueDocument(at url: URL) throws {
        withLock { recordedDocuments.append(url) }
    }

    func perform(_ command: SpeechCommand) throws {
        withLock { recordedCommands.append(command) }
    }

    func purgeCachedAudio() throws -> CachePurgeReceipt {
        throw RecordingError.unexpectedCall
    }

    func snapshot() throws -> Snapshot { throw RecordingError.unexpectedCall }
    func submit(_ submission: SpeechSubmission) throws { throw RecordingError.unexpectedCall }

    func subscribe(shouldContinue: () -> Bool, onChange: () -> Void) throws {
        throw RecordingError.unexpectedCall
    }

    private func withLock<Result>(_ body: () -> Result) -> Result {
        lock.lock()
        defer { lock.unlock() }
        return body()
    }
}

private enum RecordingError: Error {
    case unexpectedCall
}
