// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import AppKit
import SwiftUI

/// A native, labeled action with a full button hit target inside the History row.
struct ProvenanceButton: NSViewRepresentable {
    let expanded: Bool
    let onPress: () -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onPress: onPress) }

    func makeNSView(context: Context) -> NSButton {
        let button = NSButton(title: "", target: context.coordinator,
                              action: #selector(Coordinator.press))
        button.bezelStyle = .rounded
        button.controlSize = .small
        button.font = .systemFont(ofSize: NSFont.smallSystemFontSize)
        updateNSView(button, context: context)
        return button
    }

    func updateNSView(_ button: NSButton, context: Context) {
        context.coordinator.onPress = onPress
        button.title = "Provenance"
        button.setAccessibilityLabel(expanded ? "Close provenance" : "Show provenance")
        button.setAccessibilityHelp("Hover or activate to inspect this clip’s source, arguments, and hashes")
    }

    final class Coordinator: NSObject {
        var onPress: () -> Void
        init(onPress: @escaping () -> Void) { self.onPress = onPress }
        @objc func press() { onPress() }
    }
}
