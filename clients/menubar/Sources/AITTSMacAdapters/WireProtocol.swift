// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// The daemon's NDJSON protocol, typed. The tray app and the CLI have the same
// rights and use the same protocol; nothing the tray can do is unavailable to
// an agent (architecture.md §4).

import Foundation

enum WireError: Error, Equatable {
    case daemon(type: String, message: String)
    case malformed
}

enum WireProtocol {
    /// Encode one request as an NDJSON line.
    static func encode(_ payload: [String: Any]) throws -> Data {
        var line = try JSONSerialization.data(withJSONObject: payload)
        line.append(0x0A)
        return line
    }

    /// Parse one response line. A daemon error becomes a thrown `WireError`.
    static func parseResponse(_ line: Data) throws -> [String: Any] {
        guard let object = try? JSONSerialization.jsonObject(with: line),
            let json = object as? [String: Any]
        else { throw WireError.malformed }
        if (json["ok"] as? Bool) == true { return json }
        let error = json["error"] as? [String: Any]
        throw WireError.daemon(
            type: error?["type"] as? String ?? "internal",
            message: error?["message"] as? String ?? "unknown error"
        )
    }

    /// The default socket path, honouring AI_TTS_SOCKET.
    static func defaultSocketPath() -> String {
        if let override = ProcessInfo.processInfo.environment["AI_TTS_SOCKET"], !override.isEmpty {
            return (override as NSString).expandingTildeInPath
        }
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return home + "/Library/Application Support/ai-tts/ai-tts.sock"
    }
}
