// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// Observable daemon state for the popover. One `snapshot` request per refresh,
// an event subscription so queue changes land instantly, and a light poll only
// while the popover is open (it carries the live playback position).

import AITTSApplication
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
    @Published var captionsEnabled: Bool
    @Published var reachable = false
    @Published var lastError: String?

    private(set) var statusObservedAt = Date()
    private(set) var observedPlaybackRate: Double = 1.0

    /// The one user-facing queue: every clip that will play after the current one.
    var upcoming: [Utterance] {
        plan.filter { ["Queued", "Synthesizing", "Ready"].contains($0.state) }
    }

    private let speech: any SpeechServicePort
    private let documentEnqueuer: any DocumentEnqueueing
    private let currentSelectionEnqueuer: any CurrentSelectionEnqueueing
    private let clipboardEnqueuer: any ClipboardEnqueueing
    private let defaults: UserDefaults
    private let queue = DispatchQueue(label: "aitts.client", qos: .userInitiated)
    private var timer: Timer?
    private var eventThread: Thread?
    private let eventsFlag = AtomicFlag()
    private var priorApplicationProcessIdentifier: Int32?
    private var captionMigrationAttempted = false

    init(
        speech: any SpeechServicePort,
        documentEnqueuer: any DocumentEnqueueing,
        currentSelectionEnqueuer: any CurrentSelectionEnqueueing,
        clipboardEnqueuer: any ClipboardEnqueueing,
        defaults: UserDefaults
    ) {
        self.speech = speech
        self.documentEnqueuer = documentEnqueuer
        self.currentSelectionEnqueuer = currentSelectionEnqueuer
        self.clipboardEnqueuer = clipboardEnqueuer
        self.defaults = defaults
        self.captionsEnabled = defaults.bool(forKey: "captionsEnabled")
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
        queue.async { [speech] in
            let snapshot = try? speech.snapshot()
            let observedAt = Date()
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.reachable = snapshot != nil
                guard let snapshot else {
                    self.status = nil
                    return
                }
                self.statusObservedAt = observedAt
                self.observedPlaybackRate = snapshot.playbackRate
                self.status = snapshot.status
                self.plan = snapshot.plan
                self.history = snapshot.history
                self.speed = snapshot.speed
                self.playbackRate = snapshot.playbackRate
                self.applyCaptionSettings(snapshot)
                if !snapshot.voices.isEmpty { self.voices = snapshot.voices }
            }
        }
    }

    private func applyCaptionSettings(_ snapshot: Snapshot) {
        if snapshot.captionsEnabledConfigured {
            captionsEnabled = snapshot.captionsEnabled
            defaults.set(snapshot.captionsEnabled, forKey: "captionsEnabled")
            return
        }
        guard !captionMigrationAttempted,
            let legacy = defaults.object(forKey: "captionsEnabled") as? Bool
        else {
            if !captionMigrationAttempted { captionsEnabled = snapshot.captionsEnabled }
            return
        }
        captionMigrationAttempted = true
        captionsEnabled = legacy
        send(.setCaptionsEnabled(legacy))
    }

    // MARK: - Event stream (instant refresh on any state change)

    func startEventStream() {
        guard !eventsFlag.get() else { return }
        eventsFlag.set(true)
        let speech = self.speech
        let flag = eventsFlag
        let thread = Thread { [weak self] in
            while flag.get() {
                try? speech.subscribe(
                    shouldContinue: { flag.get() },
                    onChange: {
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

    private func send(_ command: SpeechCommand) {
        queue.async { [speech] in
            var failure: String?
            do {
                try speech.perform(command)
            } catch let SpeechServiceError.rejected(_, message) {
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

    func pause() { send(.pause) }
    func resume() { send(.resume) }
    func skip() { send(.skip) }
    func rewind() { send(.rewind(to: nil)) }
    func playNow(_ id: String) { send(.rewind(to: id)) }
    func cancel(_ id: String) { send(.cancel(id: id)) }
    func clearQueue() { send(.clearQueue) }
    func clearHistory() { send(.clearHistory) }
    func removeHistory(_ id: String) { send(.removeHistory(id: id)) }

    func enqueueFile(_ url: URL) {
        queue.async { [documentEnqueuer] in
            var failure: String?
            do {
                try documentEnqueuer.enqueueDocument(at: url)
            } catch let SpeechServiceError.rejected(_, message) {
                failure = message
            } catch {
                failure = error.localizedDescription
            }
            Task { @MainActor [weak self] in
                self?.lastError = failure
                self?.refresh()
            }
        }
    }

    func capturePriorApplication(processIdentifier: Int32?) {
        priorApplicationProcessIdentifier = processIdentifier
    }

    func enqueueCurrentSelection() {
        let processIdentifier = priorApplicationProcessIdentifier
        queue.async { [currentSelectionEnqueuer] in
            var failure: String?
            do {
                try currentSelectionEnqueuer.enqueueCurrentSelection(
                    from: processIdentifier)
            } catch let SpeechServiceError.rejected(_, message) {
                failure = message
            } catch {
                failure = error.localizedDescription
            }
            Task { @MainActor [weak self] in
                self?.lastError = failure
                self?.refresh()
            }
        }
    }

    func enqueueClipboard() {
        queue.async { [clipboardEnqueuer] in
            var failure: String?
            do {
                try clipboardEnqueuer.enqueueClipboard()
            } catch let SpeechServiceError.rejected(_, message) {
                failure = message
            } catch {
                failure = error.localizedDescription
            }
            Task { @MainActor [weak self] in
                self?.lastError = failure
                self?.refresh()
            }
        }
    }

    func reportFilePickerFailure(_ error: Error) {
        let cocoaError = error as NSError
        guard
            !(cocoaError.domain == NSCocoaErrorDomain
                && cocoaError.code == NSUserCancelledError)
        else { return }
        lastError = error.localizedDescription
    }

    func requeue(_ id: String, priority: RequeuePriority = .normal) {
        send(.requeue(id: id, priority: priority))
    }

    func reorderQueue(_ ids: [String]) {
        let byID = Dictionary(uniqueKeysWithValues: upcoming.map { ($0.id, $0) })
        guard ids.count == byID.count, ids.allSatisfy({ byID[$0] != nil }) else { return }
        let upcomingIDs = Set(byID.keys)
        plan = plan.filter { !upcomingIDs.contains($0.id) } + ids.compactMap { byID[$0] }
        send(.reorder(ids: ids))
    }
    func setVoice(_ voice: String) { send(.setVoice(voice)) }
    func setSpeed(_ speed: Double) { send(.setSynthesisSpeed(speed)) }
    func setPlaybackRate(_ rate: Double) {
        playbackRate = rate
        send(.setPlaybackRate(rate))
    }
    func setCaptionsEnabled(_ enabled: Bool) {
        captionMigrationAttempted = true
        captionsEnabled = enabled
        defaults.set(enabled, forKey: "captionsEnabled")
        send(.setCaptionsEnabled(enabled))
    }

    /// A liveness watchdog only. Caption preference never controls its cadence;
    /// daemon transition events drive the active-segment presentation.
    var backgroundPollingInterval: TimeInterval { 5.0 }

    func preview(_ voice: String) {
        // A fixed, generated sentence: genuinely public text.
        let submission = SpeechSubmission(
            text: "Hello. This is the voice \(voice.replacingOccurrences(of: "_", with: " ")).",
            contentFormat: .plainText,
            voice: voice,
            speed: nil,
            sensitivity: .public,
            priority: .urgent,
            source: "menubar-preview"
        )
        queue.async { [speech] in
            var failure: String?
            do {
                try speech.submit(submission)
            } catch let SpeechServiceError.rejected(_, message) {
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
}
