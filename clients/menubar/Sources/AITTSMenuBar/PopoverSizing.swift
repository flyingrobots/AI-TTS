// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import SwiftUI

/// Persisted menu dimensions, bounded by the screen hosting the status item.
@MainActor
final class PopoverSizing: ObservableObject {
    @Published private(set) var height: CGFloat
    var maximumHeight: CGFloat = 1200
    private let defaults: UserDefaults

    init(defaults: UserDefaults) {
        self.defaults = defaults
        let stored = defaults.double(forKey: "menuCardHeight")
        self.height = stored.isFinite && stored >= 360 ? min(stored, 1200) : 500
    }

    func resize(to proposed: CGFloat) {
        guard proposed.isFinite else { return }
        height = min(max(proposed, 360), maximumHeight)
        defaults.set(Double(height), forKey: "menuCardHeight")
    }
}
