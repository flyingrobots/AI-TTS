// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import AITTSApplication
import AppKit
import ApplicationServices
import Foundation

public enum MacSelectedTextError: Error, Equatable, LocalizedError, Sendable {
    case permissionDenied
    case noFocusedElement
    case unsupportedSelection
    case emptySelection
    case systemFailure(code: Int32)

    public var errorDescription: String? {
        switch self {
        case .permissionDenied:
            "Allow AI-TTS in System Settings → Privacy & Security → Accessibility, then try again."
        case .noFocusedElement:
            "The previous application has no focused element to read."
        case .unsupportedSelection:
            "The focused item does not expose selected text. Copy it and use Read Clipboard instead."
        case .emptySelection:
            "The focused item has no selected text."
        case .systemFailure(let code):
            "macOS could not read the selection (Accessibility error \(code))."
        }
    }
}

public enum MacClipboardTextError: Error, Equatable, LocalizedError, Sendable {
    case noText

    public var errorDescription: String? {
        switch self {
        case .noText:
            "The clipboard does not contain readable text."
        }
    }
}

enum AccessibilitySystemSelection: Equatable, Sendable {
    case text(String)
    case permissionDenied
    case noFocusedElement
    case unsupportedSelection
    case failure(code: Int32)
}

protocol AccessibilitySystemAccess: Sendable {
    func isTrusted(prompt: Bool) -> Bool
    func selectedText(from processIdentifier: Int32) -> AccessibilitySystemSelection
}

public struct AccessibilitySelectionReader: SelectedTextReaderPort, Sendable {
    private let system: any AccessibilitySystemAccess

    public init() {
        self.system = SystemAccessibilityAccess()
    }

    init(system: any AccessibilitySystemAccess) {
        self.system = system
    }

    public func readSelectedText(from processIdentifier: Int32) throws -> String {
        guard system.isTrusted(prompt: true) else {
            throw MacSelectedTextError.permissionDenied
        }
        switch system.selectedText(from: processIdentifier) {
        case .text(let text):
            guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw MacSelectedTextError.emptySelection
            }
            return text
        case .permissionDenied:
            throw MacSelectedTextError.permissionDenied
        case .noFocusedElement:
            throw MacSelectedTextError.noFocusedElement
        case .unsupportedSelection:
            throw MacSelectedTextError.unsupportedSelection
        case .failure(let code):
            throw MacSelectedTextError.systemFailure(code: code)
        }
    }
}

public final class MacClipboardTextReader: ClipboardTextReaderPort, @unchecked Sendable {
    private let pasteboard: NSPasteboard

    public convenience init() {
        self.init(pasteboard: .general)
    }

    init(pasteboard: NSPasteboard) {
        self.pasteboard = pasteboard
    }

    public func readClipboardText() throws -> String {
        guard let text = pasteboard.string(forType: .string) else {
            throw MacClipboardTextError.noText
        }
        return text
    }
}

private final class SystemAccessibilityAccess: AccessibilitySystemAccess, @unchecked Sendable {
    func isTrusted(prompt: Bool) -> Bool {
        let options = [
            kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: prompt
        ] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    }

    func selectedText(from processIdentifier: Int32) -> AccessibilitySystemSelection {
        let application = AXUIElementCreateApplication(pid_t(processIdentifier))
        var focusedValue: CFTypeRef?
        let focusedResult = AXUIElementCopyAttributeValue(
            application,
            kAXFocusedUIElementAttribute as CFString,
            &focusedValue
        )
        guard focusedResult == .success else {
            return focusedFailure(focusedResult)
        }
        guard
            let focusedValue,
            CFGetTypeID(focusedValue) == AXUIElementGetTypeID()
        else {
            return .noFocusedElement
        }
        let focusedElement = focusedValue as! AXUIElement
        var selectedValue: CFTypeRef?
        let selectedResult = AXUIElementCopyAttributeValue(
            focusedElement,
            kAXSelectedTextAttribute as CFString,
            &selectedValue
        )
        guard selectedResult == .success else {
            return selectionFailure(selectedResult)
        }
        guard let selectedText = selectedValue as? String else {
            return .unsupportedSelection
        }
        return .text(selectedText)
    }

    private func focusedFailure(_ error: AXError) -> AccessibilitySystemSelection {
        switch error {
        case .noValue:
            .noFocusedElement
        case .apiDisabled:
            .permissionDenied
        default:
            .failure(code: error.rawValue)
        }
    }

    private func selectionFailure(_ error: AXError) -> AccessibilitySystemSelection {
        switch error {
        case .attributeUnsupported, .notImplemented:
            .unsupportedSelection
        case .noValue:
            .text("")
        case .apiDisabled:
            .permissionDenied
        default:
            .failure(code: error.rawValue)
        }
    }
}
