// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// One resizable window for reading a clip in full.
//
// Captions show a chunk at a time and the popover shows the first few lines,
// so a long submission had no surface that let the listener actually read it.
// This is that surface, and it is a window rather than a file handed to an
// editor on purpose: speech is confidential by default, and nothing here
// should write it somewhere the listener did not ask for.

import AITTSApplication
import AppKit
import SwiftUI

@MainActor
final class FullTextWindowController: NSObject, NSWindowDelegate {
    private let state: AppState
    private var window: NSWindow?

    init(state: AppState) {
        self.state = state
        super.init()
    }

    /// Show the window for whatever the listener asked to read, or hide it.
    func update() {
        guard let subject = state.readingFullText else {
            window?.orderOut(nil)
            return
        }
        let window = window ?? makeWindow()
        window.title = Self.title(for: subject)
        window.contentViewController = NSHostingController(
            rootView: FullTextView(subject: subject).environmentObject(state))
        // The listener asked to read something, so this window may take focus —
        // unlike the captions panel, which must never steal it.
        if !window.isVisible {
            window.center()
        }
        NSApplication.shared.unhide(nil)
        window.makeKeyAndOrderFront(nil)
    }

    /// Pure formatting, so it is testable without the main actor.
    nonisolated static func title(for subject: FullTextSubject) -> String {
        if let source = subject.source, !source.isEmpty {
            return "Full text — \(source)"
        }
        return "Full text"
    }

    private func makeWindow() -> NSWindow {
        let created = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 620, height: 520),
            styleMask: [.titled, .closable, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        created.isReleasedWhenClosed = false
        created.minSize = NSSize(width: 360, height: 240)
        created.delegate = self
        window = created
        return created
    }

    func windowWillClose(_ notification: Notification) {
        // Closing the window is the listener saying they are done reading.
        state.closeFullText()
    }
}

struct FullTextView: View {
    let subject: FullTextSubject
    @EnvironmentObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider()
            ScrollView {
                Text(subject.text)
                    .font(.system(size: 13))
                    .textSelection(.enabled)
                    .lineSpacing(3)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(14)
            }
            Divider()
            footer
        }
    }

    private var header: some View {
        HStack(spacing: 8) {
            Text(subject.isChunked ? "\(subject.segmentCount) chunks" : "One clip")
                .font(.caption2.smallCaps().weight(.semibold))
                .foregroundStyle(.secondary)
            Text(subject.voice)
                .font(.system(.caption2, design: .monospaced))
                .foregroundStyle(.tertiary)
            Spacer()
            Text("\(subject.text.count) characters")
                .font(.system(.caption2, design: .monospaced))
                .foregroundStyle(.tertiary)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 9)
    }

    private var footer: some View {
        HStack {
            if let spoken = subject.activeSegmentText, !spoken.isEmpty {
                Text("Speaking now: \(spoken)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            Spacer()
            Button("Copy") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(subject.text, forType: .string)
            }
            .controlSize(.small)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 9)
    }
}
