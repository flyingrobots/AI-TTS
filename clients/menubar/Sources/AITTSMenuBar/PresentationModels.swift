// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import AITTSApplication
import Foundation

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
