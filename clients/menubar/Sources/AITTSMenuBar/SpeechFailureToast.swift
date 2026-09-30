// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import AppKit
import SwiftUI

struct SpeechFailureNotice: Identifiable, Equatable {
    let id: String
    let detail: String
}

/// A local non-activating toast works without notification authorization and
/// leaves a persistent error in the menu after the transient panel disappears.
@MainActor
final class SpeechFailureToastController {
    private let panel: NSPanel
    private let state: AppState
    private let openHistory: () -> Void
    private var dismissal: DispatchWorkItem?

    init(state: AppState, openHistory: @escaping () -> Void) {
        self.state = state
        self.openHistory = openHistory
        panel = NSPanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel],
                        backing: .buffered, defer: false)
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
    }

    func update(_ notice: SpeechFailureNotice?) {
        dismissal?.cancel()
        guard let notice else { panel.orderOut(nil); return }
        panel.contentViewController = NSHostingController(rootView: SpeechFailureToast(
            notice: notice,
            dismiss: { [weak self] in self?.state.dismissError() },
            openHistory: { [weak self] in
                self?.panel.orderOut(nil)
                self?.openHistory()
            }
        ))
        let visible = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 800, height: 600)
        panel.setFrame(NSRect(x: visible.maxX - 396, y: visible.maxY - 158,
                              width: 380, height: 142), display: true)
        NSApp.unhideWithoutActivation()
        panel.orderFrontRegardless()
        let hide = DispatchWorkItem { [weak self] in self?.panel.orderOut(nil) }
        dismissal = hide
        DispatchQueue.main.asyncAfter(deadline: .now() + 12, execute: hide)
    }
}

private struct SpeechFailureToast: View {
    let notice: SpeechFailureNotice
    let dismiss: () -> Void
    let openHistory: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("Speech failed", systemImage: "exclamationmark.triangle.fill")
                    .font(.headline)
                Spacer()
                Button(action: dismiss) { Image(systemName: "xmark") }
                    .buttonStyle(.borderless).help("Dismiss error")
            }
            Text(notice.detail).font(.caption).lineLimit(3)
            Button("View History", action: openHistory).buttonStyle(.borderless)
        }
        .padding(14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
}
