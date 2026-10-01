// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import SwiftUI

/// Runs delayed card work on the UI actor; the returned closure cancels it.
@MainActor
protocol ProvenanceCardScheduling {
    func schedule(after delay: Duration,
                  _ action: @escaping @MainActor () -> Void) -> @MainActor () -> Void
}

/// Production scheduling backed by a cancellable task.
struct TaskProvenanceCardScheduler: ProvenanceCardScheduling {
    nonisolated init() {}

    func schedule(after delay: Duration,
                  _ action: @escaping @MainActor () -> Void) -> @MainActor () -> Void {
        let task = Task { @MainActor in
            do { try await Task.sleep(for: delay) } catch { return }
            guard !Task.isCancelled else { return }
            action()
        }
        return { task.cancel() }
    }
}

/// Decides when one History row's provenance card is shown.
///
/// Resting on the trigger or activating it opens the card. Leaving the trigger
/// or the card dismisses it after a grace period, so the pointer can cross
/// the gap between them. `open` runs exactly when the card goes from hidden
/// to shown; the row uses it to request fresh details.
@MainActor
final class ProvenanceCardPresenter: ObservableObject {
    static let dismissalGrace: Duration = .milliseconds(250)
    static let hoverIntentDelay: Duration = .milliseconds(400)

    @Published private(set) var isPresented = false

    private let scheduler: any ProvenanceCardScheduling
    private var cancelPending: (@MainActor () -> Void)?
    // Scheduled work runs only if nothing was cancelled or rescheduled since,
    // because a timer can finish sleeping before its cancellation is observed.
    private var pendingGeneration = 0
    // The trigger and the card are separate windows, so one region's enter can
    // arrive before the other's exit. Dismissal depends on both, not the last event.
    private var triggerHovered = false
    private var cardHovered = false

    init(scheduler: any ProvenanceCardScheduling = TaskProvenanceCardScheduler()) {
        self.scheduler = scheduler
    }

    /// A popover binding: the system closing the popover closes the card.
    var presentation: Binding<Bool> {
        Binding(get: { self.isPresented }, set: { shown in if !shown { self.close() } })
    }

    /// The labeled trigger was activated by click, keyboard, or accessibility.
    func activate(open: () -> Void) {
        if isPresented {
            close()
        } else {
            present(open)
        }
    }

    /// Hovering opens only after the pointer rests on the trigger, so sweeping
    /// across History neither flashes cards nor sends a daemon request per row.
    func triggerHover(_ hovering: Bool, open: @escaping () -> Void) {
        triggerHovered = hovering
        if hovering {
            cancelPendingWork()
            guard !isPresented else { return }
            schedule(after: Self.hoverIntentDelay) { [weak self] in self?.present(open) }
        } else {
            scheduleDismissal()
        }
    }

    func cardHover(_ hovering: Bool) {
        cardHovered = hovering
        if hovering {
            cancelPendingWork()
        } else {
            scheduleDismissal()
        }
    }

    /// Close now and forget any pending work, e.g. the close button or row removal.
    func close() {
        cancelPendingWork()
        // A closed card's window is gone, so its exit event may never arrive.
        cardHovered = false
        isPresented = false
    }

    private func present(_ open: () -> Void) {
        cancelPendingWork()
        guard !isPresented else { return }
        open()
        isPresented = true
    }

    private func scheduleDismissal() {
        cancelPendingWork()
        guard isPresented, !triggerHovered, !cardHovered else { return }
        schedule(after: Self.dismissalGrace) { [weak self] in
            guard let self, !self.triggerHovered, !self.cardHovered else { return }
            self.isPresented = false
        }
    }

    private func schedule(after delay: Duration, _ action: @escaping @MainActor () -> Void) {
        let generation = pendingGeneration
        cancelPending = scheduler.schedule(after: delay) { [weak self] in
            guard let self, self.pendingGeneration == generation else { return }
            self.cancelPending = nil
            action()
        }
    }

    private func cancelPendingWork() {
        pendingGeneration &+= 1
        cancelPending?()
        cancelPending = nil
    }
}
