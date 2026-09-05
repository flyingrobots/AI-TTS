// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// Typed system-automation entry points. App Intents acquire parameters and
// delegate to existing application ports; they do not own speech policy.

import AITTSApplication
import AppIntents
import Foundation

struct AITTSAppIntentDependencies: Sendable {
    private let selectionEnqueuer: any SelectionEnqueueing
    private let documentEnqueuer: any DocumentEnqueueing
    private let speech: any SpeechServicePort

    init(
        selectionEnqueuer: any SelectionEnqueueing,
        documentEnqueuer: any DocumentEnqueueing,
        speech: any SpeechServicePort
    ) {
        self.selectionEnqueuer = selectionEnqueuer
        self.documentEnqueuer = documentEnqueuer
        self.speech = speech
    }

    func readText(_ text: String) throws {
        try selectionEnqueuer.enqueueSelection(text, source: "macos-intent:text")
    }

    func readFile(at url: URL) throws {
        try documentEnqueuer.enqueueDocument(at: url)
    }

    func perform(_ command: SpeechCommand) throws {
        try speech.perform(command)
    }
}

enum AITTSAppIntentRuntime {
    static func register(_ dependencies: AITTSAppIntentDependencies) {
        AppDependencyManager.shared.add(dependency: dependencies)
    }
}

enum AITTSAppIntentError: Error, Equatable, LocalizedError, Sendable {
    case fileUnavailable

    var errorDescription: String? {
        switch self {
        case .fileUnavailable:
            "The selected file is unavailable. Choose a local text, Markdown, or PDF file."
        }
    }
}

enum IntentPlaybackRate: Double, AppEnum, CaseIterable {
    case half = 0.5
    case threeQuarters = 0.75
    case normal = 1
    case oneAndAHalf = 1.5
    case double = 2
    case triple = 3

    static var typeDisplayRepresentation: TypeDisplayRepresentation = "Playback Speed"
    static var caseDisplayRepresentations: [IntentPlaybackRate: DisplayRepresentation] = [
        .half: "0.5×",
        .threeQuarters: "0.75×",
        .normal: "1×",
        .oneAndAHalf: "1.5×",
        .double: "2×",
        .triple: "3×",
    ]
}

struct ReadTextIntent: AppIntent {
    static let title: LocalizedStringResource = "Read Text"
    static let description = IntentDescription("Add literal text to the AI-TTS queue.")
    static let openAppWhenRun = false

    @Parameter(title: "Text")
    var text: String

    @AppDependency
    private var dependencies: AITTSAppIntentDependencies

    static var parameterSummary: some ParameterSummary {
        Summary("Read \(\.$text)")
    }

    func perform() async throws -> some IntentResult {
        try perform(using: dependencies)
        return .result()
    }

    func perform(using dependencies: AITTSAppIntentDependencies) throws {
        try dependencies.readText(text)
    }
}

struct ReadFileIntent: AppIntent {
    static let title: LocalizedStringResource = "Read File"
    static let description = IntentDescription(
        "Add one plain-text, Markdown, or text-bearing PDF file to the AI-TTS queue."
    )
    static let openAppWhenRun = false

    @Parameter(title: "File")
    var file: IntentFile

    @AppDependency
    private var dependencies: AITTSAppIntentDependencies

    static var parameterSummary: some ParameterSummary {
        Summary("Read \(\.$file)")
    }

    func perform() async throws -> some IntentResult {
        try perform(using: dependencies)
        return .result()
    }

    func perform(using dependencies: AITTSAppIntentDependencies) throws {
        try perform(fileURL: file.fileURL, using: dependencies)
    }

    func perform(
        fileURL: URL?,
        using dependencies: AITTSAppIntentDependencies
    ) throws {
        guard let url = fileURL else { throw AITTSAppIntentError.fileUnavailable }
        try dependencies.readFile(at: url)
    }
}

struct PauseSpeechIntent: AppIntent {
    static let title: LocalizedStringResource = "Pause"
    static let description = IntentDescription("Pause AI-TTS playback globally.")
    static let openAppWhenRun = false

    @AppDependency
    private var dependencies: AITTSAppIntentDependencies

    func perform() async throws -> some IntentResult {
        try perform(using: dependencies)
        return .result()
    }

    func perform(using dependencies: AITTSAppIntentDependencies) throws {
        try dependencies.perform(.pause)
    }
}

struct ResumeSpeechIntent: AppIntent {
    static let title: LocalizedStringResource = "Resume"
    static let description = IntentDescription("Resume AI-TTS playback globally.")
    static let openAppWhenRun = false

    @AppDependency
    private var dependencies: AITTSAppIntentDependencies

    func perform() async throws -> some IntentResult {
        try perform(using: dependencies)
        return .result()
    }

    func perform(using dependencies: AITTSAppIntentDependencies) throws {
        try dependencies.perform(.resume)
    }
}

struct SkipSpeechIntent: AppIntent {
    static let title: LocalizedStringResource = "Skip"
    static let description = IntentDescription("Skip the current AI-TTS utterance.")
    static let openAppWhenRun = false

    @AppDependency
    private var dependencies: AITTSAppIntentDependencies

    func perform() async throws -> some IntentResult {
        try perform(using: dependencies)
        return .result()
    }

    func perform(using dependencies: AITTSAppIntentDependencies) throws {
        try dependencies.perform(.skip)
    }
}

struct SetPlaybackSpeedIntent: AppIntent {
    static let title: LocalizedStringResource = "Set Playback Speed"
    static let description = IntentDescription(
        "Change AI-TTS playback speed without regenerating the current audio."
    )
    static let openAppWhenRun = false

    @Parameter(title: "Speed")
    var speed: IntentPlaybackRate

    @AppDependency
    private var dependencies: AITTSAppIntentDependencies

    static var parameterSummary: some ParameterSummary {
        Summary("Set playback speed to \(\.$speed)")
    }

    func perform() async throws -> some IntentResult {
        try perform(using: dependencies)
        return .result()
    }

    func perform(using dependencies: AITTSAppIntentDependencies) throws {
        try dependencies.perform(.setPlaybackRate(speed.rawValue))
    }
}

struct AITTSAppShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: ReadTextIntent(),
            phrases: ["Read text with \(.applicationName)"],
            shortTitle: "Read Text",
            systemImageName: "text.quote"
        )
        AppShortcut(
            intent: ReadFileIntent(),
            phrases: ["Read a file with \(.applicationName)"],
            shortTitle: "Read File",
            systemImageName: "doc.text"
        )
        AppShortcut(
            intent: PauseSpeechIntent(),
            phrases: ["Pause \(.applicationName)"],
            shortTitle: "Pause",
            systemImageName: "pause.fill"
        )
        AppShortcut(
            intent: ResumeSpeechIntent(),
            phrases: ["Resume \(.applicationName)"],
            shortTitle: "Resume",
            systemImageName: "play.fill"
        )
        AppShortcut(
            intent: SkipSpeechIntent(),
            phrases: ["Skip in \(.applicationName)"],
            shortTitle: "Skip",
            systemImageName: "forward.end.fill"
        )
        AppShortcut(
            intent: SetPlaybackSpeedIntent(),
            phrases: ["Set the speed in \(.applicationName)"],
            shortTitle: "Set Playback Speed",
            systemImageName: "speedometer"
        )
    }

    static let shortcutTileColor: ShortcutTileColor = .navy
}
