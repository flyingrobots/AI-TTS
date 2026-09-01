// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// The tray icon answers, without a click: is it doing anything, is sound
// about to come out, did something break (ui-design.md §6). State precedence:
// error > playing > paused > synthesizing > idle.

import AppKit
import Combine
import SwiftUI

@MainActor
final class StatusController: NSObject, NSPopoverDelegate {
    private let statusItem: NSStatusItem
    private let popover = NSPopover()
    private let state: AppState
    private var cancellable: AnyCancellable?

    init(state: AppState) {
        self.state = state
        self.statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        super.init()

        popover.contentSize = NSSize(width: 360, height: 480)
        popover.behavior = .transient
        popover.delegate = self
        popover.contentViewController = NSHostingController(
            rootView: PopoverView().environmentObject(state))

        if let button = statusItem.button {
            button.action = #selector(togglePopover(_:))
            button.target = self
        }
        updateIcon()
        cancellable = state.$status.sink { [weak self] _ in
            Task { @MainActor in self?.updateIcon() }
        }
    }

    private func updateIcon() {
        // SF Symbols stand in for the custom template icon in the mockups;
        // one silhouette family, distinct interiors, template-rendered.
        let symbol = Self.symbolName(reachable: state.reachable, state: state.status?.state)
        let image = NSImage(
            systemSymbolName: symbol, accessibilityDescription: "AI-TTS \(symbol)")
        image?.isTemplate = true
        statusItem.button?.image = image
    }

    nonisolated static func symbolName(reachable: Bool, state: String?) -> String {
        guard reachable, let state else { return "exclamationmark.bubble" }
        switch state {
        case "playing": return "waveform"
        case "paused": return "pause.circle"
        case "synthesizing": return "ellipsis.bubble"
        default: return "bubble.left"
        }
    }

    @objc private func togglePopover(_ sender: Any?) {
        if popover.isShown {
            popover.performClose(sender)
        } else if let button = statusItem.button {
            state.startPolling(interval: 0.5)
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
        }
    }

    nonisolated func popoverDidClose(_ notification: Notification) {
        Task { @MainActor in self.state.startPolling(interval: 2.0) }
    }
}
