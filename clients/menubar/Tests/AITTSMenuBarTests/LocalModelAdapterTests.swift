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
        XCTAssertTrue(ready.adapterRefreshAvailable)
        XCTAssertFalse(missing.adapterRefreshAvailable)
        XCTAssertFalse(loading.adapterRefreshAvailable)
        XCTAssertFalse(installing.adapterRefreshAvailable)
        XCTAssertFalse(incompatible.adapterRefreshAvailable)
    }
}
