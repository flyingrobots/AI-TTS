// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned Unix-socket transport fake)
// Test-Oracle: the first-run experience described in README's installation section

import Foundation
import XCTest

import AITTSApplication

@testable import AITTSMacAdapters
@testable import AITTSMenuBar

/// A first run fetches around 330 MB before anything can be spoken. Until the
/// snapshot said so, the menu bar showed what it shows for a fast clip, and a
/// fresh install was indistinguishable from a wedged daemon.
final class EnginePreparationTests: XCTestCase {
    override func setUp() {
        super.setUp()
        executionTimeAllowance = 15
    }

    func testThePreparingEngineReachesTheStatusModel() throws {
        let transport = PreparationTransport(responses: [
            Self.snapshot(engine: [
                "asset": "kokoro-v1_0.pth",
                "since": 1_788_000_000,
            ])
        ])
        let service = UnixSocketSpeechService(transport: transport)

        let preparing = try XCTUnwrap(service.snapshot().status.enginePreparing)

        XCTAssertEqual(preparing.asset, "kokoro-v1_0.pth")
        XCTAssertEqual(preparing.since, 1_788_000_000, accuracy: 0.001)
    }

    func testAReadyEngineReportsNothing() throws {
        let transport = PreparationTransport(responses: [Self.snapshot(engine: nil)])
        let service = UnixSocketSpeechService(transport: transport)

        // "Ready" and "preparing something unnamed" must not render the same.
        XCTAssertNil(try service.snapshot().status.enginePreparing)
    }

    func testAReportMissingItsAssetIsIgnored() throws {
        let transport = PreparationTransport(responses: [
            Self.snapshot(engine: ["since": 1_788_000_000])
        ])
        let service = UnixSocketSpeechService(transport: transport)

        // A banner that names no asset tells the listener less than no banner.
        XCTAssertNil(try service.snapshot().status.enginePreparing)
    }

    func testTheNoticeNamesTheAssetAndHowLongItHasBeenGoing() {
        let notice = EnginePreparationNotice(
            preparing: EnginePreparation(asset: "kokoro-v1_0.pth", since: 1_788_000_000),
            now: 1_788_000_125
        )

        // Named rather than measured: the model host reports no progress this
        // client can trust, so it says what and since when, not a percentage.
        XCTAssertEqual(notice.title, "Preparing the speech engine")
        XCTAssertTrue(notice.detail.contains("kokoro-v1_0.pth"), notice.detail)
        XCTAssertTrue(notice.detail.contains("2 min"), notice.detail)
    }

    func testAFreshFetchReadsAsJustStartedRatherThanZero() {
        let notice = EnginePreparationNotice(
            preparing: EnginePreparation(asset: "config.json", since: 1_788_000_000),
            now: 1_788_000_000
        )

        // "0 sec" reads as a stalled counter on the very first frame.
        XCTAssertTrue(notice.detail.contains("just started"), notice.detail)
    }

    func testAClockThatWentBackwardsDoesNotProduceNegativeTime() {
        let notice = EnginePreparationNotice(
            preparing: EnginePreparation(asset: "config.json", since: 1_788_000_050),
            now: 1_788_000_000
        )

        // The timestamp comes from the daemon's clock, not this process's.
        XCTAssertFalse(notice.detail.contains("-"), notice.detail)
        XCTAssertTrue(notice.detail.contains("just started"), notice.detail)
    }

    private static func snapshot(engine: [String: Any]?) -> [String: Any] {
        var status: [String: Any] = [
            "playback_state": "paused",
            "current": NSNull(),
            "counts": [:],
            "voice": "bf_emma",
            "engine": "kokoro",
        ]
        if let engine { status["engine_preparing"] = engine }
        return ["ok": true, "status": status]
    }
}

private final class PreparationTransport: DaemonTransport, @unchecked Sendable {
    private var responses: [[String: Any]]

    init(responses: [[String: Any]] = []) {
        self.responses = responses
    }

    func request(_ payload: [String: Any]) throws -> [String: Any] {
        _ = payload
        guard !responses.isEmpty else { return ["ok": true] }
        return responses.removeFirst()
    }

    func subscribe(shouldContinue: () -> Bool, onEvent: (Data) -> Void) throws {
        _ = shouldContinue
        _ = onEvent
    }
}

/// The controls a listener reaches for most, reachable without a trackpad.
///
/// The audit that prompted these found no key path to pause while the popover
/// was open, which is the single most-pressed control in the app: it is what
/// you press when speech starts during a call.
final class TransportKeyboardTests: XCTestCase {
    func testPauseIsATransportActionLikeTheRest() {
        // Pause was a separately-built button with a tooltip and no key. Being
        // in the enum is what makes its label and key assertable at all.
        XCTAssertTrue(TransportAction.allCases.contains(.playPause))
        XCTAssertFalse(TransportAction.playPause.label.isEmpty)
    }

    func testEveryTransportActionKeyIsUnique() {
        var seen: Set<String> = []
        for action in TransportAction.allCases {
            let key = String(describing: action.shortcut.character)
            XCTAssertFalse(seen.contains(key), "\(action.rawValue) reuses \(key)")
            seen.insert(key)
        }

        // A duplicate key means one of two controls silently never fires, and
        // which one is a SwiftUI implementation detail.
        XCTAssertEqual(seen.count, TransportAction.allCases.count)
    }

    func testPauseIsTheOnlyPrimaryControl() {
        let primary = TransportAction.allCases.filter(\.isPrimary)

        // The icon row renders everything that is not primary. Two primaries
        // would mean one control silently missing from the row, and none would
        // put a second pause button beside the prominent one, sharing its key.
        XCTAssertEqual(primary, [.playPause])
    }

    func testPauseDoesNotRequireAChunkedClip() {
        // Only the chunk controls are conditional. A pause that appeared and
        // disappeared with the shape of the current clip would be unusable.
        XCTAssertFalse(TransportAction.playPause.needsChunks)
    }
}
