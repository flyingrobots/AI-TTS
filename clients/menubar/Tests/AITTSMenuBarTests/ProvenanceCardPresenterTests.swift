// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (menu presentation model with a manual scheduler under XCTest)
// Test-Oracle: ui-design History provenance card: activation toggles, dismissal waits a grace period, the card holds itself open

import XCTest

@testable import AITTSMenuBar

final class ProvenanceCardPresenterTests: XCTestCase {
    override func setUp() {
        super.setUp()
        executionTimeAllowance = 15
    }

    @MainActor
    func testActivationOpensOnceAndTogglesClosed() {
        let scheduler = ManualCardScheduler()
        let card = ProvenanceCardPresenter(scheduler: scheduler)
        var loads = 0

        card.activate { loads += 1 }
        XCTAssertTrue(card.isPresented)
        XCTAssertEqual(loads, 1, "Opening must request this clip's details exactly once")

        card.activate { loads += 1 }
        XCTAssertFalse(card.isPresented, "Activating an open card closes it")
        XCTAssertEqual(loads, 1, "Closing must not request details")
    }

    @MainActor
    func testLeavingTheTriggerDismissesOnlyAfterTheGracePeriod() {
        let scheduler = ManualCardScheduler()
        let card = ProvenanceCardPresenter(scheduler: scheduler)
        card.activate {}

        card.triggerHover(false) {}
        XCTAssertTrue(card.isPresented, "Leaving must not close the card immediately")
        XCTAssertEqual(scheduler.pendingDelays, [ProvenanceCardPresenter.dismissalGrace])

        scheduler.firePending()
        XCTAssertFalse(card.isPresented)
    }

    @MainActor
    func testEnteringTheCardCancelsAPendingDismissal() {
        let scheduler = ManualCardScheduler()
        let card = ProvenanceCardPresenter(scheduler: scheduler)
        card.activate {}

        card.triggerHover(false) {}
        card.cardHover(true)
        XCTAssertEqual(scheduler.pendingDelays, [])
        scheduler.firePending()
        XCTAssertTrue(card.isPresented, "The pointer inside the card keeps it open")

        card.cardHover(false)
        scheduler.firePending()
        XCTAssertFalse(card.isPresented, "Leaving the card dismisses it after the grace period")
    }

    @MainActor
    func testDismissalFollowsWhereThePointerIsNotTheLastEventDelivered() {
        let scheduler = ManualCardScheduler()
        let card = ProvenanceCardPresenter(scheduler: scheduler)
        card.activate {}
        card.triggerHover(true) {}

        // The trigger and the card are separate windows; enter may precede the matching exit.
        card.cardHover(true)
        card.triggerHover(false) {}
        scheduler.firePending()
        XCTAssertTrue(card.isPresented, "The pointer is inside the card")

        card.triggerHover(true) {}
        card.cardHover(false)
        scheduler.firePending()
        XCTAssertTrue(card.isPresented, "The pointer is back on the trigger")

        card.triggerHover(false) {}
        scheduler.firePending()
        XCTAssertFalse(card.isPresented, "The pointer left both regions")
    }

    @MainActor
    func testCancelledWorkThatWakesLateHasNoEffect() {
        let scheduler = ManualCardScheduler()
        let card = ProvenanceCardPresenter(scheduler: scheduler)
        var loads = 0

        card.triggerHover(true) { loads += 1 }
        card.triggerHover(false) { loads += 1 }
        // A timer can finish sleeping before its cancellation is observed.
        scheduler.fireIncludingCancelled()

        XCTAssertFalse(card.isPresented, "A cancelled open must not show the card")
        XCTAssertEqual(loads, 0, "A cancelled open must not request details")
    }

    @MainActor
    func testPassingPointerNeitherOpensNorRequestsDetails() {
        let scheduler = ManualCardScheduler()
        let card = ProvenanceCardPresenter(scheduler: scheduler)
        var loads = 0

        card.triggerHover(true) { loads += 1 }
        card.triggerHover(false) { loads += 1 }
        scheduler.firePending()

        XCTAssertFalse(card.isPresented, "Crossing a row on the way elsewhere must not open its card")
        XCTAssertEqual(loads, 0, "Crossing a row must not send a provenance request to the daemon")
    }

    @MainActor
    func testRestingOnTheTriggerOpensAfterTheHoverIntentDelay() {
        let scheduler = ManualCardScheduler()
        let card = ProvenanceCardPresenter(scheduler: scheduler)
        var loads = 0

        card.triggerHover(true) { loads += 1 }
        XCTAssertFalse(card.isPresented)
        XCTAssertEqual(loads, 0)
        XCTAssertEqual(scheduler.pendingDelays, [ProvenanceCardPresenter.hoverIntentDelay])

        scheduler.firePending()
        XCTAssertTrue(card.isPresented)
        XCTAssertEqual(loads, 1)
    }

    @MainActor
    func testSystemDismissalAndRowRemovalCloseAndCancelPendingWork() {
        let scheduler = ManualCardScheduler()
        let card = ProvenanceCardPresenter(scheduler: scheduler)
        card.activate {}

        card.presentation.wrappedValue = false
        XCTAssertFalse(card.isPresented, "A popover closed by the system must close the card")

        card.activate {}
        card.triggerHover(false) {}
        card.close()
        XCTAssertFalse(card.isPresented)
        XCTAssertEqual(scheduler.pendingDelays, [], "Closing cancels any pending dismissal")
    }
}

/// Runs scheduled card work only when the test says so, so no wall clock participates.
@MainActor
final class ManualCardScheduler: ProvenanceCardScheduling {
    private struct Entry {
        let delay: Duration
        let action: @MainActor () -> Void
        var cancelled = false
        var fired = false
    }

    private var entries: [Entry] = []

    var pendingDelays: [Duration] {
        entries.filter { !$0.cancelled && !$0.fired }.map(\.delay)
    }

    func schedule(after delay: Duration,
                  _ action: @escaping @MainActor () -> Void) -> @MainActor () -> Void {
        let index = entries.count
        entries.append(Entry(delay: delay, action: action))
        return { [weak self] in self?.entries[index].cancelled = true }
    }

    /// Fire every live entry in scheduling order, including entries scheduled while firing.
    func firePending() {
        var index = 0
        while index < entries.count {
            if !entries[index].cancelled && !entries[index].fired {
                entries[index].fired = true
                entries[index].action()
            }
            index += 1
        }
    }

    /// Fire every unfired entry, cancelled or not, modelling timers that woke before cancellation.
    func fireIncludingCancelled() {
        var index = 0
        while index < entries.count {
            if !entries[index].fired {
                entries[index].fired = true
                entries[index].action()
            }
            index += 1
        }
    }
}
