// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import AITTSApplication
import Foundation

/// Deliver provenance on the UI actor without blocking it on the daemon socket.
@MainActor
protocol ProvenanceLoading {
    func load(_ id: String, completion: @escaping @MainActor (String) -> Void)
}

@MainActor
final class BackgroundProvenanceLoader: ProvenanceLoading {
    private let exporter: any EvidenceExporting

    init(exporter: any EvidenceExporting) { self.exporter = exporter }

    func load(_ id: String, completion: @escaping @MainActor (String) -> Void) {
        let exporter = exporter
        DispatchQueue.global(qos: .userInitiated).async {
            let text: String
            do { text = try exporter.provenance(id: id) }
            catch { text = "Provenance is unavailable. Close and reopen these details to retry." }
            Task { @MainActor in completion(text) }
        }
    }
}
