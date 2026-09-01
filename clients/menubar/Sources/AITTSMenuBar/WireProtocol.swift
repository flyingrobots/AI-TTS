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

struct Utterance: Identifiable, Equatable {
    let id: String
    let text: String
    let voice: String
    let state: String
    let durationMs: Int?
    let playedMs: Int?
    let error: String?
    let finalState: String?

    init?(json: [String: Any]) {
        guard let id = json["id"] as? String,
            let text = json["text"] as? String,
            let voice = json["voice"] as? String,
            let state = json["state"] as? String
        else { return nil }
        self.id = id
        self.text = text
        self.voice = voice
        self.state = state
        self.durationMs = json["duration_ms"] as? Int
        self.playedMs = json["played_ms"] as? Int
        self.error = json["error"] as? String
        self.finalState = json["final_state"] as? String
    }
}

struct DaemonStatus: Equatable {
    let state: String
    let current: Utterance?
    let counts: [String: Int]
    let voice: String

    init?(json: [String: Any]) {
        guard let state = json["state"] as? String else { return nil }
        self.state = state
        self.current = (json["current"] as? [String: Any]).flatMap(Utterance.init(json:))
        self.counts = json["counts"] as? [String: Int] ?? [:]
        self.voice = json["voice"] as? String ?? ""
    }
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
