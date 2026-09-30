// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import Foundation

public enum SpeechDraftError: Error, LocalizedError {
    case empty
    case tooLarge

    public var errorDescription: String? {
        switch self {
        case .empty: "Type, paste, or attach some text first."
        case .tooLarge: "Keep the combined text under 512 KiB."
        }
    }
}

/// Editable, in-memory source. Importing never submits or starts playback.
public struct SpeechDraft: Equatable, Sendable {
    public var text = ""
    public var voice: String?
    public var engine: String?
    public var contentFormat: SpeechContentFormat = .plainText
    public private(set) var origins: [String] = []

    public init() {}

    public mutating func append(_ imported: String, origin: String,
                                format: SpeechContentFormat) throws {
        let combined = text.isEmpty ? imported : text + "\n\n" + imported
        guard combined.utf8.count <= 512 * 1024 else { throw SpeechDraftError.tooLarge }
        text = combined
        origins.append(origin)
        if format == .markdown { contentFormat = .markdown }
    }

    /// Changing models releases a voice the new model cannot speak.
    public mutating func reconcileVoice(with catalog: [String]) {
        if let voice, !catalog.contains(voice) { self.voice = nil }
    }

    public func submission() throws -> SpeechSubmission {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw SpeechDraftError.empty
        }
        guard text.utf8.count <= 512 * 1024 else { throw SpeechDraftError.tooLarge }
        return SpeechSubmission(text: text, contentFormat: contentFormat,
                                voice: voice, speed: nil, sensitivity: .confidential,
                                priority: .normal,
                                source: "menubar-composer" + (origins.isEmpty ? "" : ":" + origins.joined(separator: "+")),
                                engine: engine)
    }
}
