// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// Phrase-sized caption cues derived from segment text and clip-level timing.

import Foundation

struct CaptionCueTrack {
    static let maximumWords = 12
    static let maximumCharacters = 84

    let cues: [String]
    private let weights: [Int]

    init(text: String) {
        let cues = Self.makeCues(text: text)
        self.cues = cues
        self.weights = cues.map(Self.spokenWeight)
    }

    func cue(positionMs: Int?, durationMs: Int?) -> String {
        guard let first = cues.first else { return "" }
        guard cues.count > 1,
            let durationMs,
            durationMs > 0,
            let positionMs
        else { return first }

        let clampedPosition = min(max(positionMs, 0), durationMs)
        if clampedPosition == durationMs { return cues.last ?? first }

        let totalWeight = weights.reduce(0, +)
        guard totalWeight > 0 else { return first }
        let target =
            Double(clampedPosition) / Double(durationMs) * Double(totalWeight)
        var upperBound = 0
        for (index, weight) in weights.enumerated() {
            upperBound += weight
            if target < Double(upperBound) { return cues[index] }
        }
        return cues.last ?? first
    }

    private static func makeCues(text: String) -> [String] {
        let words = text.split(whereSeparator: \.isWhitespace).map(String.init)
        guard !words.isEmpty else { return [] }

        var cues: [String] = []
        var current: [String] = []
        var currentCharacters = 0

        func flush() {
            guard !current.isEmpty else { return }
            cues.append(current.joined(separator: " "))
            current.removeAll(keepingCapacity: true)
            currentCharacters = 0
        }

        for word in words {
            if word.count > maximumCharacters {
                flush()
                var remainder = word[...]
                while !remainder.isEmpty {
                    let chunk = remainder.prefix(maximumCharacters)
                    cues.append(String(chunk))
                    remainder = remainder.dropFirst(chunk.count)
                }
                continue
            }

            let joinedCharacters = currentCharacters + (current.isEmpty ? 0 : 1) + word.count
            if !current.isEmpty
                && (current.count == maximumWords || joinedCharacters > maximumCharacters)
            {
                flush()
            }

            current.append(word)
            currentCharacters += (current.count == 1 ? 0 : 1) + word.count

            if let boundary = terminalPunctuation(in: word),
                strongBoundaries.contains(boundary)
                    || (softBoundaries.contains(boundary) && current.count >= 6)
            {
                flush()
            }
        }
        flush()
        return cues
    }

    private static let strongBoundaries = Set<Character>(".!?;:\u{2026}")
    private static let softBoundaries = Set<Character>(",\u{2013}\u{2014}")
    private static let closingMarks = Set<Character>("\"'\u{2019}\u{201d})]}\u{00bb}")

    private static func terminalPunctuation(in word: String) -> Character? {
        word.reversed().first { !closingMarks.contains($0) }
    }

    private static func spokenWeight(_ cue: String) -> Int {
        let weight = cue.reduce(into: 0) { total, character in
            if character.isLetter || character.isNumber {
                total += 1
            } else if strongBoundaries.contains(character) {
                total += 6
            } else if softBoundaries.contains(character) {
                total += 3
            }
        }
        return max(weight, 1)
    }
}

struct CaptionMetadata: Equatable {
    let sourceLabel: String?
    let partLabel: String?

    init(source: String?, segmentNumber: Int, segmentCount: Int) {
        self.sourceLabel = source.flatMap { $0.isEmpty ? nil : "\($0):" }
        self.partLabel =
            segmentCount > 1 ? "PART \(segmentNumber) OF \(segmentCount)" : nil
    }
}

enum CaptionPlaybackTimeline {
    static func positionMs(
        reportedPositionMs: Int?,
        observedAt: Date,
        now: Date,
        playbackState: String,
        playbackRate: Double,
        durationMs: Int?
    ) -> Int {
        let reported = max(reportedPositionMs ?? 0, 0)
        guard playbackState.lowercased() == "playing" else {
            return clamped(reported, durationMs: durationMs)
        }
        let elapsed = max(now.timeIntervalSince(observedAt), 0)
        let rate = playbackRate.isFinite && playbackRate > 0 ? playbackRate : 1
        let advanced = reported + Int((elapsed * 1_000 * rate).rounded(.down))
        return clamped(advanced, durationMs: durationMs)
    }

    private static func clamped(_ positionMs: Int, durationMs: Int?) -> Int {
        guard let durationMs else { return positionMs }
        return min(positionMs, max(durationMs, 0))
    }
}
