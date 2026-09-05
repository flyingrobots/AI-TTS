// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import AITTSApplication
import Foundation

/// The raw transport seam owned by the Unix-socket speech adapter.
protocol DaemonTransport: Sendable {
    func request(_ payload: [String: Any]) throws -> [String: Any]
    func subscribe(shouldContinue: () -> Bool, onEvent: (Data) -> Void) throws
}

extension DaemonClient: DaemonTransport {}

/// Outbound adapter from typed application requests to the daemon's NDJSON protocol.
public struct UnixSocketSpeechService: SpeechServicePort, Sendable {
    private let transport: any DaemonTransport

    public init() {
        self.transport = DaemonClient()
    }

    init(transport: any DaemonTransport) {
        self.transport = transport
    }

    public func snapshot() throws -> Snapshot {
        let response = try request(["op": "snapshot"])
        guard let snapshot = Snapshot(daemonJSON: response) else {
            throw SpeechServiceError.invalidResponse
        }
        return snapshot
    }

    public func submit(_ submission: SpeechSubmission) throws {
        var payload: [String: Any] = [
            "op": "submit",
            "text": submission.text,
            "content_format": submission.contentFormat.rawValue,
            "sensitivity": submission.sensitivity.rawValue,
            "priority": submission.priority.rawValue,
        ]
        if let voice = submission.voice { payload["voice"] = voice }
        if let speed = submission.speed { payload["speed"] = speed }
        if let source = submission.source { payload["source"] = source }
        _ = try request(payload)
    }

    public func perform(_ command: SpeechCommand) throws {
        let payload: [String: Any]
        switch command {
        case .pause:
            payload = ["op": "pause"]
        case .resume:
            payload = ["op": "resume"]
        case .skip:
            payload = ["op": "skip"]
        case .rewind(let id):
            if let id {
                payload = ["op": "rewind", "to": id]
            } else {
                payload = ["op": "rewind"]
            }
        case .cancel(let id):
            payload = ["op": "cancel", "id": id]
        case .clearQueue:
            payload = ["op": "clear", "queue": "queue"]
        case .clearHistory:
            payload = ["op": "clear", "queue": "history"]
        case .removeHistory(let id):
            payload = ["op": "remove_history", "id": id]
        case .requeue(let id, let priority):
            payload = ["op": "requeue", "id": id, "priority": priority.rawValue]
        case .reorder(let ids):
            payload = ["op": "reorder", "ids": ids]
        case .setVoice(let voice):
            payload = ["op": "settings", "set": ["voice": voice]]
        case .setSynthesisSpeed(let speed):
            payload = ["op": "settings", "set": ["speed": speed]]
        case .setPlaybackRate(let rate):
            payload = ["op": "settings", "set": ["playback_rate": rate]]
        }
        _ = try request(payload)
    }

    public func subscribe(shouldContinue: () -> Bool, onChange: () -> Void) throws {
        do {
            try transport.subscribe(
                shouldContinue: shouldContinue,
                onEvent: { _ in onChange() }
            )
        } catch let WireError.daemon(type, message) {
            throw SpeechServiceError.rejected(type: type, message: message)
        } catch WireError.malformed {
            throw SpeechServiceError.invalidResponse
        } catch {
            throw SpeechServiceError.unavailable
        }
    }

    private func request(_ payload: [String: Any]) throws -> [String: Any] {
        do {
            return try transport.request(payload)
        } catch let WireError.daemon(type, message) {
            throw SpeechServiceError.rejected(type: type, message: message)
        } catch WireError.malformed {
            throw SpeechServiceError.invalidResponse
        } catch {
            throw SpeechServiceError.unavailable
        }
    }
}

// These decoders live with the outbound adapter so the application models do
// not know about daemon dictionaries or field names.
extension ActiveSegment {
    init?(daemonJSON json: [String: Any]) {
        guard let index = json["index"] as? Int,
            let number = json["number"] as? Int,
            let count = json["count"] as? Int,
            let text = json["text"] as? String,
            let state = json["state"] as? String
        else { return nil }
        self.init(
            index: index,
            number: number,
            count: count,
            text: text,
            state: state,
            durationMs: json["duration_ms"] as? Int,
            positionMs: json["position_ms"] as? Int
        )
    }
}

extension Utterance {
    init?(daemonJSON json: [String: Any]) {
        guard let id = json["id"] as? String,
            let text = json["text"] as? String,
            let voice = json["voice"] as? String,
            let state = json["state"] as? String
        else { return nil }
        self.init(
            id: id,
            text: text,
            voice: voice,
            state: state,
            durationMs: json["duration_ms"] as? Int,
            playedMs: json["played_ms"] as? Int,
            positionMs: json["position_ms"] as? Int,
            error: json["error"] as? String,
            finalState: json["final_state"] as? String,
            source: json["source"] as? String,
            priority: RequeuePriority(rawValue: json["priority"] as? String ?? "") ?? .normal,
            enqueuedAt: json["enqueued_at"] as? Double,
            finishedAt: json["finished_at"] as? Double,
            segmentCount: json["segment_count"] as? Int ?? 1,
            completedSegments: json["completed_segments"] as? Int ?? 0,
            activeSegment: (json["active_segment"] as? [String: Any])
                .flatMap(ActiveSegment.init(daemonJSON:))
        )
    }
}

extension DaemonStatus {
    init?(daemonJSON json: [String: Any]) {
        guard let playbackState =
            json["playback_state"] as? String ?? json["state"] as? String
        else { return nil }
        self.init(
            playbackState: playbackState,
            current: (json["current"] as? [String: Any])
                .flatMap(Utterance.init(daemonJSON:)),
            counts: json["counts"] as? [String: Int] ?? [:],
            voice: json["voice"] as? String ?? "",
            engine: json["engine"] as? String ?? ""
        )
    }
}

extension Snapshot {
    init?(daemonJSON json: [String: Any]) {
        guard let statusJSON = json["status"] as? [String: Any],
            let status = DaemonStatus(daemonJSON: statusJSON)
        else { return nil }
        self.init(
            status: status,
            plan: Self.items(json["plan"]),
            input: Self.items(json["input"]),
            history: Self.items(json["history"]),
            voices: json["voices"] as? [String] ?? [],
            speed: (json["settings"] as? [String: Any])?["speed"] as? Double ?? 1.0,
            playbackRate: (json["settings"] as? [String: Any])?["playback_rate"] as? Double
                ?? 1.0
        )
    }

    private static func items(_ value: Any?) -> [Utterance] {
        guard let rows = value as? [[String: Any]] else { return [] }
        return rows.compactMap(Utterance.init(daemonJSON:))
    }
}
