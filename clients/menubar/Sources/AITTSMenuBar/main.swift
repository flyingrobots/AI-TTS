// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// Entry point: an accessory app (no Dock icon) that lives in the menu bar.

import AITTSApplication
import AITTSMacAdapters
import AITTSMacEntryPoints
import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusController: StatusController?
    private let state: AppState
    private let serviceProvider: MacServiceProvider

    override init() {
        let speech = UnixSocketSpeechService()
        let documents = LocalSpeechDocumentReader()
        let selectionEnqueuer = EnqueueSelection(speech: speech)
        state = AppState(
            speech: speech,
            documentEnqueuer: EnqueueDocument(
                documents: documents,
                speech: speech,
                sourcePrefix: "menubar-file"
            ),
            currentSelectionEnqueuer: EnqueueCurrentSelection(
                reader: AccessibilitySelectionReader(),
                selectionEnqueuer: selectionEnqueuer,
                source: "macos-accessibility:text"
            ),
            clipboardEnqueuer: EnqueueClipboard(
                reader: MacClipboardTextReader(),
                selectionEnqueuer: selectionEnqueuer,
                source: "macos-clipboard:text"
            ),
            defaults: .standard
        )
        serviceProvider = MacServiceProvider(
            selectionEnqueuer: selectionEnqueuer,
            documentEnqueuer: EnqueueDocument(
                documents: documents,
                speech: speech,
                sourcePrefix: "macos-service:file"
            )
        )
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApplication.shared.servicesProvider = serviceProvider
        statusController = StatusController(state: state)
        state.startPolling(interval: 5.0)
        state.startEventStream()
    }
}

MainActor.assumeIsolated {
    guard let instanceLock = SingleInstanceLock() else { return }
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    let delegate = AppDelegate()
    app.delegate = delegate
    withExtendedLifetime(instanceLock) {
        app.run()
    }
}
