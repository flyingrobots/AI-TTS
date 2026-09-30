// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned route and explicit asynchronous restoration gate)
// Test-Oracle: duck only during speech; reuse active routes; restore on pause, disable, disconnection

import XCTest
import AITTSApplication

private final class OwnedDuckingRoute: MediaDuckingRoute {
    let outputDevice: UInt32
    var gains: [Bool] = []
    var closed = 0
    init(_ device: UInt32 = 1) { outputDevice = device }
    var readiness: () async throws -> Void = {}
    func waitUntilReady() async throws { try await readiness() }
    var monitoring: () async throws -> Void = { try await Task.sleep(nanoseconds: 60_000_000_000) }
    func monitorDelivery() async throws { try await monitoring() }
    func setDucked(_ value: Bool) { gains.append(value) }
    func close() { closed += 1 }
}

final class MediaDuckingTests: XCTestCase {
    override func setUp() { super.setUp(); executionTimeAllowance = 15 }

    @MainActor
    func testInactiveDefaultDoesNotCreateTapAndSpeechReusesRoute() {
        let route = OwnedDuckingRoute()
        var pids: [Int32] = []
        let controller = MediaDuckingController(create: { pids.append($0); return route }, defaultOutput: { 1 })
        controller.update(enabled: true, speaking: false, daemonPID: 12)
        XCTAssertEqual(pids, [])
        controller.update(enabled: true, speaking: true, daemonPID: 12)
        controller.update(enabled: true, speaking: true, daemonPID: 12)
        XCTAssertEqual(pids, [12])
        XCTAssertEqual(route.gains, [true, true])
        controller.close()
        XCTAssertEqual(route.closed, 1)
    }

    @MainActor
    func testPauseRestoresBeforeClosingAndResumeCancelsOldClose() async {
        let route = OwnedDuckingRoute()
        var resume: CheckedContinuation<Void, Never>?
        let delayEntered = expectation(description: "restoration gate")
        let delayExited = expectation(description: "restoration released")
        let controller = MediaDuckingController(create: { _ in route }, defaultOutput: { 1 }, releaseDelay: {
            await withCheckedContinuation { continuation in
                resume = continuation
                delayEntered.fulfill()
            }
            delayExited.fulfill()
        })
        controller.update(enabled: true, speaking: true, daemonPID: 12)
        controller.update(enabled: true, speaking: false, daemonPID: 12)
        await fulfillment(of: [delayEntered], timeout: 1)
        XCTAssertEqual(route.gains, [true, false])
        XCTAssertEqual(route.closed, 0)
        controller.update(enabled: true, speaking: true, daemonPID: 12)
        resume?.resume()
        await fulfillment(of: [delayExited], timeout: 1)
        XCTAssertEqual(route.closed, 0)
        controller.close()
        XCTAssertEqual(route.gains, [true, false, true])
        XCTAssertEqual(route.closed, 1)
    }

    @MainActor
    func testPauseDisableAndDisconnectRestoreAndReleaseTheRoute() async {
        for ending in ["pause", "disable", "disconnect"] {
            let route = OwnedDuckingRoute()
            let released = expectation(description: ending)
            let controller = MediaDuckingController(create: { _ in route }, defaultOutput: { 1 }, releaseDelay: {})
            controller.update(enabled: true, speaking: true, daemonPID: 12)
            controller.onStatus = { _ in released.fulfill() }
            controller.update(enabled: ending != "disable", speaking: ending != "pause", daemonPID: ending == "disconnect" ? nil : 12)
            await fulfillment(of: [released], timeout: 1)
            XCTAssertEqual(route.gains, [true, false])
            XCTAssertEqual(route.closed, 1)
            controller.close()
            XCTAssertEqual(route.closed, 1)
        }
    }

    @MainActor
    func testOutputAndDaemonChangesCloseOldRouteBeforeReplacement() {
        var output: UInt32 = 1
        var routes: [OwnedDuckingRoute] = []
        let controller = MediaDuckingController(create: { _ in
            if let previous = routes.last { XCTAssertEqual(previous.closed, 1) }
            let route = OwnedDuckingRoute(output)
            routes.append(route)
            return route
        }, defaultOutput: { output })
        controller.update(enabled: true, speaking: true, daemonPID: 12)
        output = 2
        controller.update(enabled: true, speaking: true, daemonPID: 12)
        controller.update(enabled: true, speaking: true, daemonPID: 13)
        XCTAssertEqual(routes.count, 3)
        XCTAssertEqual(routes.map(\.closed), [1, 1, 0])
        controller.close()
    }

    @MainActor
    func testReadinessIsNotPublishedBeforeDeliveryAndFailureClosesRoute() async {
        let route = OwnedDuckingRoute()
        var release: CheckedContinuation<Void, Error>?
        let waiting = expectation(description: "waiting for native delivery")
        let failed = expectation(description: "readiness failure published")
        route.readiness = {
            try await withCheckedThrowingContinuation { continuation in
                release = continuation
                waiting.fulfill()
            }
        }
        let controller = MediaDuckingController(create: { _ in route }, defaultOutput: { 1 })
        controller.onStatus = { if $0.contains("no delivery") { failed.fulfill() } }
        controller.update(enabled: true, speaking: true, daemonPID: 12)
        await fulfillment(of: [waiting], timeout: 1)
        XCTAssertTrue(controller.status.hasPrefix("Waiting"))
        XCTAssertEqual(route.closed, 0)
        release?.resume(throwing: NSError(domain: "no delivery", code: 1))
        await fulfillment(of: [failed], timeout: 1)
        XCTAssertEqual(route.closed, 1)
        controller.close()
        XCTAssertEqual(route.closed, 1)
    }

    @MainActor
    func testConfirmedDeliveryPublishesActiveStatus() async {
        let route = OwnedDuckingRoute()
        let active = expectation(description: "native delivery confirmed")
        let controller = MediaDuckingController(create: { _ in route }, defaultOutput: { 1 })
        controller.onStatus = { if $0 == "Other apps are lowered during speech." { active.fulfill() } }
        controller.update(enabled: true, speaking: true, daemonPID: 12)
        await fulfillment(of: [active], timeout: 1)
        XCTAssertEqual(route.closed, 0)
        controller.close()
    }

    @MainActor
    func testActiveDeliveryFailureRestoresRouteWithoutAnotherSnapshot() async {
        let route = OwnedDuckingRoute()
        var release: CheckedContinuation<Void, Error>?
        let monitoring = expectation(description: "monitor active delivery")
        let restored = expectation(description: "route failure surfaced")
        route.monitoring = {
            try await withCheckedThrowingContinuation { continuation in
                release = continuation
                monitoring.fulfill()
            }
        }
        let controller = MediaDuckingController(create: { _ in route }, defaultOutput: { 1 })
        controller.onStatus = { if $0.contains("delivery stopped") { restored.fulfill() } }
        controller.update(enabled: true, speaking: true, daemonPID: 12)
        await fulfillment(of: [monitoring], timeout: 1)
        XCTAssertEqual(controller.status, "Other apps are lowered during speech.")
        release?.resume(throwing: NSError(domain: "delivery stopped", code: 1))
        await fulfillment(of: [restored], timeout: 1)
        XCTAssertEqual(route.closed, 1)
        controller.close()
        XCTAssertEqual(route.closed, 1)
    }

    @MainActor
    func testIdleDeliveryGapRestoresAndRearmsWithoutAnotherSnapshot() async {
        let first = OwnedDuckingRoute(), second = OwnedDuckingRoute()
        let rearmed = expectation(description: "new unmuted route waiting for audio")
        first.monitoring = { throw MediaDuckingRouteError.deliveryInterrupted }
        var attempts = 0
        let controller = MediaDuckingController(create: { _ in
            attempts += 1
            if attempts == 1 { return first }
            XCTAssertEqual(first.closed, 1)
            rearmed.fulfill()
            return second
        }, defaultOutput: { 1 })
        controller.update(enabled: true, speaking: true, daemonPID: 12)
        await fulfillment(of: [rearmed], timeout: 1)
        XCTAssertEqual(attempts, 2)
        XCTAssertEqual(second.closed, 0)
        controller.close()
        XCTAssertEqual(second.closed, 1)
    }

    @MainActor
    func testFailureDoesNotRepeatedlyRequestPermissionUntilRetry() {
        var attempts = 0
        let controller = MediaDuckingController(create: { _ in
            attempts += 1
            throw NSError(domain: "permission", code: 1)
        }, defaultOutput: { 1 })
        controller.update(enabled: true, speaking: true, daemonPID: 12)
        controller.update(enabled: true, speaking: true, daemonPID: 12)
        XCTAssertEqual(attempts, 1)
        XCTAssertTrue(controller.status.contains("permission"))
        controller.retry()
        controller.update(enabled: true, speaking: true, daemonPID: 12)
        XCTAssertEqual(attempts, 2)
    }
}
