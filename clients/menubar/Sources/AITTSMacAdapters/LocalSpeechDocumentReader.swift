// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import AITTSApplication
import Foundation
import PDFKit
import UniformTypeIdentifiers

public enum SpeechDocumentReadError: LocalizedError, Equatable {
    case unsupportedFileType(String)
    case unreadableText(String)
    case unreadablePDF(String)
    case lockedPDF(String)
    case noSpeakableText(String)
    case noExtractablePDFText(String)
    case fileTooLarge(String, maximumBytes: Int)
    case tooManyPDFPages(String, maximumPages: Int)
    case extractedTextTooLarge(String, maximumBytes: Int)

    public var errorDescription: String? {
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
        case .fileTooLarge(let filename, let maximumBytes):
            return "\(filename) is too large. Choose a file no larger than "
                + "\(Self.describe(byteLimit: maximumBytes))."
        case .tooManyPDFPages(let filename, let maximumPages):
            return "\(filename) has too many pages. PDFs are limited to \(maximumPages) pages."
        case .extractedTextTooLarge(let filename, let maximumBytes):
            return "\(filename) contains too much text. Extracted text is limited to "
                + "\(Self.describe(byteLimit: maximumBytes))."
        }
    }

    private static func describe(byteLimit: Int) -> String {
        if byteLimit.isMultiple(of: 1024 * 1024) {
            return "\(byteLimit / (1024 * 1024)) MiB"
        }
        if byteLimit.isMultiple(of: 1024) {
            return "\(byteLimit / 1024) KiB"
        }
        return "\(byteLimit) bytes"
    }
}

struct SpeechDocumentReadLimits: Equatable, Sendable {
    static let standard = Self(
        maximumTextBytes: 512 * 1024,
        maximumPDFBytes: 32 * 1024 * 1024,
        maximumPDFPages: 500,
        maximumExtractedTextBytes: 512 * 1024
    )

    let maximumTextBytes: Int
    let maximumPDFBytes: Int
    let maximumPDFPages: Int
    let maximumExtractedTextBytes: Int
}

/// Outbound adapter from the document-reader port to user-selected local files.
public struct LocalSpeechDocumentReader: SpeechDocumentReaderPort, Sendable {
    public static let allowedContentTypes: [UTType] = [
        .plainText,
        UTType(filenameExtension: "md") ?? .plainText,
        UTType(filenameExtension: "markdown") ?? .plainText,
        .pdf,
    ]

    private let limits: SpeechDocumentReadLimits

    public init() {
        limits = .standard
    }

    init(limits: SpeechDocumentReadLimits) {
        self.limits = limits
    }

    public func read(_ url: URL) throws -> SpeechDocument {
        let filename = url.lastPathComponent
        let accessed = url.startAccessingSecurityScopedResource()
        defer {
            if accessed { url.stopAccessingSecurityScopedResource() }
        }

        switch fileKind(for: url) {
        case .plainText:
            return try readText(url, filename: filename, contentFormat: .plainText)
        case .markdown:
            return try readText(url, filename: filename, contentFormat: .markdown)
        case .pdf:
            return try readPDF(url, filename: filename)
        case nil:
            throw SpeechDocumentReadError.unsupportedFileType(filename)
        }
    }

    private enum FileKind {
        case plainText
        case markdown
        case pdf
    }

    private func fileKind(for url: URL) -> FileKind? {
        let pathExtension = url.pathExtension.lowercased()
        if pathExtension == "pdf" { return .pdf }
        if ["md", "markdown"].contains(pathExtension) { return .markdown }
        guard !pathExtension.isEmpty,
            let type = UTType(filenameExtension: pathExtension),
            type.conforms(to: .plainText)
        else { return nil }
        return .plainText
    }

    private func readText(
        _ url: URL,
        filename: String,
        contentFormat: SpeechContentFormat
    ) throws -> SpeechDocument {
        let data = try readData(
            url,
            filename: filename,
            maximumBytes: limits.maximumTextBytes,
            unreadable: .unreadableText(filename)
        )
        guard let text = String(data: data, encoding: .utf8) else {
            throw SpeechDocumentReadError.unreadableText(filename)
        }
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw SpeechDocumentReadError.noSpeakableText(filename)
        }
        return SpeechDocument(filename: filename, text: text, contentFormat: contentFormat)
    }

    private func readPDF(_ url: URL, filename: String) throws -> SpeechDocument {
        let data = try readData(
            url,
            filename: filename,
            maximumBytes: limits.maximumPDFBytes,
            unreadable: .unreadablePDF(filename)
        )
        guard let document = PDFDocument(data: data) else {
            throw SpeechDocumentReadError.unreadablePDF(filename)
        }
        guard !document.isLocked else {
            throw SpeechDocumentReadError.lockedPDF(filename)
        }
        guard document.pageCount <= limits.maximumPDFPages else {
            throw SpeechDocumentReadError.tooManyPDFPages(
                filename,
                maximumPages: limits.maximumPDFPages
            )
        }
        var pages: [String] = []
        var extractedBytes = 0
        for index in 0..<document.pageCount {
            guard
                let text = document.page(at: index)?.string?
                    .trimmingCharacters(in: .whitespacesAndNewlines),
                !text.isEmpty
            else { continue }
            let requiredBytes = text.utf8.count + (pages.isEmpty ? 0 : 2)
            guard requiredBytes <= limits.maximumExtractedTextBytes - extractedBytes else {
                throw SpeechDocumentReadError.extractedTextTooLarge(
                    filename,
                    maximumBytes: limits.maximumExtractedTextBytes
                )
            }
            pages.append(text)
            extractedBytes += requiredBytes
        }
        guard !pages.isEmpty else {
            throw SpeechDocumentReadError.noExtractablePDFText(filename)
        }
        return SpeechDocument(
            filename: filename,
            text: pages.joined(separator: "\n\n"),
            contentFormat: .plainText
        )
    }

    private func readData(
        _ url: URL,
        filename: String,
        maximumBytes: Int,
        unreadable: SpeechDocumentReadError
    ) throws -> Data {
        let handle: FileHandle
        do {
            handle = try FileHandle(forReadingFrom: url)
        } catch {
            throw unreadable
        }
        defer { try? handle.close() }

        var data = Data()
        do {
            while data.count <= maximumBytes {
                let remaining = maximumBytes - data.count + 1
                guard
                    let chunk = try handle.read(upToCount: min(64 * 1024, remaining)),
                    !chunk.isEmpty
                else { break }
                data.append(chunk)
            }
        } catch {
            throw unreadable
        }
        guard data.count <= maximumBytes else {
            throw SpeechDocumentReadError.fileTooLarge(filename, maximumBytes: maximumBytes)
        }
        return data
    }
}
