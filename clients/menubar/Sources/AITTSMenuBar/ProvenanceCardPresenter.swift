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
            action()
        }
        return { task.cancel() }
    }
}

/// Decides when one History row's provenance card is shown.
///
/// Hovering the trigger or activating it opens the card. Leaving the trigger
/// or the card dismisses it after a grace period, so the pointer can cross
/// the gap between them. `open` runs exactly when the card goes from hidden
/// to shown; the row uses it to request fresh details.
@MainActor
final class ProvenanceCardPresenter: ObservableObject {
    static let dismissalGrace: Duration = .milliseconds(250)

    @Published private(set) var isPresented = false

    private let scheduler: any ProvenanceCardScheduling
    private var cancelPending: (@MainActor () -> Void)?

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

    func triggerHover(_ hovering: Bool, open: () -> Void) {
        if hovering {
            present(open)
        } else {
            scheduleDismissal()
        }
    }

    func cardHover(_ hovering: Bool) {
        if hovering {
            cancelPendingWork()
        } else {
            scheduleDismissal()
        }
    }

    /// Close now and forget any pending work, e.g. the close button or row removal.
    func close() {
        cancelPendingWork()
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
        cancelPending = scheduler.schedule(after: Self.dismissalGrace) { [weak self] in
            self?.cancelPending = nil
            self?.isPresented = false
        }
    }

    private func cancelPendingWork() {
        cancelPending?()
        cancelPending = nil
    }
}
