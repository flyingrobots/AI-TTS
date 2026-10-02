// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned temporary home; no real launchctl invocation)
// Test-Oracle: manual reopen resumes registered UI supervision; managed/development launches stay local

import Foundation
import XCTest
import AITTSMacAdapters

final class MenuBarLaunchAgentTests: XCTestCase {
    private var home: URL!
    private let executable = "/owned/AI-TTS.app/Contents/MacOS/AITTSMenuBar"

    override func setUpWithError() throws {
        executionTimeAllowance = 15
        home = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let plist = home.appendingPathComponent("Library/LaunchAgents/com.flyingrobots.ai-tts.menubar.plist")
        try FileManager.default.createDirectory(at: plist.deletingLastPathComponent(), withIntermediateDirectories: true)
        try PropertyListSerialization.data(
            fromPropertyList: ["ProgramArguments": [executable]], format: .xml, options: 0
        ).write(to: plist)
    }

    override func tearDownWithError() throws {
        try FileManager.default.removeItem(at: home)
    }

    // Retire with the launch-agent ownership contract.
    func testManualReopenHandsOffWithoutKillingRunningUI() {
        var calls: [[String]] = []
        let launcher = MenuBarLaunchAgent(home: home, executablePath: executable, managed: false, userID: 42) {
            executable, arguments in
            calls.append([executable] + arguments)
            return 0
        }
        XCTAssertTrue(launcher.handOffIfInstalled())
        XCTAssertEqual(calls, [["/bin/launchctl", "kickstart", "gui/42/com.flyingrobots.ai-tts.menubar"]])
    }

    func testManagedAndDevelopmentLaunchesStayLocal() {
        for (path, managed) in [(executable, true), ("/development/AITTSMenuBar", false)] {
            var calls = 0
            let launcher = MenuBarLaunchAgent(home: home, executablePath: path, managed: managed) { _, _ in
                calls += 1
                return 0
            }
            XCTAssertFalse(launcher.handOffIfInstalled())
            XCTAssertEqual(calls, 0)
        }
    }

    // CodeRabbit PRRT_kwDOUHyfMM6oPaqg: a hung launchctl must not block startup.
    func testHungKickstartFallsBackToStandaloneLaunchWithinItsDeadline() {
        let started = Date()
        let launcher = MenuBarLaunchAgent(home: home, executablePath: executable, managed: false) { _, _ in
            // An owned child that never exits stands in for a hung launchctl.
            try MenuBarLaunchAgent.runProcess("/bin/sleep", ["30"], deadline: 0.2)
        }
        XCTAssertFalse(launcher.handOffIfInstalled())
        XCTAssertLessThan(Date().timeIntervalSince(started), 5)
    }

    func testUnavailableAgentPreservesStandaloneLaunch() {
        for failsWithError in [false, true] {
            let launcher = MenuBarLaunchAgent(home: home, executablePath: executable, managed: false) { _, _ in
                if failsWithError { throw NSError(domain: "owned launchctl failure", code: 1) }
                return 113
            }
            XCTAssertFalse(launcher.handOffIfInstalled())
        }
    }
}
