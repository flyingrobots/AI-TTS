// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned temporary home; no real launchctl invocation)
// Test-Oracle: installed launch-agent contract; explicit launch starts one user service, errors stay visible

import Foundation
import XCTest
import AITTSMacAdapters

final class DaemonLauncherTests: XCTestCase {
    private var home: URL!

    override func setUpWithError() throws {
        executionTimeAllowance = 15
        home = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try FileManager.default.removeItem(at: home)
    }

    func testRestartExplicitlyReplacesRegisteredDaemon() throws {
        var calls: [[String]] = []
        let launcher = DaemonLauncher(home: home, userID: 42) { executable, arguments in
            calls.append([executable] + arguments)
            return 0
        }
        try launcher.restart()
        XCTAssertEqual(calls, [["/bin/launchctl", "kickstart", "-k", "gui/42/com.flyingrobots.ai-tts"]])
    }

    func testRegisteredServiceStartsWithoutRestartingOrBootstrapping() throws {
        var calls: [[String]] = []
        let launcher = DaemonLauncher(home: home, userID: 42) { executable, arguments in
            calls.append([executable] + arguments)
            return 0
        }
        try launcher.launch()
        XCTAssertEqual(calls, [
            ["/bin/launchctl", "print", "gui/42/com.flyingrobots.ai-tts"],
            ["/bin/launchctl", "kickstart", "gui/42/com.flyingrobots.ai-tts"],
        ])
    }

    func testUnregisteredServiceLoadsInstalledAgentBeforeStarting() throws {
        let plist = home.appendingPathComponent("Library/LaunchAgents/com.flyingrobots.ai-tts.plist")
        try FileManager.default.createDirectory(
            at: plist.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data().write(to: plist)
        var calls: [[String]] = []
        let launcher = DaemonLauncher(home: home, userID: 42) { executable, arguments in
            calls.append([executable] + arguments)
            return arguments.first == "print" ? 113 : 0
        }
        try launcher.launch()
        XCTAssertEqual(calls, [
            ["/bin/launchctl", "print", "gui/42/com.flyingrobots.ai-tts"],
            ["/bin/launchctl", "bootstrap", "gui/42", plist.path],
            ["/bin/launchctl", "kickstart", "gui/42/com.flyingrobots.ai-tts"],
        ])
    }

    func testMissingInstallationReportsActionableFailure() {
        let launcher = DaemonLauncher(home: home, userID: 42) { _, _ in 113 }
        var message: String?
        do { try launcher.launch() } catch { message = error.localizedDescription }
        XCTAssertEqual(message,
            "The daemon is not installed. Run make install from the AI-TTS checkout.")
    }

    func testFailedStartReportsFailure() {
        let launcher = DaemonLauncher(home: home, userID: 42) { _, arguments in
            arguments.first == "print" ? 0 : 1
        }
        var message: String?
        do { try launcher.launch() } catch { message = error.localizedDescription }
        XCTAssertEqual(message, "Could not launch the daemon. View Logs for details.")
    }
}
