// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import SwiftUI

/// Persisted menu dimensions, bounded by the screen hosting the status item.
@MainActor
final class PopoverSizing: ObservableObject {
    @Published private(set) var height: CGFloat
    private(set) var maximumHeight: CGFloat = 1200
    private var preferredHeight: CGFloat
    private let defaults: UserDefaults

    init(defaults: UserDefaults) {
        self.defaults = defaults
        let stored = defaults.double(forKey: "menuCardHeight")
        self.preferredHeight = stored.isFinite && stored >= 360 ? stored : 500
        self.height = preferredHeight
    }

    /// Fit the current screen without changing the durable user preference.
    func fit(to maximum: CGFloat) {
        guard maximum.isFinite, maximum > 0 else { return }
        maximumHeight = maximum
        height = min(preferredHeight, maximumHeight)
    }

    func resize(to proposed: CGFloat) {
        guard proposed.isFinite else { return }
        height = min(max(proposed, 360), maximumHeight)
        preferredHeight = max(height, 360)
        defaults.set(Double(preferredHeight), forKey: "menuCardHeight")
    }
}
