// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import Foundation

public enum RequeuePriority: String, CaseIterable, Equatable, Sendable {
    case normal
    case urgent
}

public enum SpeechSensitivity: String, Equatable, Sendable {
    case `public`
    case `internal`
    case confidential
}

public enum SpeechServiceError: Error, Equatable, Sendable {
    case rejected(type: String, message: String)
    case invalidResponse
    case unavailable
}

public struct SpeechSubmission: Equatable, Sendable {
    public let text: String
    public let voice: String?
    public let speed: Double?
    public let sensitivity: SpeechSensitivity
    public let priority: RequeuePriority
    public let source: String?

    public init(
        text: String,
        voice: String?,
        speed: Double?,
        sensitivity: SpeechSensitivity,
        priority: RequeuePriority,
        source: String?
    ) {
        self.text = text
        self.voice = voice
        self.speed = speed
        self.sensitivity = sensitivity
        self.priority = priority
        self.source = source
    }
}

public struct SpeechDocument: Equatable, Sendable {
    public let filename: String
    public let text: String

    public init(filename: String, text: String) {
        self.filename = filename
        self.text = text
    }
}

public enum SpeechCommand: Equatable, Sendable {
    case pause
    case resume
    case skip
    case rewind(to: String?)
    case cancel(id: String)
    case clearQueue
    case clearHistory
    case removeHistory(id: String)
    case requeue(id: String, priority: RequeuePriority)
    case reorder(ids: [String])
    case setVoice(String)
    case setSynthesisSpeed(Double)
    case setPlaybackRate(Double)
}

/// Outbound port for every speech capability used by a native macOS client.
public protocol SpeechServicePort: Sendable {
    func snapshot() throws -> Snapshot
    func submit(_ submission: SpeechSubmission) throws
    func perform(_ command: SpeechCommand) throws
    func subscribe(shouldContinue: () -> Bool, onChange: () -> Void) throws
}

/// Outbound port for projecting a user-selected URL into speakable source text.
public protocol SpeechDocumentReaderPort: Sendable {
    func read(_ url: URL) throws -> SpeechDocument
}

/// Inbound application port shared by menu, Finder, Services, and Shortcuts adapters.
public protocol DocumentEnqueueing: Sendable {
    func enqueueDocument(at url: URL) throws
}

public struct EnqueueDocument: DocumentEnqueueing, Sendable {
    private let documents: any SpeechDocumentReaderPort
    private let speech: any SpeechServicePort
    private let sourcePrefix: String

    public init(
        documents: any SpeechDocumentReaderPort,
        speech: any SpeechServicePort,
        sourcePrefix: String
    ) {
        self.documents = documents
        self.speech = speech
        self.sourcePrefix = sourcePrefix
    }

    public func enqueueDocument(at url: URL) throws {
        let document = try documents.read(url)
        try speech.submit(
            SpeechSubmission(
                text: document.text,
                voice: nil,
                speed: nil,
                sensitivity: .confidential,
                priority: .normal,
                source: "\(sourcePrefix):\(document.filename)"
            )
        )
    }
}
