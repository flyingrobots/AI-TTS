// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import Foundation

/// Reopening the installed app returns ownership to its registered launch agent.
public struct MenuBarLaunchAgent {
    private let home: URL
    private let executablePath: String?
    private let managed: Bool
    private let userID: UInt32
    private let run: (String, [String]) throws -> Int32

    public init(
        home: URL = FileManager.default.homeDirectoryForCurrentUser,
        executablePath: String? = Bundle.main.executablePath,
        managed: Bool = ProcessInfo.processInfo.environment["AITTS_MENU_BAR_AGENT"] == "1",
        userID: UInt32 = getuid(),
        run: @escaping (String, [String]) throws -> Int32 = DaemonLauncher.runProcess
    ) {
        self.home = home
        self.executablePath = executablePath
        self.managed = managed
        self.userID = userID
        self.run = run
    }

    /// True means this manual process should exit before acquiring the UI lock.
    public func handOffIfInstalled() -> Bool {
        guard !managed, let executablePath else { return false }
        let plist = home.appendingPathComponent(
            "Library/LaunchAgents/com.flyingrobots.ai-tts.menubar.plist")
        guard let data = try? Data(contentsOf: plist),
              let payload = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
              payload["ProgramArguments"] as? [String] == [executablePath]
        else { return false }
        // Kickstart without -k leaves an already-running instance alone. If the
        // agent is disabled/unregistered, keep normal standalone launch working.
        return (try? run("/bin/launchctl", ["kickstart", "gui/\(userID)/com.flyingrobots.ai-tts.menubar"])) == 0
    }
}
