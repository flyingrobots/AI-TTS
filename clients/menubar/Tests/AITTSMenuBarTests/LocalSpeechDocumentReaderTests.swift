// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned filesystem and macOS PDF text extraction)
// Test-Oracle: exact selected-file extraction and actionable local refusal contract

import AITTSApplication
import AppKit
import CoreText
import PDFKit
import XCTest

@testable import AITTSMacAdapters

final class LocalSpeechDocumentReaderTests: XCTestCase {
    private var directory: URL!

    override func setUpWithError() throws {
        executionTimeAllowance = 15
        directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(
                "ai-tts-file-import-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(
            at: directory, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: directory)
    }

    func testTextFileBecomesSpeechDocumentWithoutChangingContent() throws {
        let source = "  Exact plain text.\nSecond line.\n"
        let url = directory.appendingPathComponent("notes.txt")
        try Data(source.utf8).write(to: url)

        let document = try LocalSpeechDocumentReader().read(url)

        XCTAssertEqual(
            document,
            SpeechDocument(
                filename: "notes.txt",
                text: source,
                contentFormat: .plainText
            )
        )
    }

    func testMarkdownFileKeepsSyntaxForDaemonProjection() throws {
        let source = "# Revenue Review\n\nRead **SalesOS** next.\n"
        let url = directory.appendingPathComponent("history.md")
        try Data(source.utf8).write(to: url)

        let imported = try LocalSpeechDocumentReader().read(url)

        XCTAssertEqual(imported.filename, "history.md")
        XCTAssertEqual(imported.text, source)
        XCTAssertEqual(imported.contentFormat, .markdown)
    }

    func testTextBearingPDFBecomesPageOrderedTextSubmission() throws {
        let url = directory.appendingPathComponent("brief.pdf")
        try writeTextPDF(["First page.", "Second page."], to: url)

        let imported = try LocalSpeechDocumentReader().read(url)

        XCTAssertEqual(imported.filename, "brief.pdf")
        XCTAssertEqual(imported.text, "First page.\n\nSecond page.")
        XCTAssertEqual(imported.contentFormat, .plainText)
    }

    func testEmptyTextFileFailsWithActionableMessage() throws {
        let url = directory.appendingPathComponent("empty.txt")
        try Data(" \n\t".utf8).write(to: url)

        XCTAssertThrowsError(try LocalSpeechDocumentReader().read(url)) { error in
            XCTAssertEqual(
                error as? SpeechDocumentReadError, .noSpeakableText("empty.txt"))
            XCTAssertEqual(
                error.localizedDescription,
                "empty.txt contains no speakable text."
            )
        }
    }

    func testNonUTF8TextFileFailsWithEncodingGuidance() throws {
        let url = directory.appendingPathComponent("legacy.txt")
        try Data([0xFF, 0xFE, 0x41]).write(to: url)

        XCTAssertThrowsError(try LocalSpeechDocumentReader().read(url)) { error in
            XCTAssertEqual(
                error as? SpeechDocumentReadError, .unreadableText("legacy.txt"))
            XCTAssertEqual(
                error.localizedDescription,
                "legacy.txt could not be read as UTF-8 text."
            )
        }
    }

    func testImageOnlyPDFFailsWithExplicitOCRGuidance() throws {
        let url = directory.appendingPathComponent("scan.pdf")
        try writeImageOnlyPDF(to: url)

        XCTAssertThrowsError(try LocalSpeechDocumentReader().read(url)) { error in
            XCTAssertEqual(
                error as? SpeechDocumentReadError,
                .noExtractablePDFText("scan.pdf")
            )
            XCTAssertEqual(
                error.localizedDescription,
                "scan.pdf has no extractable text. "
                    + "Image-only PDFs need OCR, which AI-TTS does not perform."
            )
        }
    }

    func testPasswordLockedPDFFailsBeforeExtraction() throws {
        let url = directory.appendingPathComponent("locked.pdf")
        try writeLockedPDF(to: url)

        XCTAssertThrowsError(try LocalSpeechDocumentReader().read(url)) { error in
            XCTAssertEqual(error as? SpeechDocumentReadError, .lockedPDF("locked.pdf"))
            XCTAssertEqual(
                error.localizedDescription,
                "locked.pdf is password-protected. Unlock it before enqueueing."
            )
        }
    }

    func testUnsupportedFileTypeIsRejectedLocally() throws {
        let url = directory.appendingPathComponent("notes.rtf")
        try Data(#"{\rtf1 raw}"#.utf8).write(to: url)

        XCTAssertThrowsError(try LocalSpeechDocumentReader().read(url)) { error in
            XCTAssertEqual(
                error as? SpeechDocumentReadError,
                .unsupportedFileType("notes.rtf")
            )
            XCTAssertEqual(
                error.localizedDescription,
                "Choose a plain-text, Markdown, or PDF file. "
                    + "notes.rtf is not supported."
            )
        }
    }

    func testStandardLimitsMatchTheDocumentedV010Contract() {
        XCTAssertEqual(
            SpeechDocumentReadLimits.standard,
            SpeechDocumentReadLimits(
                maximumTextBytes: 512 * 1024,
                maximumPDFBytes: 32 * 1024 * 1024,
                maximumPDFPages: 500,
                maximumExtractedTextBytes: 512 * 1024
            )
        )
    }

    func testTextByteLimitIsInclusiveAndRejectsTheFirstExcessByte() throws {
        let acceptedURL = directory.appendingPathComponent("accepted.txt")
        try Data("12345678".utf8).write(to: acceptedURL)
        let rejectedURL = directory.appendingPathComponent("rejected.txt")
        try Data("123456789".utf8).write(to: rejectedURL)
        let reader = LocalSpeechDocumentReader(
            limits: SpeechDocumentReadLimits(
                maximumTextBytes: 8,
                maximumPDFBytes: 1024 * 1024,
                maximumPDFPages: 10,
                maximumExtractedTextBytes: 1024
            ))

        XCTAssertEqual(try reader.read(acceptedURL).text, "12345678")
        XCTAssertThrowsError(try reader.read(rejectedURL)) { error in
            XCTAssertEqual(
                error as? SpeechDocumentReadError,
                .fileTooLarge("rejected.txt", maximumBytes: 8)
            )
            XCTAssertEqual(
                error.localizedDescription,
                "rejected.txt is too large. Choose a file no larger than 8 bytes."
            )
        }
    }

    func testPDFSourceLimitWinsBeforeParsingAnOversizedMalformedFile() throws {
        let url = directory.appendingPathComponent("oversized.pdf")
        try Data(repeating: 0x41, count: 9).write(to: url)
        let reader = LocalSpeechDocumentReader(
            limits: SpeechDocumentReadLimits(
                maximumTextBytes: 1024,
                maximumPDFBytes: 8,
                maximumPDFPages: 10,
                maximumExtractedTextBytes: 1024
            ))

        XCTAssertThrowsError(try reader.read(url)) { error in
            XCTAssertEqual(
                error as? SpeechDocumentReadError,
                .fileTooLarge("oversized.pdf", maximumBytes: 8)
            )
        }
    }

    func testPDFPageLimitIsInclusiveAndRejectsTheNextPage() throws {
        let acceptedURL = directory.appendingPathComponent("accepted.pdf")
        try writeTextPDF(["First page.", "Second page."], to: acceptedURL)
        let rejectedURL = directory.appendingPathComponent("rejected.pdf")
        try writeTextPDF(["First page.", "Second page.", "Third page."], to: rejectedURL)
        let reader = LocalSpeechDocumentReader(
            limits: SpeechDocumentReadLimits(
                maximumTextBytes: 1024,
                maximumPDFBytes: 1024 * 1024,
                maximumPDFPages: 2,
                maximumExtractedTextBytes: 1024
            ))

        XCTAssertEqual(try reader.read(acceptedURL).text, "First page.\n\nSecond page.")
        XCTAssertThrowsError(try reader.read(rejectedURL)) { error in
            XCTAssertEqual(
                error as? SpeechDocumentReadError,
                .tooManyPDFPages("rejected.pdf", maximumPages: 2)
            )
            XCTAssertEqual(
                error.localizedDescription,
                "rejected.pdf has too many pages. PDFs are limited to 2 pages."
            )
        }
    }

    func testExtractedTextLimitIsInclusiveAndRejectsTheFirstExcessByte() throws {
        let acceptedURL = directory.appendingPathComponent("accepted-text.pdf")
        try writeTextPDF(["12345678"], to: acceptedURL)
        let rejectedURL = directory.appendingPathComponent("rejected-text.pdf")
        try writeTextPDF(["123456789"], to: rejectedURL)
        let reader = LocalSpeechDocumentReader(
            limits: SpeechDocumentReadLimits(
                maximumTextBytes: 1024,
                maximumPDFBytes: 1024 * 1024,
                maximumPDFPages: 10,
                maximumExtractedTextBytes: 8
            ))

        XCTAssertEqual(try reader.read(acceptedURL).text, "12345678")
        XCTAssertThrowsError(try reader.read(rejectedURL)) { error in
            XCTAssertEqual(
                error as? SpeechDocumentReadError,
                .extractedTextTooLarge("rejected-text.pdf", maximumBytes: 8)
            )
            XCTAssertEqual(
                error.localizedDescription,
                "rejected-text.pdf contains too much text. Extracted text is limited to 8 bytes."
            )
        }
    }

    private func writeTextPDF(_ pages: [String], to url: URL) throws {
        let data = NSMutableData()
        guard let consumer = CGDataConsumer(data: data as CFMutableData) else {
            return XCTFail("could not create the controlled PDF consumer")
        }
        var mediaBox = CGRect(x: 0, y: 0, width: 612, height: 792)
        guard let context = CGContext(consumer: consumer, mediaBox: &mediaBox, nil) else {
            return XCTFail("could not create the controlled PDF context")
        }
        for text in pages {
            context.beginPDFPage(nil)
            let attributed = NSAttributedString(
                string: text,
                attributes: [.font: NSFont.systemFont(ofSize: 14)]
            )
            let framesetter = CTFramesetterCreateWithAttributedString(attributed)
            let path = CGPath(
                rect: CGRect(x: 72, y: 72, width: 468, height: 648),
                transform: nil
            )
            let frame = CTFramesetterCreateFrame(
                framesetter,
                CFRange(location: 0, length: attributed.length),
                path,
                nil
            )
            CTFrameDraw(frame, context)
            context.endPDFPage()
        }
        context.closePDF()
        try (data as Data).write(to: url)
    }

    private func writeImageOnlyPDF(to url: URL) throws {
        let document = PDFDocument()
        let image = NSImage(size: NSSize(width: 20, height: 20))
        image.lockFocus()
        NSColor.black.setFill()
        NSBezierPath(rect: NSRect(x: 0, y: 0, width: 20, height: 20)).fill()
        image.unlockFocus()
        document.insert(try XCTUnwrap(PDFPage(image: image)), at: 0)
        XCTAssertTrue(document.write(to: url))
    }

    private func writeLockedPDF(to url: URL) throws {
        let document = PDFDocument()
        let image = NSImage(size: NSSize(width: 20, height: 20))
        image.lockFocus()
        NSColor.black.setFill()
        NSBezierPath(rect: NSRect(x: 0, y: 0, width: 20, height: 20)).fill()
        image.unlockFocus()
        document.insert(try XCTUnwrap(PDFPage(image: image)), at: 0)
        XCTAssertTrue(
            document.write(
                to: url,
                withOptions: [
                    .userPasswordOption: "secret",
                    .ownerPasswordOption: "owner",
                ]
            )
        )
    }
}
