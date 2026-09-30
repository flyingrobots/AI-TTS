// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import Foundation

/// Starts the installed per-user service without creating a second daemon.
public struct DaemonLauncher {
    private let home: URL
    private let userID: UInt32
    private let run: (String, [String]) throws -> Int32

    public init(
        home: URL = FileManager.default.homeDirectoryForCurrentUser,
        userID: UInt32 = getuid(),
        run: @escaping (String, [String]) throws -> Int32 = DaemonLauncher.runProcess
    ) {
        self.home = home
        self.userID = userID
        self.run = run
    }

    public func launch() throws {
        let domain = "gui/\(userID)"
        let service = "\(domain)/com.flyingrobots.ai-tts"
        let plist = home.appendingPathComponent(
            "Library/LaunchAgents/com.flyingrobots.ai-tts.plist")
        if try run("/bin/launchctl", ["print", service]) != 0 {
            guard FileManager.default.fileExists(atPath: plist.path) else {
                throw LaunchError.notInstalled
            }
            guard try run("/bin/launchctl", ["bootstrap", domain, plist.path]) == 0 else {
                throw LaunchError.failed
            }
        }
        guard try run("/bin/launchctl", ["kickstart", service]) == 0 else {
            throw LaunchError.failed
        }
    }

    public func restart() throws {
        guard try run("/bin/launchctl", ["kickstart", "-k", "gui/\(userID)/com.flyingrobots.ai-tts"]) == 0 else {
            throw LaunchError.failed
        }
    }

    public static func runProcess(_ executable: String, _ arguments: [String]) throws -> Int32 {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try process.run()
        process.waitUntilExit()
        return process.terminationStatus
    }

    private enum LaunchError: LocalizedError {
        case notInstalled, failed

        var errorDescription: String? {
            switch self {
            case .notInstalled:
                return "The daemon is not installed. Run make install from the AI-TTS checkout."
            case .failed:
                return "Could not launch the daemon. View Logs for details."
            }
        }
    }
}
