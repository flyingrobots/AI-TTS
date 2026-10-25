// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (menu presentation model under XCTest)
// Test-Oracle: approved bounded phrase captions preserve provenance and playback progress

import AITTSApplication
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

    // Kokoro (bm_daniel, 1x) word starts for this passage, measured from the
    // engine's own duration predictions on 2026-10-25; the clip is 16,375 ms.
    // See docs/testing-evidence/2026-10-25-caption-word-timing.md.
    private static let measuredText =
        "In 1995, Dr. Smith paid $3,450.75 for 12 GB of memory. The meeting starts at 3:30 p.m. "
        + "on Jan. 5th. Version 2.14.1 fixed 37 bugs. Call 555-0142 for details."
    private static let measuredStarts: [Int?] = [
        250, 312, 1350, 1675, 1975, 2250, 5050, 5175, 5512, 5862, 5950, 6725, 6825, 7200, 7512,
        7612, 8225, 8612, 8788, 9388, 9938, 10338, 11388, 11650, 12300, 12975, 13250, 15100, 15225,
    ]
    private static let measuredDurationMs = 16_375

    func testAbbreviationPeriodsDoNotSplitACue() {
        let track = CaptionCueTrack(text: Self.measuredText)

        XCTAssertEqual(
            track.cues,
            [
                "In 1995, Dr. Smith paid $3,450.75 for 12 GB of memory.",
                "The meeting starts at 3:30 p.m. on Jan. 5th.",
                "Version 2.14.1 fixed 37 bugs.",
                "Call 555-0142 for details.",
            ])
    }

    func testTimedCaptionShowsTheCueOfTheWordBeingHeard() {
        let timed = CaptionCueTrack(
            text: Self.measuredText,
            timing: CaptionTiming(wordStartsMs: Self.measuredStarts, complete: true)
        )
        let estimated = CaptionCueTrack(text: Self.measuredText)
        let duration = Self.measuredDurationMs

        XCTAssertTrue(timed.isTimed)
        // 6,600 ms: "memory." (5,950) is still sounding; "The" begins at 6,725.
        XCTAssertEqual(
            timed.cue(positionMs: 6_600, durationMs: duration),
            "In 1995, Dr. Smith paid $3,450.75 for 12 GB of memory."
        )
        // The proportional estimate has already moved on: the drift this fixes.
        XCTAssertEqual(
            estimated.cue(positionMs: 6_600, durationMs: duration),
            "The meeting starts at 3:30 p.m. on Jan. 5th."
        )
        XCTAssertEqual(
            timed.cue(positionMs: 6_725, durationMs: duration),
            "The meeting starts at 3:30 p.m. on Jan. 5th."
        )
        // A streaming clip has no duration yet; timing does not need one.
        XCTAssertEqual(timed.cue(positionMs: 13_000, durationMs: nil), "Call 555-0142 for details.")
        XCTAssertEqual(timed.cue(positionMs: 0, durationMs: nil), timed.cues[0])
    }

    func testIncompleteTimingHoldsTheLastTimedWordsCue() {
        let prefix = Array(Self.measuredStarts.prefix(12)) + Array(repeating: nil, count: 17)
        let track = CaptionCueTrack(
            text: Self.measuredText,
            timing: CaptionTiming(wordStartsMs: prefix, complete: false)
        )

        XCTAssertEqual(
            track.cue(positionMs: 9_000, durationMs: nil),
            "The meeting starts at 3:30 p.m. on Jan. 5th."
        )
    }

    func testTimingForDifferentWordsIsIgnored() {
        let track = CaptionCueTrack(
            text: "First concise thought. Second concise thought.",
            timing: CaptionTiming(wordStartsMs: [0, 7_000], complete: true)
        )

        XCTAssertFalse(track.isTimed)
        XCTAssertEqual(track.cue(positionMs: 7_999, durationMs: 8_000), "Second concise thought.")
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

    func testCaptionMetadataPreservesTheExactHistorySourceAboveTheCue() {
        let sourced = CaptionMetadata(
            source: "menubar-file:long-notes.md",
            segmentNumber: 3,
            segmentCount: 8
        )
        let legacy = CaptionMetadata(source: nil, segmentNumber: 1, segmentCount: 1)

        XCTAssertEqual(sourced.sourceLabel, "menubar-file:long-notes.md:")
        XCTAssertEqual(sourced.partLabel, "PART 3 OF 8")
        XCTAssertNil(legacy.sourceLabel)
        XCTAssertNil(legacy.partLabel)
    }
}
