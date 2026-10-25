// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// Phrase-sized caption cues for one spoken clip. When the daemon reports word
// timing, the cue holding the word being heard is shown; otherwise the cue is
// estimated from the clip's position within its duration.

import AITTSApplication
import Foundation

struct CaptionCueTrack {
    static let maximumWords = 12
    static let maximumCharacters = 84

    let cues: [String]
    private let weights: [Int]
    /// The index of the clip word each cue begins with.
    private let firstWords: [Int]
    /// Daemon word start times, kept only when they describe these words.
    private let wordStartsMs: [Int?]?

    init(text: String, timing: CaptionTiming? = nil) {
        let words = text.split(whereSeparator: \.isWhitespace).map(String.init)
        let built = Self.makeCues(words: words)
        self.cues = built.map(\.text)
        self.firstWords = built.map(\.firstWord)
        self.weights = cues.map(Self.spokenWeight)
        self.wordStartsMs =
            timing.flatMap { $0.wordStartsMs.count == words.count ? $0.wordStartsMs : nil }
    }

    /// Whether cues follow reported word timing rather than an estimate.
    var isTimed: Bool { wordStartsMs != nil }

    func cue(positionMs: Int?, durationMs: Int?) -> String {
        guard let first = cues.first else { return "" }
        if let wordStartsMs, let positionMs {
            return timedCue(positionMs: positionMs, wordStartsMs: wordStartsMs) ?? first
        }
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

    /// The cue holding the word most recently begun; `nil` before the first word.
    private func timedCue(positionMs: Int, wordStartsMs: [Int?]) -> String? {
        var heard: Int?
        for (index, start) in wordStartsMs.enumerated() {
            guard let start else { continue }
            if start > positionMs { break }
            heard = index
        }
        guard let heard else { return nil }
        let cue = firstWords.lastIndex { $0 <= heard } ?? 0
        return cues[cue]
    }

    private static func makeCues(words: [String]) -> [(text: String, firstWord: Int)] {
        guard !words.isEmpty else { return [] }

        var cues: [(text: String, firstWord: Int)] = []
        var current: [String] = []
        var currentFirst = 0
        var currentCharacters = 0

        func flush() {
            guard !current.isEmpty else { return }
            cues.append((current.joined(separator: " "), currentFirst))
            current.removeAll(keepingCapacity: true)
            currentCharacters = 0
        }

        for (index, word) in words.enumerated() {
            if word.count > maximumCharacters {
                flush()
                var remainder = word[...]
                while !remainder.isEmpty {
                    let chunk = remainder.prefix(maximumCharacters)
                    cues.append((String(chunk), index))
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

            if current.isEmpty { currentFirst = index }
            current.append(word)
            currentCharacters += (current.count == 1 ? 0 : 1) + word.count

            let following = index + 1 < words.count ? words[index + 1] : nil
            if let boundary = terminalPunctuation(in: word),
                (strongBoundaries.contains(boundary)
                    && !(boundary == "." && isAbbreviation(word, following: following)))
                    || (softBoundaries.contains(boundary) && current.count >= 6)
            {
                flush()
            }
        }
        flush()
        return cues
    }

    // Kept in step with the daemon's sentence rules in src/aitts/timing.py.
    private static let titleAbbreviations: Set<String> = [
        "mr.", "mrs.", "ms.", "dr.", "prof.", "st.", "sr.", "jr.", "rev.", "gen.", "capt.", "sgt.",
    ]
    private static let abbreviations: Set<String> = titleAbbreviations.union([
        "vs.", "etc.", "e.g.", "i.e.", "a.m.", "p.m.", "no.", "fig.", "approx.", "inc.", "ltd.",
        "co.", "jan.", "feb.", "mar.", "apr.", "jun.", "jul.", "aug.", "sep.", "sept.", "oct.",
        "nov.", "dec.",
    ])

    /// A period that abbreviates rather than ends: a title, an initial, or a
    /// known abbreviation followed by text that shows the sentence continues.
    private static func isAbbreviation(_ word: String, following: String?) -> Bool {
        var core = Substring(word.lowercased())
        while let last = core.last, closingMarks.contains(last) { core = core.dropLast() }
        core = core.drop { "\"'([{\u{2018}\u{201c}".contains($0) }
        let lowered = String(core)
        let initial = lowered.count == 2 && lowered.first?.isLetter == true && lowered.last == "."
        guard abbreviations.contains(lowered) || initial, let following else { return false }
        if titleAbbreviations.contains(lowered) || initial { return true }
        return following.first.map { !$0.isUppercase } ?? false
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
