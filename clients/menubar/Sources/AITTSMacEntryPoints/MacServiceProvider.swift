// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import AITTSApplication
import AppKit
import Foundation

public enum MacServiceInputError: Error, Equatable, LocalizedError, Sendable {
    case noTextSelection
    case requiresSingleFile(actualCount: Int)

    public var errorDescription: String? {
        switch self {
        case .noTextSelection:
            "Select text before choosing Read Selection with AI-TTS."
        case .requiresSingleFile(actualCount: 0):
            "Select one plain-text, Markdown, or PDF file before choosing Read File with AI-TTS."
        case .requiresSingleFile:
            "Read File with AI-TTS accepts one file at a time."
        }
    }
}

public final class MacServiceProvider: NSObject {
    private let selectionEnqueuer: any SelectionEnqueueing
    private let documentEnqueuer: any DocumentEnqueueing

    public init(
        selectionEnqueuer: any SelectionEnqueueing,
        documentEnqueuer: any DocumentEnqueueing
    ) {
        self.selectionEnqueuer = selectionEnqueuer
        self.documentEnqueuer = documentEnqueuer
    }

    public func enqueueSelectedText(from pasteboard: NSPasteboard) throws {
        guard let selectedText = pasteboard.string(forType: .string) else {
            throw MacServiceInputError.noTextSelection
        }
        try selectionEnqueuer.enqueueSelection(
            selectedText,
            source: "macos-service:text"
        )
    }

    public func enqueueSelectedFile(from pasteboard: NSPasteboard) throws {
        let selectedURLs = (
            pasteboard.readObjects(
                forClasses: [NSURL.self],
                options: [.urlReadingFileURLsOnly: true]
            ) as? [NSURL] ?? []
        ).map { $0 as URL }
        guard selectedURLs.count == 1, let selectedURL = selectedURLs.first else {
            throw MacServiceInputError.requiresSingleFile(actualCount: selectedURLs.count)
        }
        try documentEnqueuer.enqueueDocument(at: selectedURL)
    }

    @objc(readSelection:userData:error:)
    public func readSelection(
        _ pasteboard: NSPasteboard,
        userData _: String?,
        error errorPointer: AutoreleasingUnsafeMutablePointer<NSString?>
    ) {
        performService(errorPointer) {
            try enqueueSelectedText(from: pasteboard)
        }
    }

    @objc(readFile:userData:error:)
    public func readFile(
        _ pasteboard: NSPasteboard,
        userData _: String?,
        error errorPointer: AutoreleasingUnsafeMutablePointer<NSString?>
    ) {
        performService(errorPointer) {
            try enqueueSelectedFile(from: pasteboard)
        }
    }

    private func performService(
        _ errorPointer: AutoreleasingUnsafeMutablePointer<NSString?>,
        operation: () throws -> Void
    ) {
        errorPointer.pointee = nil
        do {
            try operation()
        } catch {
            errorPointer.pointee = error.localizedDescription as NSString
        }
    }
}
