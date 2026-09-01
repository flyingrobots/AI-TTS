// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// Entry point: an accessory app (no Dock icon) that lives in the menu bar.

import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusController: StatusController?
    private let state = AppState()

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusController = StatusController(state: state)
        state.startPolling(interval: 5.0)
        state.startEventStream()
    }
}

MainActor.assumeIsolated {
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    let delegate = AppDelegate()
    app.delegate = delegate
    app.run()
}
