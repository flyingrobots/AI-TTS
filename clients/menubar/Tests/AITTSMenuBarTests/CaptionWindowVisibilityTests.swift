// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (AppKit main-actor application visibility)
// Test-Oracle: a caption-ready hidden accessory app becomes window-visible without activation

import XCTest

@testable import AITTSMenuBar

@MainActor
final class CaptionWindowVisibilityTests: XCTestCase {
    override func setUp() {
        super.setUp()
        executionTimeAllowance = 15
    }

    func testCaptionPanelHostUnhidesOnlyWhenLaunchServicesLeftItHidden() {
        let hiddenApplication = RecordingCaptionApplicationVisibility(isHidden: true)
        let visibleApplication = RecordingCaptionApplicationVisibility(isHidden: false)

        CaptionApplicationVisibility.prepareForPanel(hiddenApplication)
        CaptionApplicationVisibility.prepareForPanel(visibleApplication)

        XCTAssertFalse(hiddenApplication.isHidden)
        XCTAssertEqual(hiddenApplication.unhideWithoutActivationCount, 1)
        XCTAssertFalse(visibleApplication.isHidden)
        XCTAssertEqual(visibleApplication.unhideWithoutActivationCount, 0)
    }
}

@MainActor
private final class RecordingCaptionApplicationVisibility:
    CaptionApplicationVisibilityPort
{
    var isHidden: Bool
    private(set) var unhideWithoutActivationCount = 0

    init(isHidden: Bool) {
        self.isHidden = isHidden
    }

    func unhideWithoutActivation() {
        isHidden = false
        unhideWithoutActivationCount += 1
    }
}
