// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// The tray icon answers, without a click: is it doing anything, is sound
// about to come out, did something break (ui-design.md §6). State precedence:
// error > playing > paused > synthesizing > idle. Only working states animate.

import AppKit
import Combine
import SwiftUI

enum PopoverOpenSequence {
    static func capturePriorApplicationThenActivate(
        frontmostProcessIdentifier: () -> Int32?,
        ownProcessIdentifier: Int32,
        store: (Int32?) -> Void,
        activate: () -> Void
    ) {
        let frontmost = frontmostProcessIdentifier()
        let prior = frontmost == ownProcessIdentifier ? nil : frontmost

        store(prior)
        activate()
    }
}

@MainActor
final class StatusController: NSObject, NSPopoverDelegate {
    private let statusItem: NSStatusItem
    private let popover = NSPopover()
    private let state: AppState
    private let captionPanel: CaptionPanelController
    private var cancellables: Set<AnyCancellable> = []
    private var animationTimer: Timer?
    private var phase = 0
    private var trayState: TrayState = .error

    init(state: AppState) {
        self.state = state
        self.captionPanel = CaptionPanelController(state: state)
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
        applyState()
        state.$status
            .combineLatest(state.$reachable)
            .sink { [weak self] _, _ in
                Task { @MainActor in self?.applyState() }
            }
            .store(in: &cancellables)
        state.$status
            .sink { [weak self] _ in
                Task { @MainActor in self?.captionPanel.updateVisibility() }
            }
            .store(in: &cancellables)
        state.$captionsEnabled
            .sink { [weak self] _ in
                Task { @MainActor in self?.captionPanel.updateVisibility() }
            }
            .store(in: &cancellables)
    }

    private func applyState() {
        let newState = TrayState.from(
            reachable: state.reachable, daemonState: state.status?.playbackState)
        guard newState != trayState else { return }
        trayState = newState
        phase = 0
        render()
        animationTimer?.invalidate()
        animationTimer = nil
        if newState.animates {
            let timer = Timer(timeInterval: 0.4, repeats: true) { [weak self] _ in
                Task { @MainActor in self?.tick() }
            }
            RunLoop.main.add(timer, forMode: .common)
            animationTimer = timer
        }
    }

    private func tick() {
        phase = (phase + 1) % TrayIcon.phases
        render()
    }

    private func render() {
        statusItem.button?.image = TrayIcon.frame(state: trayState, phase: phase)
    }

    @objc private func togglePopover(_ sender: Any?) {
        if popover.isShown {
            popover.performClose(sender)
        } else if let button = statusItem.button {
            PopoverOpenSequence.capturePriorApplicationThenActivate(
                frontmostProcessIdentifier: {
                    NSWorkspace.shared.frontmostApplication?.processIdentifier
                },
                ownProcessIdentifier: ProcessInfo.processInfo.processIdentifier,
                store: { state.capturePriorApplication(processIdentifier: $0) },
                activate: {
                    state.startPolling(interval: 0.5)
                    popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
                    popover.contentViewController?.view.window?.makeKey()
                }
            )
        }
    }

    nonisolated func popoverDidClose(_ notification: Notification) {
        Task { @MainActor in
            self.state.startPolling(interval: self.state.backgroundPollingInterval)
        }
    }
}
