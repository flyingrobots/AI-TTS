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
    case restart
    case previousChunk
    case nextChunk
    case skip
    case fullText

    /// Spoken by VoiceOver, and shown as the tooltip.
    var label: String {
        switch self {
        case .restart: "Restart this clip"
        case .previousChunk: "Previous chunk"
        case .nextChunk: "Next chunk"
        case .skip: "Skip this clip"
        case .fullText: "Read the full text"
        }
    }

    var systemImage: String {
        switch self {
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
}
