// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (menu presentation model under XCTest)
// Test-Oracle: approved bounded phrase captions advance with observed playback

import Foundation
import XCTest

@testable import AITTSMenuBar

final class CaptionCueTests: XCTestCase {
    override func setUp() {
        super.setUp()
        executionTimeAllowance = 15
    }

    func testLongSpokenSegmentBecomesBoundedCuesWithoutDroppingWords() {
        let text = (1...80).map { "word\($0)" }.joined(separator: " ")

        let track = CaptionCueTrack(text: text)

        XCTAssertGreaterThan(track.cues.count, 1)
        XCTAssertEqual(track.cues.joined(separator: " "), text)
        XCTAssertTrue(
            track.cues.allSatisfy {
                $0.split(whereSeparator: \.isWhitespace).count
                    <= CaptionCueTrack.maximumWords
            })
        XCTAssertTrue(
            track.cues.allSatisfy { $0.count <= CaptionCueTrack.maximumCharacters })
    }

    func testCaptionCuesPreferNaturalPunctuationBeforeTheHardLimit() {
        let track = CaptionCueTrack(
            text: "A short opening thought. The next thought continues with several more words."
        )

        XCTAssertEqual(
            track.cues,
            [
                "A short opening thought.",
                "The next thought continues with several more words.",
            ])
    }

    func testUnbrokenTokenIsBoundedWithoutDroppingCharacters() {
        let token = String(repeating: "x", count: CaptionCueTrack.maximumCharacters + 20)

        let track = CaptionCueTrack(text: token)

        XCTAssertEqual(track.cues.joined(), token)
        XCTAssertTrue(
            track.cues.allSatisfy { $0.count <= CaptionCueTrack.maximumCharacters })
    }

    func testCaptionCueAdvancesAcrossTheReportedClipDuration() {
        let track = CaptionCueTrack(
            text: "First concise thought. Second concise thought."
        )

        XCTAssertEqual(track.cue(positionMs: 0, durationMs: 8_000), "First concise thought.")
        XCTAssertEqual(
            track.cue(positionMs: 7_999, durationMs: 8_000),
            "Second concise thought."
        )
    }

    func testCaptionTimelineAdvancesOnlyDuringPlaybackAtTheObservedRate() {
        let observedAt = Date(timeIntervalSince1970: 1_000)
        let twoSecondsLater = observedAt.addingTimeInterval(2)

        XCTAssertEqual(
            CaptionPlaybackTimeline.positionMs(
                reportedPositionMs: 1_000,
                observedAt: observedAt,
                now: twoSecondsLater,
                playbackState: "playing",
                playbackRate: 1.5,
                durationMs: 10_000
            ),
            4_000
        )
        XCTAssertEqual(
            CaptionPlaybackTimeline.positionMs(
                reportedPositionMs: 1_000,
                observedAt: observedAt,
                now: twoSecondsLater,
                playbackState: "paused",
                playbackRate: 1.5,
                durationMs: 10_000
            ),
            1_000
        )
        XCTAssertEqual(
            CaptionPlaybackTimeline.positionMs(
                reportedPositionMs: 1_000,
                observedAt: observedAt,
                now: twoSecondsLater,
                playbackState: "playing",
                playbackRate: 3,
                durationMs: 5_000
            ),
            5_000
        )
    }
}
