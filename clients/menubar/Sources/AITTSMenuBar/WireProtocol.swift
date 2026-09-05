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

enum RequeuePriority: String, CaseIterable, Equatable {
    case normal
    case urgent

    var actionDescription: String {
        switch self {
        case .normal: return "Add to end of Queue"
        case .urgent: return "Play next after current"
        }
    }
}

enum PlaybackRate: Double, CaseIterable, Equatable, Hashable {
    case half = 0.5
    case threeQuarters = 0.75
    case normal = 1.0
    case oneAndHalf = 1.5
    case double = 2.0
    case triple = 3.0

    var label: String { String(format: "%g×", rawValue) }
}

struct ActiveSegment: Equatable {
    let index: Int
    let number: Int
    let count: Int
    let text: String
    let state: String
    let durationMs: Int?
    let positionMs: Int?
}

struct Utterance: Identifiable, Equatable {
    let id: String
    let text: String
    let voice: String
    let state: String
    let durationMs: Int?
    let playedMs: Int?
    let positionMs: Int?
    let error: String?
    let finalState: String?
    let source: String?
    let priority: RequeuePriority
    let enqueuedAt: Double?
    let finishedAt: Double?
    let segmentCount: Int
    let completedSegments: Int
    let activeSegment: ActiveSegment?

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
        self.positionMs = json["position_ms"] as? Int
        self.error = json["error"] as? String
        self.finalState = json["final_state"] as? String
        self.source = json["source"] as? String
        self.priority = RequeuePriority(rawValue: json["priority"] as? String ?? "") ?? .normal
        self.enqueuedAt = json["enqueued_at"] as? Double
        self.finishedAt = json["finished_at"] as? Double
        self.segmentCount = json["segment_count"] as? Int ?? 1
        self.completedSegments = json["completed_segments"] as? Int ?? 0
        self.activeSegment = nil
    }
}

struct DaemonStatus: Equatable {
    let playbackState: String
    let current: Utterance?
    let counts: [String: Int]
    let voice: String
    let engine: String

    init?(json: [String: Any]) {
        guard let playbackState =
            json["playback_state"] as? String ?? json["state"] as? String
        else { return nil }
        self.playbackState = playbackState
        self.current = (json["current"] as? [String: Any]).flatMap(Utterance.init(json:))
        self.counts = json["counts"] as? [String: Int] ?? [:]
        self.voice = json["voice"] as? String ?? ""
        self.engine = json["engine"] as? String ?? ""
    }
}

/// Everything the popover shows, from one `snapshot` request.
struct Snapshot {
    let status: DaemonStatus
    let plan: [Utterance]
    let input: [Utterance]
    let history: [Utterance]
    let voices: [String]
    let speed: Double
    let playbackRate: Double

    init?(json: [String: Any]) {
        guard let statusJson = json["status"] as? [String: Any],
            let status = DaemonStatus(json: statusJson)
        else { return nil }
        self.status = status
        self.plan = Self.items(json["plan"])
        self.input = Self.items(json["input"])
        self.history = Self.items(json["history"])
        self.voices = json["voices"] as? [String] ?? []
        let settings = json["settings"] as? [String: Any]
        self.speed = settings?["speed"] as? Double ?? 1.0
        self.playbackRate = settings?["playback_rate"] as? Double ?? 1.0
    }

    private static func items(_ value: Any?) -> [Utterance] {
        guard let rows = value as? [[String: Any]] else { return [] }
        return rows.compactMap(Utterance.init(json:))
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
