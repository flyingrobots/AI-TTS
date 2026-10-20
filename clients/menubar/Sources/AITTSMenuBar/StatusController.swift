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
    private let popover: NSPopover
    private let sizing: PopoverSizing
    private let state: AppState
    private let captionPanel: CaptionPanelController
    private let fullTextWindow: FullTextWindowController
    private let selectionTracker: SpeechSelectionTracker
    private lazy var failureToast = SpeechFailureToastController(state: state) { [weak self] in
        guard let self else { return }
        self.state.revealHistory()
        if !self.popover.isShown { self.togglePopover(nil) }
    }
    private var cancellables: Set<AnyCancellable> = []
    private var animationTimer: Timer?
    private var phase = 0
    private var trayState: TrayState = .error

    init(state: AppState, defaults: UserDefaults = .standard,
         popover: NSPopover? = nil, statusItem: NSStatusItem? = nil,
         applicationNotifications: NotificationCenter? = nil) {
        self.popover = popover ?? NSPopover()
        self.sizing = PopoverSizing(defaults: defaults)
        self.selectionTracker = SpeechSelectionTracker(
            state: state, applicationNotifications: applicationNotifications)
        self.state = state
        self.captionPanel = CaptionPanelController(state: state)
        self.fullTextWindow = FullTextWindowController(state: state)
        self.statusItem = statusItem ?? NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        super.init()

        let popover = self.popover
        let statusItem = self.statusItem
        sizing.fit(to: sizing.maximumHeight)
        popover.contentSize = NSSize(width: 368, height: sizing.height)
        popover.behavior = .transient
        popover.delegate = self
        popover.contentViewController = NSHostingController(
            rootView: PopoverView(sizing: sizing).environmentObject(state))
        sizing.$height.sink { [weak self] height in
            self?.popover.contentSize = NSSize(width: 368, height: height)
        }.store(in: &cancellables)

        if let button = statusItem.button {
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
            button.action = #selector(statusButtonClicked(_:))
            button.target = self
        }
        render()
        applyState()
        state.$failureNotice
            .sink { [weak self] notice in
                Task { @MainActor in
                    self?.failureToast.update(notice)
                    self?.applyState()
                }
            }
            .store(in: &cancellables)
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
        state.$captionPosition
            .sink { [weak self] _ in
                Task { @MainActor in self?.captionPanel.updateVisibility() }
            }
            .store(in: &cancellables)
        state.$captionsEnabled
            .sink { [weak self] _ in
                Task { @MainActor in self?.captionPanel.updateVisibility() }
            }
            .store(in: &cancellables)
        state.$readingFullText
            .sink { [weak self] _ in
                Task { @MainActor in self?.fullTextWindow.update() }
            }
            .store(in: &cancellables)
    }

    private func applyState() {
        let newState: TrayState = state.failureNotice != nil ? .error : TrayState.from(
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
        statusItem.button?.setAccessibilityLabel(trayState.accessibilityLabel)
    }

    @objc private func statusButtonClicked(_ sender: Any?) {
        guard let event = NSApp.currentEvent else {
            togglePopover(sender)
            return
        }

        if event.type == .rightMouseUp || (event.type == .leftMouseUp && event.modifierFlags.contains(.control)) {
            showContextMenu()
        } else {
            togglePopover(sender)
        }
    }

    func buildContextMenu() -> NSMenu {
        let menu = NSMenu()
        menu.autoenablesItems = false
        let isPlaying = state.status?.playbackState == "playing"
        let hasCurrent = state.status?.current != nil
        let hasMultipleChunks = (state.status?.current?.segmentCount ?? 0) > 1

        let playPauseItem = NSMenuItem(
            title: isPlaying ? "Pause" : "Play",
            action: #selector(contextPlayPause),
            keyEquivalent: ""
        )
        playPauseItem.target = self
        playPauseItem.isEnabled = state.reachable
        menu.addItem(playPauseItem)

        let nextPartItem = NSMenuItem(
            title: "Next Part",
            action: #selector(contextNextPart),
            keyEquivalent: ""
        )
        nextPartItem.target = self
        nextPartItem.isEnabled = state.reachable && hasMultipleChunks
        menu.addItem(nextPartItem)

        let nextItem = NSMenuItem(
            title: "Next",
            action: #selector(contextNext),
            keyEquivalent: ""
        )
        nextItem.target = self
        nextItem.isEnabled = state.reachable && hasCurrent
        menu.addItem(nextItem)

        let clearItem = NSMenuItem(
            title: "Clear",
            action: #selector(contextClear),
            keyEquivalent: ""
        )
        clearItem.target = self
        clearItem.isEnabled = state.reachable
        menu.addItem(clearItem)

        menu.addItem(NSMenuItem.separator())

        let quitItem = NSMenuItem(
            title: "Quit",
            action: #selector(contextQuit),
            keyEquivalent: "q"
        )
        quitItem.target = self
        menu.addItem(quitItem)

        return menu
    }

    private func showContextMenu() {
        if popover.isShown {
            popover.performClose(nil)
        }
        guard let button = statusItem.button else { return }
        let menu = buildContextMenu()
        menu.popUp(positioning: nil, at: NSPoint(x: 0, y: button.bounds.height), in: button)
    }

    @objc func contextPlayPause() {
        if state.status?.playbackState == "playing" {
            state.pause()
        } else {
            state.resume()
        }
    }

    @objc func contextNextPart() {
        state.nextChunk()
    }

    @objc func contextNext() {
        state.skip()
    }

    @objc func contextClear() {
        state.clearQueue()
        if state.status?.current != nil {
            state.skip()
        }
    }

    @objc func contextQuit() {
        NSApplication.shared.terminate(nil)
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
                    sizing.fit(to: max(200, (button.window?.screen?.visibleFrame.height ?? 800) - 32))
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
