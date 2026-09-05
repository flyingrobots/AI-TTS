// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import Foundation
import PDFKit
import UniformTypeIdentifiers

struct ImportedSpeechFile {
    let filename: String
    let text: String

    var submissionPayload: [String: Any] {
        [
            "op": "submit",
            "text": text,
            "sensitivity": "confidential",
            "priority": "normal",
            "source": "menubar-file:\(filename)",
        ]
    }
}

enum SpeechFileImportError: LocalizedError, Equatable {
    case unsupportedFileType(String)
    case unreadableText(String)
    case unreadablePDF(String)
    case lockedPDF(String)
    case noSpeakableText(String)
    case noExtractablePDFText(String)

    var errorDescription: String? {
        switch self {
        case .unsupportedFileType(let filename):
            return "Choose a plain-text, Markdown, or PDF file. "
                + "\(filename) is not supported."
        case .unreadableText(let filename):
            return "\(filename) could not be read as UTF-8 text."
        case .unreadablePDF(let filename):
            return "\(filename) could not be opened as a PDF."
        case .lockedPDF(let filename):
            return "\(filename) is password-protected. Unlock it before enqueueing."
        case .noSpeakableText(let filename):
            return "\(filename) contains no speakable text."
        case .noExtractablePDFText(let filename):
            return "\(filename) has no extractable text. "
                + "Image-only PDFs need OCR, which AI-TTS does not perform."
        }
    }
}

enum SpeechFileImport {
    static let allowedContentTypes: [UTType] = [
        .plainText,
        UTType(filenameExtension: "md") ?? .plainText,
        UTType(filenameExtension: "markdown") ?? .plainText,
        .pdf,
    ]

    static func read(_ url: URL) throws -> ImportedSpeechFile {
        let filename = url.lastPathComponent
        let accessed = url.startAccessingSecurityScopedResource()
        defer {
            if accessed { url.stopAccessingSecurityScopedResource() }
        }

        switch fileKind(for: url) {
        case .text:
            return try readText(url, filename: filename)
        case .pdf:
            return try readPDF(url, filename: filename)
        case nil:
            throw SpeechFileImportError.unsupportedFileType(filename)
        }
    }

    private enum FileKind {
        case text
        case pdf
    }

    private static func fileKind(for url: URL) -> FileKind? {
        let pathExtension = url.pathExtension.lowercased()
        if pathExtension == "pdf" { return .pdf }
        if ["md", "markdown"].contains(pathExtension) { return .text }
        guard !pathExtension.isEmpty,
            let type = UTType(filenameExtension: pathExtension),
            type.conforms(to: .plainText)
        else { return nil }
        return .text
    }

    private static func readText(_ url: URL, filename: String) throws -> ImportedSpeechFile {
        let data: Data
        do {
            data = try Data(contentsOf: url, options: .mappedIfSafe)
        } catch {
            throw SpeechFileImportError.unreadableText(filename)
        }
        guard let text = String(data: data, encoding: .utf8) else {
            throw SpeechFileImportError.unreadableText(filename)
        }
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw SpeechFileImportError.noSpeakableText(filename)
        }
        return ImportedSpeechFile(filename: filename, text: text)
    }

    private static func readPDF(_ url: URL, filename: String) throws -> ImportedSpeechFile {
        guard let document = PDFDocument(url: url) else {
            throw SpeechFileImportError.unreadablePDF(filename)
        }
        guard !document.isLocked else {
            throw SpeechFileImportError.lockedPDF(filename)
        }
        let pages = (0..<document.pageCount).compactMap { index -> String? in
            let text = document.page(at: index)?.string?
                .trimmingCharacters(in: .whitespacesAndNewlines)
            return text?.isEmpty == false ? text : nil
        }
        guard !pages.isEmpty else {
            throw SpeechFileImportError.noExtractablePDFText(filename)
        }
        return ImportedSpeechFile(filename: filename, text: pages.joined(separator: "\n\n"))
    }
}
