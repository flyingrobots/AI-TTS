// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// Observable daemon state for the popover. The tray is a thin client: it
// polls status and the queues, and every action is one protocol op.

import Foundation

@MainActor
final class AppState: ObservableObject {
    @Published var status: DaemonStatus?
    @Published var playbackQueue: [Utterance] = []
    @Published var inputQueue: [Utterance] = []
    @Published var history: [Utterance] = []
    @Published var voices: [String] = []
    @Published var reachable = false
    @Published var lastError: String?

    private let client: DaemonClient
    private let queue = DispatchQueue(label: "aitts.client", qos: .userInitiated)
    private var timer: Timer?

    init(client: DaemonClient = DaemonClient()) {
        self.client = client
    }

    func startPolling(interval: TimeInterval = 1.0) {
        stopPolling()
        refresh()
        let timer = Timer(timeInterval: interval, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    func stopPolling() {
        timer?.invalidate()
        timer = nil
    }

    func refresh() {
        queue.async { [client] in
            let status = (try? client.request(["op": "status"]))
                .flatMap(DaemonStatus.init(json:))
            let playback = Self.items(try? client.request(["op": "list", "queue": "playback"]))
            let input = Self.items(try? client.request(["op": "list", "queue": "input"]))
            let history = Self.items(try? client.request(["op": "history", "limit": 50]))
            let voices =
                (try? client.request(["op": "voices"]))?["voices"] as? [String] ?? []
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.reachable = status != nil
                self.status = status
                self.playbackQueue = playback
                self.inputQueue = input
                self.history = history
                if !voices.isEmpty { self.voices = voices }
            }
        }
    }

    private nonisolated static func items(_ response: [String: Any]?) -> [Utterance] {
        guard let rows = response?["items"] as? [[String: Any]] else { return [] }
        return rows.compactMap(Utterance.init(json:))
    }

    // MARK: - Actions (fire, then refresh)

    func send(_ payload: [String: Any]) {
        queue.async { [client] in
            var failure: String?
            do {
                _ = try client.request(payload)
            } catch let WireError.daemon(_, message) {
                failure = message
            } catch {
                failure = "daemon unreachable"
            }
            Task { @MainActor [weak self] in
                self?.lastError = failure
                self?.refresh()
            }
        }
    }

    func pause() { send(["op": "pause"]) }
    func resume() { send(["op": "resume"]) }
    func skip() { send(["op": "skip"]) }
    func rewind() { send(["op": "rewind"]) }
    func replay(_ id: String) { send(["op": "rewind", "to": id]) }
    func cancel(_ id: String) { send(["op": "cancel", "id": id]) }
    func setVoice(_ voice: String) { send(["op": "settings", "set": ["voice": voice]]) }
    func setSpeed(_ speed: Double) { send(["op": "settings", "set": ["speed": speed]]) }
    func say(_ text: String) { send(["op": "submit", "text": text, "source": "menubar"]) }
}
