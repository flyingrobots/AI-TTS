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

public enum SpeechContentFormat: String, Equatable, Sendable {
    case plainText = "plain_text"
    case markdown
}

public enum SpeechServiceError: Error, Equatable, Sendable {
    case rejected(type: String, message: String)
    case invalidResponse
    case unavailable
}

public enum SpeechSelectionError: Error, Equatable, LocalizedError, Sendable {
    case noSpeakableText

    public var errorDescription: String? {
        switch self {
        case .noSpeakableText:
            "The selection contains no speakable text."
        }
    }
}

public enum CurrentSelectionError: Error, Equatable, LocalizedError, Sendable {
    case noPriorApplication

    public var errorDescription: String? {
        switch self {
        case .noPriorApplication:
            "Open AI-TTS from the menu bar while another application has a selection."
        }
    }
}

public struct SpeechSubmission: Equatable, Sendable {
    public let text: String
    public let contentFormat: SpeechContentFormat
    public let voice: String?
    public let speed: Double?
    public let sensitivity: SpeechSensitivity
    public let priority: RequeuePriority
    public let source: String?

    public init(
        text: String,
        contentFormat: SpeechContentFormat,
        voice: String?,
        speed: Double?,
        sensitivity: SpeechSensitivity,
        priority: RequeuePriority,
        source: String?
    ) {
        self.text = text
        self.contentFormat = contentFormat
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
    public let contentFormat: SpeechContentFormat

    public init(filename: String, text: String, contentFormat: SpeechContentFormat) {
        self.filename = filename
        self.text = text
        self.contentFormat = contentFormat
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
    case setCaptionsEnabled(Bool)
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

/// Inbound application port shared by native selected-text adapters.
public protocol SelectionEnqueueing: Sendable {
    func enqueueSelection(_ text: String, source: String) throws
}

/// Outbound port for reading one explicit selection from a known application.
public protocol SelectedTextReaderPort: Sendable {
    func readSelectedText(from processIdentifier: Int32) throws -> String
}

/// Outbound port for reading the clipboard's current string representation.
public protocol ClipboardTextReaderPort: Sendable {
    func readClipboardText() throws -> String
}

/// Inbound application port for the explicit current-selection action.
public protocol CurrentSelectionEnqueueing: Sendable {
    func enqueueCurrentSelection(from processIdentifier: Int32?) throws
}

/// Inbound application port for the explicit clipboard fallback.
public protocol ClipboardEnqueueing: Sendable {
    func enqueueClipboard() throws
}

public struct EnqueueSelection: SelectionEnqueueing, Sendable {
    private let speech: any SpeechServicePort

    public init(speech: any SpeechServicePort) {
        self.speech = speech
    }

    public func enqueueSelection(_ text: String, source: String) throws {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw SpeechSelectionError.noSpeakableText
        }
        try speech.submit(
            SpeechSubmission(
                text: text,
                contentFormat: .plainText,
                voice: nil,
                speed: nil,
                sensitivity: .confidential,
                priority: .normal,
                source: source
            )
        )
    }
}

public struct EnqueueCurrentSelection: CurrentSelectionEnqueueing, Sendable {
    private let reader: any SelectedTextReaderPort
    private let selectionEnqueuer: any SelectionEnqueueing
    private let source: String

    public init(
        reader: any SelectedTextReaderPort,
        selectionEnqueuer: any SelectionEnqueueing,
        source: String
    ) {
        self.reader = reader
        self.selectionEnqueuer = selectionEnqueuer
        self.source = source
    }

    public func enqueueCurrentSelection(from processIdentifier: Int32?) throws {
        guard let processIdentifier else {
            throw CurrentSelectionError.noPriorApplication
        }
        let selectedText = try reader.readSelectedText(from: processIdentifier)
        try selectionEnqueuer.enqueueSelection(selectedText, source: source)
    }
}

public struct EnqueueClipboard: ClipboardEnqueueing, Sendable {
    private let reader: any ClipboardTextReaderPort
    private let selectionEnqueuer: any SelectionEnqueueing
    private let source: String

    public init(
        reader: any ClipboardTextReaderPort,
        selectionEnqueuer: any SelectionEnqueueing,
        source: String
    ) {
        self.reader = reader
        self.selectionEnqueuer = selectionEnqueuer
        self.source = source
    }

    public func enqueueClipboard() throws {
        let selectedText = try reader.readClipboardText()
        try selectionEnqueuer.enqueueSelection(selectedText, source: source)
    }
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
                contentFormat: document.contentFormat,
                voice: nil,
                speed: nil,
                sensitivity: .confidential,
                priority: .normal,
                source: "\(sourcePrefix):\(document.filename)"
            )
        )
    }
}
