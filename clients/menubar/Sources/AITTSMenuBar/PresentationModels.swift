// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import AITTSApplication
import Foundation
import SwiftUI

extension RequeuePriority {
    var actionDescription: String {
        switch self {
        case .normal: return "Add to end of Queue"
        case .urgent: return "Play next after current"
        }
    }
}

/// The menu's deliberately finite set of live playback-rate choices.
enum PlaybackRate: Double, CaseIterable, Equatable, Hashable, Sendable {
    case half = 0.5
    case threeQuarters = 0.75
    case normal = 1.0
    case oneAndHalf = 1.5
    case double = 2.0
    case triple = 3.0

    var label: String { String(format: "%g×", rawValue) }
}

/// One clip's full text, addressed by the window that reads it.
///
/// Captions show a chunk at a time and the popover shows the first few lines;
/// neither lets the listener read the whole thing, which is what this carries.
struct FullTextSubject: Identifiable, Equatable {
    let id: String
    let text: String
    let voice: String
    let source: String?
    let segmentCount: Int
    /// The chunk being spoken right now, so the reader can highlight it.
    let activeSegmentText: String?

    var isChunked: Bool { segmentCount > 1 }
}

/// One transport control, with everything a caller needs to render it
/// accessibly and to bind a key to it.
///
/// This exists so accessibility is a value that can be asserted rather than a
/// modifier somebody has to remember. Icon-only buttons discard their text
/// label from the accessibility tree, and this tool is for people who are
/// listening rather than looking; an unlabelled transport is a pointed
/// failure here rather than a cosmetic one.
enum TransportAction: String, CaseIterable {
    case playPause
    case restart
    case previousChunk
    case nextChunk
    case skip
    case fullText

    /// Spoken by VoiceOver, and shown as the tooltip.
    var label: String {
        switch self {
        case .playPause: "Pause or resume playback"
        case .restart: "Restart this clip"
        case .previousChunk: "Previous chunk"
        case .nextChunk: "Next chunk"
        case .skip: "Skip this clip"
        case .fullText: "Read the full text"
        }
    }

    var systemImage: String {
        switch self {
        case .playPause: "pause.fill"
        case .restart: "backward.end.fill"
        case .previousChunk: "backward.fill"
        case .nextChunk: "forward.fill"
        case .skip: "forward.end.fill"
        case .fullText: "text.alignleft"
        }
    }

    /// The key that operates it while the popover is focused.
    var shortcut: KeyEquivalent {
        switch self {
        // The most-pressed control in the app: it is what you reach for when
        // speech starts during a call. It had a tooltip and no key.
        case .playPause: "p"
        case .restart: "r"
        case .previousChunk: .leftArrow
        case .nextChunk: .rightArrow
        case .skip: "."
        case .fullText: "t"
        }
    }

    /// Whether the control only makes sense for a clip split into chunks.
    var needsChunks: Bool {
        self == .previousChunk || self == .nextChunk
    }

    /// Whether this is the one control rendered prominently rather than as an
    /// icon in the transport row.
    ///
    /// Pause is the most-pressed control in the app and reads as a decision
    /// rather than a nudge, so it keeps its own labelled button. It is in this
    /// enum anyway so that its label and its key are assertable like the rest;
    /// a control whose accessibility lives only at its call site is a control
    /// nothing can check.
    var isPrimary: Bool {
        self == .playPause
    }
}

/// What to show while the engine is still fetching what it needs to speak.
///
/// A first run pulls around 330 MB before a single word comes out. The daemon
/// reports which asset and since when, and deliberately no percentage: the
/// model host gives no progress this client can trust, and an invented one is
/// worse than an honest "still fetching this".
struct EnginePreparationNotice: Equatable {
    let asset: String
    let elapsed: TimeInterval

    init(preparing: EnginePreparation, now: TimeInterval = Date().timeIntervalSince1970) {
        asset = preparing.asset
        // The timestamp is on the daemon's clock, not this process's, so it
        // can legitimately sit ahead of `now`. Clamped, because a countdown
        // running backwards reads as a bug in the thing you are waiting for.
        elapsed = max(0, now - preparing.since)
    }

    var title: String { "Preparing the speech engine" }

    var detail: String {
        "Fetching \(asset), \(sinceDescription). Speech starts once it finishes."
    }

    private var sinceDescription: String {
        // "0 sec" reads as a stalled counter on the very first frame.
        if elapsed < 1 { return "just started" }
        if elapsed < 60 { return "\(Int(elapsed)) sec so far" }
        return "\(Int(elapsed) / 60) min so far"
    }
}
