// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (the dispatch-source case delivers an otherwise unused, ignored signal to this process)
// Test-Oracle: James's decision R; SIGTERM takes the normal NSApplication termination path, so applicationWillTerminate cleanup runs

import Darwin
import Foundation
import XCTest
import AITTSMacAdapters

final class TerminationSignalRouterTests: XCTestCase {
    override func setUp() {
        executionTimeAllowance = 15
    }

    // Retire with the installer's SIGTERM retirement of a running menu-bar UI.
    func testInstalledSigtermHandlerCallsTheNormalTerminationPath() {
        var installed: [(Int32, () -> Void)] = []
        var terminations = 0
        let router = TerminationSignalRouter(
            install: { signal, handler in
                installed.append((signal, handler))
                return NSObject()
            },
            terminate: { terminations += 1 }
        )

        XCTAssertEqual(installed.map(\.0), [SIGTERM])
        XCTAssertEqual(terminations, 0, "installing the handler must not terminate")
        installed.first?.1()
        XCTAssertEqual(terminations, 1)
        withExtendedLifetime(router) {}
    }

    func testDispatchSourceDeliversTheSignalToTheHandlerInsteadOfKilling() {
        // SIGUSR2 is unused by XCTest and the source ignores it first, so the
        // test process survives delivery; the real app installs SIGTERM.
        let delivered = expectation(description: "signal routed to handler")
        delivered.assertForOverFulfill = false
        let queue = DispatchQueue(label: "termination-signal-router-test")
        let source = TerminationSignalRouter.dispatchSource(signal: SIGUSR2, queue: queue) {
            delivered.fulfill()
        }
        defer {
            (source as? DispatchSourceSignal)?.cancel()
            Darwin.signal(SIGUSR2, SIG_DFL)
        }
        // The source registers with the kernel asynchronously after resume, so
        // a signal sent before registration is missed. Resend until observed.
        var result = XCTWaiter.Result.timedOut
        for _ in 0..<50 where result != .completed {
            XCTAssertEqual(kill(getpid(), SIGUSR2), 0)
            result = XCTWaiter().wait(for: [delivered], timeout: 0.1)
        }
        XCTAssertEqual(result, .completed)
    }
}
