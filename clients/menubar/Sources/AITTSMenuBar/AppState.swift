// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// Observable daemon state for the popover. One `snapshot` request per refresh,
// an event subscription so queue changes land instantly, and a light poll only
// while the popover is open (it carries the live playback position).

import Foundation

/// A lock-guarded bool shared between the main actor and the event thread.
final class AtomicFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var value = false

    func set(_ newValue: Bool) {
        lock.lock()
        value = newValue
        lock.unlock()
    }

    func get() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        return value
    }
}

@MainActor
final class AppState: ObservableObject {
    @Published var status: DaemonStatus?
    @Published var plan: [Utterance] = []
    @Published var history: [Utterance] = []
    @Published var voices: [String] = []
    @Published var speed: Double = 1.0
    @Published var playbackRate: Double = 1.0
    @Published var reachable = false
    @Published var lastError: String?

    /// The one user-facing queue: every clip that will play after the current one.
    var upcoming: [Utterance] {
        plan.filter { ["Queued", "Synthesizing", "Ready"].contains($0.state) }
    }

    private let client: DaemonClient
    private let queue = DispatchQueue(label: "aitts.client", qos: .userInitiated)
    private var timer: Timer?
    private var eventThread: Thread?
    private let eventsFlag = AtomicFlag()

    init(client: DaemonClient = DaemonClient()) {
        self.client = client
    }

    // MARK: - Refresh

    func startPolling(interval: TimeInterval) {
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
            let snapshot = (try? client.request(["op": "snapshot"]))
                .flatMap(Snapshot.init(json:))
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.reachable = snapshot != nil
                guard let snapshot else {
                    self.status = nil
                    return
                }
                self.status = snapshot.status
                self.plan = snapshot.plan
                self.history = snapshot.history
                self.speed = snapshot.speed
                self.playbackRate = snapshot.playbackRate
                if !snapshot.voices.isEmpty { self.voices = snapshot.voices }
            }
        }
    }

    // MARK: - Event stream (instant refresh on any state change)

    func startEventStream() {
        guard !eventsFlag.get() else { return }
        eventsFlag.set(true)
        let client = self.client
        let flag = eventsFlag
        let thread = Thread { [weak self] in
            while flag.get() {
                try? client.subscribe(
                    shouldContinue: { flag.get() },
                    onEvent: { _ in
                        Task { @MainActor [weak self] in self?.refresh() }
                    }
                )
                // Daemon gone or stream dropped: reflect it, then retry.
                Task { @MainActor [weak self] in self?.refresh() }
                Thread.sleep(forTimeInterval: 2.0)
            }
        }
        thread.name = "aitts.events"
        thread.start()
        eventThread = thread
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
    func playNow(_ id: String) { send(["op": "rewind", "to": id]) }
    func cancel(_ id: String) { send(["op": "cancel", "id": id]) }
    func clearQueue() { send(["op": "clear", "queue": "queue"]) }
    func clearHistory() { send(["op": "clear", "queue": "history"]) }
    func removeHistory(_ id: String) { send(["op": "remove_history", "id": id]) }

    func requeue(_ id: String, priority: RequeuePriority = .normal) {
        send(["op": "requeue", "id": id, "priority": priority.rawValue])
    }

    func reorderQueue(_ ids: [String]) {
        let byID = Dictionary(uniqueKeysWithValues: upcoming.map { ($0.id, $0) })
        guard ids.count == byID.count, ids.allSatisfy({ byID[$0] != nil }) else { return }
        let upcomingIDs = Set(byID.keys)
        plan = plan.filter { !upcomingIDs.contains($0.id) } + ids.compactMap { byID[$0] }
        send(["op": "reorder", "ids": ids])
    }
    func setVoice(_ voice: String) { send(["op": "settings", "set": ["voice": voice]]) }
    func setSpeed(_ speed: Double) { send(["op": "settings", "set": ["speed": speed]]) }
    func setPlaybackRate(_ rate: Double) {
        playbackRate = rate
        send(["op": "settings", "set": ["playback_rate": rate]])
    }

    func preview(_ voice: String) {
        // A fixed, generated sentence: genuinely public text.
        send([
            "op": "submit",
            "text": "Hello. This is the voice \(voice.replacingOccurrences(of: "_", with: " ")).",
            "voice": voice,
            "sensitivity": "public",
            "priority": "urgent",
            "source": "menubar-preview",
        ])
    }
}
