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
        AITTSAppIntentRuntime.register(
            AITTSAppIntentDependencies(
                selectionEnqueuer: selectionEnqueuer,
                documentEnqueuer: EnqueueDocument(
                    documents: documents,
                    speech: speech,
                    sourcePrefix: "macos-intent:file"
                ),
                speech: speech
            )
        )
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
            defaults: .standard,
            mediaDucking: MediaDuckingController(
                create: { pid in
                    guard #available(macOS 14.2, *) else {
                        throw AudioTapError.unavailable("Other-app ducking requires macOS 14.2 or later.")
                    }
                    return try OtherAudioTap(daemonPID: pid)
                },
                defaultOutput: {
                    guard #available(macOS 14.2, *) else { return 0 }
                    return try OtherAudioTap.defaultOutputDevice()
                }
            )
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

    func applicationWillTerminate(_ notification: Notification) {
        state.stopDucking()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApplication.shared.servicesProvider = serviceProvider
        statusController = StatusController(state: state)
        state.startPolling(interval: state.backgroundPollingInterval)
        state.startEventStream()
    }
}

MainActor.assumeIsolated {
    guard !MenuBarLaunchAgent().handOffIfInstalled() else { return }
    guard let instanceLock = SingleInstanceLock() else { return }
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    let delegate = AppDelegate()
    app.delegate = delegate
    // SIGTERM (installer retirement, launchctl bootout) quits normally, so
    // applicationWillTerminate restores ducked media.
    let terminationRouter = TerminationSignalRouter {
        MainActor.assumeIsolated { NSApplication.shared.terminate(nil) }
    }
    withExtendedLifetime((instanceLock, terminationRouter)) {
        app.run()
    }
}
