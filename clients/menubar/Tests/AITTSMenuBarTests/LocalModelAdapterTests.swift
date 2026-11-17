// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (application and wire contract; owned JSON, no daemon or model)
// Test-Oracle: issue164 preserves usable legacy adapters and offers explicit refresh for stale/unknown code

import AITTSApplication
import Foundation
import XCTest
@testable import AITTSMacAdapters

final class LocalModelAdapterTests: XCTestCase {
    override func setUp() { super.setUp(); executionTimeAllowance = 15 }

    func testCapturedCancellationCatalogPreservesRepairConsent() throws {
        let file = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("../../../../docs/testing-evidence/artifacts/2026-11-16-worker-adapter-refresh/recovery-catalog-cases.json")
        let capture = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any])
        let cases = try XCTUnwrap(capture["cases"] as? [[String: Any]])
        XCTAssertEqual(cases.count, 4)
        for row in cases {
            let failed = try XCTUnwrap(row["incumbent_failed"] as? Bool)
            let model = try XCTUnwrap(row["model"] as? [String: Any])
            let snapshot = try XCTUnwrap(Snapshot(daemonJSON: [
                "status": ["playback_state": "idle", "engine": "fake", "voice": "default"],
                "models": [model]
            ]))
            let decoded = try XCTUnwrap(snapshot.models.first)
            XCTAssertEqual(decoded.adapterRefreshAvailable, !failed)
            XCTAssertEqual(decoded.message, "Setup cancelled. You can retry.")
        }
    }

    func testSnapshotPreservesAdapterStatusAndOlderDaemonAbsence() throws {
        let base: [String: Any] = ["name": "kokoro", "title": "Kokoro", "description": "Local",
                                  "installed": true, "selected": false, "state": "ready", "message": ""]
        let rows = [
            base.merging(["adapter_status": "stale"]) { _, new in new },
            base.merging(["adapter_status": "unknown"]) { _, new in new },
            base.merging(["adapter_status": "current"]) { _, new in new },
            base.merging(["adapter_status": NSNull()]) { _, new in new },
            base
        ]
        let snapshot = try XCTUnwrap(Snapshot(daemonJSON: [
            "status": ["playback_state": "idle", "engine": "kokoro", "voice": "af_heart"],
            "models": rows
        ]))
        XCTAssertEqual(snapshot.models.map(\.adapterStatus), [.stale, .unknown, .current, nil, nil])
        XCTAssertEqual(snapshot.models.map(\.installed), [true, true, true, true, true])
        XCTAssertEqual(snapshot.models.map(\.adapterRefreshAvailable), [true, true, false, false, false])
    }

    func testOnlyUsableIdleAdaptersOfferRefresh() {
        let ready = LocalSpeechModel(name: "kokoro", title: "Kokoro", description: "Local", installed: true,
                                     selected: true, state: "ready", message: "", adapterStatus: .stale)
        let missing = LocalSpeechModel(name: "kokoro", title: "Kokoro", description: "Local", installed: false,
                                       selected: false, state: "not installed", message: "", adapterStatus: .stale)
        let loading = LocalSpeechModel(name: "kokoro", title: "Kokoro", description: "Local", installed: true,
                                       selected: false, state: "loading", message: "", adapterStatus: .stale)
        let installing = LocalSpeechModel(name: "kokoro", title: "Kokoro", description: "Local", installed: true,
                                          selected: false, state: "installing", message: "", adapterStatus: .unknown)
        let incompatible = LocalSpeechModel(name: "kokoro", title: "Kokoro", description: "Local", installed: true,
                                            selected: false, state: "ready", message: "", incompatible: "Unavailable",
                                            adapterStatus: .stale)
        let failed = LocalSpeechModel(name: "kokoro", title: "Kokoro", description: "Local", installed: true,
                                      selected: true, state: "failed", message: "Setup failed", adapterStatus: .unknown)
        let cancelled = LocalSpeechModel(name: "kokoro", title: "Kokoro", description: "Local", installed: true,
                                         selected: true, state: "cancelled", message: "Cancelled", adapterStatus: .unknown)
        XCTAssertTrue(ready.adapterRefreshAvailable)
        XCTAssertFalse(missing.adapterRefreshAvailable)
        XCTAssertFalse(loading.adapterRefreshAvailable)
        XCTAssertFalse(installing.adapterRefreshAvailable)
        XCTAssertFalse(incompatible.adapterRefreshAvailable)
        XCTAssertFalse(failed.adapterRefreshAvailable)
        XCTAssertTrue(cancelled.adapterRefreshAvailable)
    }
}
