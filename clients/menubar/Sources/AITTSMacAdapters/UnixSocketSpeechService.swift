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
public struct UnixSocketSpeechService: SpeechServicePort, EvidenceExporting, GeneratedStorageManaging, Sendable {
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
        if let engine = submission.engine { payload["engine"] = engine }
        if let voice = submission.voice { payload["voice"] = voice }
        if let speed = submission.speed { payload["speed"] = speed }
        if let source = submission.source { payload["source"] = source }
        _ = try request(payload)
    }

    public func perform(_ command: SpeechCommand) throws {
        let payload: [String: Any]
        switch command {
        case .pause:
            payload = ["op": "pause", "origin": "menubar"]
        case .resume:
            payload = ["op": "resume", "origin": "menubar"]
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
        case .setEngine(let name):
            payload = ["op": "settings", "set": ["engine": name]]
        case .installModel(let name):
            payload = ["op": "model_setup", "name": name]
        case .cancelModelSetup:
            payload = ["op": "cancel_model_setup"]
        case .setVoice(let voice):
            payload = ["op": "settings", "set": ["voice": voice]]
        case .setSynthesisSpeed(let speed):
            payload = ["op": "settings", "set": ["speed": speed]]
        case .setPlaybackRate(let rate):
            payload = ["op": "settings", "set": ["playback_rate": rate]]
        case .setEarconEnabled(let enabled):
            payload = ["op": "settings", "set": ["earcon_enabled": enabled]]
        case .setDuckingEnabled(let enabled):
            payload = ["op": "settings", "set": ["ducking_enabled": enabled]]
        case .setCaptionsEnabled(let enabled):
            payload = ["op": "settings", "set": ["captions_enabled": enabled]]
        case .nextSegment:
            payload = ["op": "next_segment"]
        case .previousSegment:
            payload = ["op": "previous_segment"]
        case .resumeWhenInputIdle:
            payload = ["op": "resume_when_input_idle"]
        case .setInputInterruptEnabled(let enabled):
            payload = ["op": "settings", "set": ["input_interrupt_enabled": enabled]]
        case .setInputInterruptResume(let policy):
            payload = ["op": "settings", "set": ["input_interrupt_resume": policy.rawValue]]
        case .assignVoice(let source, let voice):
            payload = ["op": "assign_voice", "source": source, "voice": voice]
        case .releaseVoice(let source):
            // Stated, not implied: an absent voice is a mistake, not a request
            // to forget an assignment.
            payload = ["op": "assign_voice", "source": source, "release": true]
        }
        _ = try request(payload)
    }

    public static var dataDirectory: URL {
        URL(fileURLWithPath: WireProtocol.defaultSocketPath()).deletingLastPathComponent()
    }

    public func provenance(id: String) throws -> String {
        let response = try request(["op": "provenance", "id": id])
        guard let details = response["provenance"] as? [String: Any] else {
            throw SpeechServiceError.invalidResponse
        }
        func pretty(_ value: Any) -> String {
            guard JSONSerialization.isValidJSONObject(value),
                let data = try? JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys]),
                let text = String(data: data, encoding: .utf8) else { return "Not captured" }
            return text
        }
        var lines = ["From: \(details["origin"] as? String ?? "Unknown")",
                     "Caller: \(details["caller_source"] as? String ?? "—")",
                     "Resolved voice: \(details["resolved_voice"] as? String ?? "—")",
                     "Resolved speed: \(details["resolved_speed"] ?? "—")",
                     "Source BLAKE3 (UTF-8):", details["source_blake3"] as? String ?? "Not captured",
                     "", "Request arguments:", pretty(details["arguments"] ?? NSNull())]
        if let clips = details["clips"] as? [[String: Any]] {
            for (index, clip) in clips.enumerated() {
                let audio = clip["audio"] as? [String: Any]
                lines += ["", "Audio \(index + 1) BLAKE3:", audio?["blake3"] as? String ?? "Not captured",
                          "Generation and audio details:", pretty(clip)]
            }
        }
        return lines.joined(separator: "\n")
    }

    public func storage(retentionDays: Int? = nil, deleting: [String]? = nil) throws -> GeneratedStorageSnapshot {
        var payload: [String: Any] = ["op": "storage"]
        if let retentionDays { payload["retention_days"] = retentionDays }
        if let deleting { payload["delete"] = deleting }
        let response = try request(payload)
        guard let rows = response["entries"] as? [[String: Any]],
              let total = response["total_bytes"] as? Int64,
              let days = response["retention_days"] as? Int else { throw SpeechServiceError.invalidResponse }
        let entries = try rows.map { row -> GeneratedFile in
            guard let id = row["id"] as? String, let preview = row["preview"] as? String,
                  let bytes = row["bytes"] as? Int64, let modified = row["modified_at"] as? Double,
                  let protected = row["protected"] as? Bool else { throw SpeechServiceError.invalidResponse }
            return GeneratedFile(id: id, preview: preview, bytes: bytes, modifiedAt: modified, protected: protected)
        }
        let receipt = response["receipt"] as? [String: Int]
        let message = receipt.map { "Deleted \($0["removed"] ?? 0); protected \($0["protected"] ?? 0); failed \($0["failed"] ?? 0)." }
        return GeneratedStorageSnapshot(entries: entries, totalBytes: total, retentionDays: days, message: message)
    }

    public func clearHistoryAndFiles() throws {
        _ = try request(["op": "clear", "queue": "history", "delete_files": true])
    }

    public func restartModel() throws { _ = try request(["op": "restart_model"]) }

    public func exportEvidence(id: String, destination: URL) throws -> [String] {
        let response = try request(["op": "export_evidence", "id": id, "destination": destination.path])
        guard let warnings = response["warnings"] as? [String], response["path"] as? String == destination.path else {
            throw SpeechServiceError.invalidResponse
        }
        return warnings
    }

    public func purgeCachedAudio() throws -> CachePurgeReceipt {
        let response = try request(["op": "purge_cache"])
        guard let removedFiles = response["removed_files"] as? Int,
            let removedBytes = response["removed_bytes"] as? Int,
            let protectedFiles = response["protected_files"] as? Int,
            let protectedBytes = response["protected_bytes"] as? Int,
            let failedFiles = response["failed_files"] as? Int,
            let failedBytes = response["failed_bytes"] as? Int,
            [
                removedFiles,
                removedBytes,
                protectedFiles,
                protectedBytes,
                failedFiles,
                failedBytes,
            ].allSatisfy({ $0 >= 0 })
        else {
            throw SpeechServiceError.invalidResponse
        }
        return CachePurgeReceipt(
            removedFiles: removedFiles,
            removedBytes: removedBytes,
            protectedFiles: protectedFiles,
            protectedBytes: protectedBytes,
            failedFiles: failedFiles,
            failedBytes: failedBytes
        )
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

extension SpeechInterruption {
    init?(daemonJSON json: [String: Any]) {
        guard let reason = json["reason"] as? String else { return nil }
        // NSNumber, not Double: a whole-numbered timestamp decodes as an
        // integer and `as? Double` would quietly yield zero.
        self.init(
            reason: reason,
            at: (json["at"] as? NSNumber)?.doubleValue ?? 0,
            resumeArmed: json["resume_armed"] as? Bool ?? false
        )
    }
}

extension EnginePreparation {
    init?(daemonJSON json: [String: Any]) {
        // A banner that names no asset tells the listener less than no banner.
        guard let asset = json["asset"] as? String, !asset.isEmpty else { return nil }
        // NSNumber, not Double: a whole-numbered timestamp decodes as an
        // integer and `as? Double` would quietly yield zero.
        self.init(asset: asset, since: (json["since"] as? NSNumber)?.doubleValue ?? 0)
    }
}

extension VoiceAssignment {
    init?(daemonJSON json: [String: Any]) {
        guard let source = json["source"] as? String,
            let voice = json["voice"] as? String
        else { return nil }
        self.init(
            source: source,
            voice: voice,
            pinned: json["pinned"] as? Bool ?? false,
            assignedAt: (json["assigned_at"] as? NSNumber)?.doubleValue ?? 0
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
            engine: json["engine"] as? String ?? "",
            inputActive: json["input_active"] as? Bool,
            interruption: (json["interruption"] as? [String: Any])
                .flatMap(SpeechInterruption.init(daemonJSON:)),
            enginePreparing: (json["engine_preparing"] as? [String: Any])
                .flatMap(EnginePreparation.init(daemonJSON:))
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
                ?? 1.0,
            earconEnabled: (json["settings"] as? [String: Any])?["earcon_enabled"] as? Bool ?? false,
            duckingEnabled: (json["settings"] as? [String: Any])?["ducking_enabled"] as? Bool ?? false,
            captionsEnabled: (json["settings"] as? [String: Any])?["captions_enabled"]
                as? Bool ?? false,
            captionsEnabledConfigured: (json["settings"] as? [String: Any])?[
                "captions_enabled_configured"
            ] as? Bool ?? false,
            voiceAssignments: Self.assignments(json["voice_assignments"]),
            inputInterruptEnabled: (json["settings"] as? [String: Any])?[
                "input_interrupt_enabled"
            ] as? Bool ?? true,
            inputInterruptResume: InputInterruptResume(
                rawValue: (json["settings"] as? [String: Any])?["input_interrupt_resume"]
                    as? String ?? ""
            ) ?? .manual,
            runtime: (json["runtime"] as? [String: Any]).flatMap { row in
                guard let pid = row["pid"] as? Int, let uptime = row["uptime_seconds"] as? Double,
                      let model = row["model_state"] as? String, let jobs = row["active_synthesis"] as? Int else { return nil }
                return DaemonRuntime(pid: pid, uptimeSeconds: uptime, modelState: model, activeSynthesis: jobs)
            },
            engines: (json["engines"] as? [[String: Any]] ?? []).compactMap { row in
                guard let name = row["name"] as? String,
                      let isLocal = row["is_local"] as? Bool,
                      let voices = row["voices"] as? [String],
                      let state = row["state"] as? String else { return nil }
                return SpeechEngine(name: name, isLocal: isLocal, voices: voices, state: state)
            },
            models: (json["models"] as? [[String: Any]] ?? []).compactMap { row in
                guard let name = row["name"] as? String, let title = row["title"] as? String,
                      let description = row["description"] as? String,
                      let installed = row["installed"] as? Bool, let selected = row["selected"] as? Bool,
                      let state = row["state"] as? String else { return nil }
                return LocalSpeechModel(name: name, title: title, description: description,
                    installed: installed, selected: selected, state: state,
                    message: row["message"] as? String ?? "", incompatible: row["incompatible"] as? String)
            }
        )
    }

    private static func items(_ value: Any?) -> [Utterance] {
        guard let rows = value as? [[String: Any]] else { return [] }
        return rows.compactMap(Utterance.init(daemonJSON:))
    }

    private static func assignments(_ value: Any?) -> [VoiceAssignment] {
        guard let rows = value as? [[String: Any]] else { return [] }
        return rows.compactMap(VoiceAssignment.init(daemonJSON:))
    }
}
