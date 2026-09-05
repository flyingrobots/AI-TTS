// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (isolated pasteboards and owned Accessibility system fake)
// Test-Oracle: explicit macOS text readers preserve exact text, authority, and failure boundaries

import AppKit
import Foundation
import XCTest

@testable import AITTSMacEntryPoints

final class MacTextReadersTests: XCTestCase {
    override func setUp() {
        super.setUp()
        executionTimeAllowance = 15
    }

    func testAccessibilityReaderPromptsOnExplicitReadAndPreservesExactText() throws {
        let system = StubAccessibilitySystem(
            trusted: true,
            selection: .text("  # Exact selection\n")
        )
        let reader = AccessibilitySelectionReader(system: system)

        let selectedText = try reader.readSelectedText(from: 2718)

        XCTAssertEqual(selectedText, "  # Exact selection\n")
        XCTAssertEqual(system.trustPrompts, [true])
        XCTAssertEqual(system.requestedProcessIdentifiers, [2718])
    }

    func testAccessibilityReaderRefusesMissingPermissionBeforeReadingAnotherApp() {
        let system = StubAccessibilitySystem(
            trusted: false,
            selection: .text("must not be read")
        )
        let reader = AccessibilitySelectionReader(system: system)

        XCTAssertThrowsError(try reader.readSelectedText(from: 2718)) { error in
            XCTAssertEqual(error as? MacSelectedTextError, .permissionDenied)
        }
        XCTAssertEqual(system.trustPrompts, [true])
        XCTAssertEqual(system.requestedProcessIdentifiers, [])
    }

    func testAccessibilityReaderDistinguishesMissingFocusedElement() {
        let reader = AccessibilitySelectionReader(
            system: StubAccessibilitySystem(trusted: true, selection: .noFocusedElement)
        )

        XCTAssertThrowsError(try reader.readSelectedText(from: 2718)) { error in
            XCTAssertEqual(error as? MacSelectedTextError, .noFocusedElement)
        }
    }

    func testAccessibilityReaderDistinguishesUnsupportedSelection() {
        let reader = AccessibilitySelectionReader(
            system: StubAccessibilitySystem(trusted: true, selection: .unsupportedSelection)
        )

        XCTAssertThrowsError(try reader.readSelectedText(from: 2718)) { error in
            XCTAssertEqual(error as? MacSelectedTextError, .unsupportedSelection)
        }
    }

    func testAccessibilityReaderDistinguishesEmptySelection() {
        let reader = AccessibilitySelectionReader(
            system: StubAccessibilitySystem(trusted: true, selection: .text(" \n\t"))
        )

        XCTAssertThrowsError(try reader.readSelectedText(from: 2718)) { error in
            XCTAssertEqual(error as? MacSelectedTextError, .emptySelection)
        }
    }

    func testAccessibilityReaderPreservesSystemFailureCode() {
        let reader = AccessibilitySelectionReader(
            system: StubAccessibilitySystem(trusted: true, selection: .failure(code: -25204))
        )

        XCTAssertThrowsError(try reader.readSelectedText(from: 2718)) { error in
            XCTAssertEqual(error as? MacSelectedTextError, .systemFailure(code: -25204))
        }
    }

    func testClipboardReaderPreservesExactStringWithoutChangingPasteboard() throws {
        let pasteboard = makePasteboard()
        let exactText = "  # Clipboard literal\n"
        XCTAssertTrue(pasteboard.setString(exactText, forType: .string))
        let changeCountBeforeRead = pasteboard.changeCount
        let reader = MacClipboardTextReader(pasteboard: pasteboard)

        let selectedText = try reader.readClipboardText()

        XCTAssertEqual(selectedText, exactText)
        XCTAssertEqual(pasteboard.changeCount, changeCountBeforeRead)
    }

    func testClipboardReaderRefusesMissingTextWithoutChangingPasteboard() {
        let pasteboard = makePasteboard()
        let changeCountBeforeRead = pasteboard.changeCount
        let reader = MacClipboardTextReader(pasteboard: pasteboard)

        XCTAssertThrowsError(try reader.readClipboardText()) { error in
            XCTAssertEqual(error as? MacClipboardTextError, .noText)
        }
        XCTAssertEqual(pasteboard.changeCount, changeCountBeforeRead)
    }

    private func makePasteboard() -> NSPasteboard {
        let name = NSPasteboard.Name("ai-tts-text-reader-tests-\(UUID().uuidString)")
        let pasteboard = NSPasteboard(name: name)
        pasteboard.clearContents()
        return pasteboard
    }
}

private final class StubAccessibilitySystem: AccessibilitySystemAccess, @unchecked Sendable {
    private let trusted: Bool
    private let selection: AccessibilitySystemSelection
    private(set) var trustPrompts: [Bool] = []
    private(set) var requestedProcessIdentifiers: [Int32] = []

    init(trusted: Bool, selection: AccessibilitySystemSelection) {
        self.trusted = trusted
        self.selection = selection
    }

    func isTrusted(prompt: Bool) -> Bool {
        trustPrompts.append(prompt)
        return trusted
    }

    func selectedText(from processIdentifier: Int32) -> AccessibilitySystemSelection {
        requestedProcessIdentifiers.append(processIdentifier)
        return selection
    }
}
