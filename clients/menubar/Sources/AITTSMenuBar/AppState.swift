// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// Observable daemon state for the popover. One `snapshot` request per refresh,
// an event subscription so queue changes land instantly, and a light poll only
// while the popover is open (it carries the live playback position).

import AITTSApplication
import AITTSMacAdapters
import AppKit
import UniformTypeIdentifiers
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
    @Published var showingComposer = false
    let composer: SpeechComposer
    @Published var status: DaemonStatus?
    @Published var plan: [Utterance] = []
    @Published var history: [Utterance] = []
    @Published var voices: [String] = []
    @Published var engines: [SpeechEngine] = []
    @Published var models: [LocalSpeechModel] = []
    @Published var speed: Double = 1.0
    @Published var playbackRate: Double = 1.0
    @Published var captionPosition: CaptionPosition
    @Published var captionsEnabled: Bool
    @Published var cachePurgeReceipt: CachePurgeReceipt? = nil
    @Published var purgingCachedAudio = false
    @Published var provenanceDetails: [String: String] = [:]
    @Published var voiceNotice: String?
    @Published var reportingID: String?
    @Published var reportMessage: String?
    @Published var showingStorage = false
    @Published var storageSnapshot: GeneratedStorageSnapshot?
    @Published var storageBusy = false
    @Published var storageMessage: String?
    @Published var runtime: DaemonRuntime?
    @Published var maintenanceInProgress = false
    @Published var reachable = false
    @Published var launchingDaemon = false
    @Published var daemonRecoveryError: String?
    @Published var lastError: String?
    @Published var failureNotice: SpeechFailureNotice?
    @Published var selectedTab: PlaybackTab = .queue
    private var knownFailedIDs: Set<String>?
    @Published var voiceAssignments: [VoiceAssignment] = []
    @Published var earconEnabled = false
    @Published var duckingEnabled = false
    @Published var duckingStatus = "Ducking is available while the menu-bar app is running."
    @Published var inputInterruptEnabled = true
    @Published var inputInterruptResume: InputInterruptResume = .manual
    /// The full text the listener asked to read, shown in its own window.
    @Published var readingFullText: FullTextSubject?

    private(set) var statusObservedAt = Date()
    private(set) var observedPlaybackRate: Double = 1.0

    /// The one user-facing queue: every clip that will play after the current one.
    var upcoming: [Utterance] {
        plan.filter {
            $0.id != status?.current?.id
                && ["Queued", "Synthesizing", "Ready", "Paused"].contains($0.state)
        }
    }

    /// Suspended clips must unwind before the pending plan can be rearranged.
    var canReorderQueue: Bool { !upcoming.contains { $0.state == "Paused" } }

    /// The hold the listener's own voice caused, if that is why speech stopped.
    var interruption: SpeechInterruption? { status?.interruption }

    /// Set while the engine is still fetching what it needs to speak at all.
    var enginePreparing: EnginePreparation? { status?.enginePreparing }

    /// Whether the current clip has chunks to step between.
    var currentIsChunked: Bool { (status?.current?.segmentCount ?? 1) > 1 }

    private let mediaDucking: MediaDuckingController?
    private let storageManager: any GeneratedStorageManaging
    private let evidenceExporter: any EvidenceExporting
    private let provenanceLoader: any ProvenanceLoading
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
        defaults: UserDefaults,
        evidenceExporter: any EvidenceExporting = UnixSocketSpeechService(),
        storageManager: any GeneratedStorageManaging = UnixSocketSpeechService(),
        provenanceLoader: (any ProvenanceLoading)? = nil,
        mediaDucking: MediaDuckingController? = nil
    ) {
        self.mediaDucking = mediaDucking
        self.composer = SpeechComposer(speech: speech)
        self.storageManager = storageManager
        self.evidenceExporter = evidenceExporter
        self.provenanceLoader = provenanceLoader ?? BackgroundProvenanceLoader(exporter: evidenceExporter)
        self.speech = speech
        self.documentEnqueuer = documentEnqueuer
        self.currentSelectionEnqueuer = currentSelectionEnqueuer
        self.clipboardEnqueuer = clipboardEnqueuer
        self.defaults = defaults
        self.captionPosition = CaptionPosition(rawValue: defaults.string(forKey: "captionPosition") ?? "") ?? .bottom
        self.captionsEnabled = defaults.bool(forKey: "captionsEnabled")
        mediaDucking?.onStatus = { [weak self] status in self?.duckingStatus = status }
    }

    func manageStorage(retentionDays: Int? = nil, deleting: [String]? = nil) {
        guard !storageBusy else { return }
        storageBusy = true
        storageMessage = nil
        let manager = storageManager
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            do {
                let snapshot = try manager.storage(retentionDays: retentionDays, deleting: deleting)
                Task { @MainActor [weak self] in
                    self?.storageSnapshot = snapshot
                    self?.storageMessage = snapshot.message
                    self?.storageBusy = false
                    self?.refresh()
                }
            } catch {
                Task { @MainActor [weak self] in
                    self?.storageBusy = false
                    self?.storageMessage = "Could not update generated files. Check the daemon and retry."
                }
            }
        }
    }

    func clearHistoryAndFiles() {
        let manager = storageManager
        queue.async { [weak self] in
            var failure: String?
            do { try manager.clearHistoryAndFiles() }
            catch let SpeechServiceError.rejected(_, message) { failure = message }
            catch { failure = "Could not clear history and generated files." }
            Task { @MainActor [weak self] in
                self?.lastError = failure
                self?.provenanceDetails = [:]
                self?.refresh()
            }
        }
    }

    func loadProvenance(_ id: String) {
        guard provenanceDetails[id] == nil else { return }
        provenanceDetails[id] = "Loading…"
        provenanceLoader.load(id) { [weak self] text in
            guard let self, self.history.contains(where: { $0.id == id }) else { return }
            self.provenanceDetails[id] = text
        }
    }

    func setCaptionPosition(_ position: CaptionPosition) {
        defaults.set(position.rawValue, forKey: "captionPosition")
        captionPosition = position
    }

    func openDataFolder() {
        NSWorkspace.shared.open(UnixSocketSpeechService.dataDirectory)
    }

    func report(_ item: Utterance) {
        guard reportingID == nil else { return }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.zip]
        panel.nameFieldStringValue = "AI-TTS-report-\(item.id)-\(Int(Date().timeIntervalSince1970)).zip"
        panel.title = "Save audio evidence"
        panel.message = "Includes this item's audio, source text, generation details, and playback logs. Saved locally for you to share."
        panel.prompt = "Save Report"
        panel.begin { [weak self] result in
            guard result == .OK, let destination = panel.url, let self else { return }
            self.reportingID = item.id
            self.reportMessage = nil
            let exporter = self.evidenceExporter
            DispatchQueue.global(qos: .userInitiated).async { [self] in
                do {
                    let warnings = try exporter.exportEvidence(id: item.id, destination: destination)
                    Task { @MainActor [weak self] in
                        self?.reportingID = nil
                        self?.reportMessage = warnings.isEmpty ? "Report saved." : "Report saved. Some older evidence or cached audio was unavailable; see manifest.json."
                        NSWorkspace.shared.activateFileViewerSelecting([destination])
                    }
                } catch {
                    let message: String
                    if case SpeechServiceError.rejected(_, let detail) = error { message = detail }
                    else { message = "Could not save the report. Check the daemon and try again." }
                    Task { @MainActor [weak self] in
                        self?.reportingID = nil
                        self?.reportMessage = message
                    }
                }
            }
        }
    }

    // MARK: - Refresh

    func launchDaemon() {
        guard !launchingDaemon else { return }
        launchingDaemon = true
        daemonRecoveryError = nil
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            var failure: String?
            do {
                try DaemonLauncher().launch()
            } catch {
                failure = error.localizedDescription
            }
            Task { @MainActor [weak self] in
                self?.launchingDaemon = false
                self?.daemonRecoveryError = failure
                self?.refresh()
            }
        }
    }

    func reloadModel() {
        guard !maintenanceInProgress else { return }
        maintenanceInProgress = true
        let exporter = evidenceExporter
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            var failure: String?
            do { try exporter.restartModel() }
            catch let SpeechServiceError.rejected(_, message) { failure = message }
            catch { failure = "Model reload failed." }
            Task { @MainActor [weak self] in
                self?.maintenanceInProgress = false
                self?.lastError = failure
                self?.refresh()
            }
        }
    }

    func restartDaemon() {
        guard !maintenanceInProgress else { return }
        maintenanceInProgress = true
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            var failure: String?
            do { try DaemonLauncher().restart() }
            catch { failure = error.localizedDescription }
            Task { @MainActor [weak self] in
                self?.maintenanceInProgress = false
                self?.lastError = failure
                self?.refresh()
            }
        }
    }

    func viewDaemonLogs() {
        let directory = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/AI-TTS")
        let log = directory.appendingPathComponent("daemon.log")
        let target = FileManager.default.fileExists(atPath: log.path) ? log : directory
        if !NSWorkspace.shared.open(target) {
            daemonRecoveryError = "No daemon logs are available yet. Launch the daemon first."
        }
    }

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
        queue.async { [speech, self] in
            let snapshot = try? speech.snapshot()
            let observedAt = Date()
            Task { @MainActor [weak self] in
                self?.applySnapshot(snapshot, observedAt: observedAt)
            }
        }
    }

    /// Apply the daemon's typed snapshot at the UI boundary, independently of transport scheduling.
    func applySnapshot(_ snapshot: Snapshot?, observedAt: Date = Date()) {
        self.reachable = snapshot != nil
        self.runtime = snapshot?.runtime
        guard let snapshot else {
            self.status = nil
            mediaDucking?.update(enabled: duckingEnabled, speaking: false, daemonPID: nil)
            return
        }
        self.statusObservedAt = observedAt
        self.observedPlaybackRate = snapshot.playbackRate
        self.status = snapshot.status
        self.plan = snapshot.plan
        self.engines = snapshot.engines
        self.models = snapshot.models
        self.history = snapshot.history
        let historyIDs = Set(snapshot.history.map(\.id))
        self.provenanceDetails = self.provenanceDetails.filter { historyIDs.contains($0.key) }
        self.observeFailures(snapshot.history)
        self.speed = snapshot.speed
        self.playbackRate = snapshot.playbackRate
        self.earconEnabled = snapshot.earconEnabled
        self.duckingEnabled = snapshot.duckingEnabled
        updateDucking()
        self.applyCaptionSettings(snapshot)
        self.voiceAssignments = snapshot.voiceAssignments
        self.inputInterruptEnabled = snapshot.inputInterruptEnabled
        self.inputInterruptResume = snapshot.inputInterruptResume
        if !snapshot.voices.isEmpty { self.voices = snapshot.voices }
    }

    private func updateDucking() {
        mediaDucking?.update(
            enabled: duckingEnabled,
            speaking: status?.playbackState == "playing",
            daemonPID: runtime.flatMap { Int32(exactly: $0.pid) }
        )
    }

    func retryDucking() {
        mediaDucking?.retry()
        updateDucking()
    }

    func stopDucking() { mediaDucking?.close() }

    func openAudioPrivacySettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture") {
            NSWorkspace.shared.open(url)
        }
    }

    private func observeFailures(_ history: [Utterance]) {
        let failed = history.filter { $0.state == "Failed" }
        let previous = knownFailedIDs
        knownFailedIDs = Set(failed.map(\.id))
        // First connection establishes a baseline; old History must not toast again.
        guard let previous, let item = failed.first(where: { !previous.contains($0.id) }) else { return }
        let notice = SpeechFailureNotice(id: item.id, detail: item.error ?? "The clip could not be generated or played.")
        lastError = "Speech failed: \(notice.detail)"
        failureNotice = notice
    }

    func dismissError() {
        failureNotice = nil
        lastError = nil
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
        queue.async { [speech, self] in
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
    func nextChunk() { send(.nextSegment) }
    func previousChunk() { send(.previousSegment) }
    func resumeWhenInputIdle() { send(.resumeWhenInputIdle) }
    func setEngine(_ name: String) { send(.setEngine(name)) }
    func installModel(_ name: String) { send(.installModel(name)) }
    func cancelModelSetup() { send(.cancelModelSetup) }
    func setEarconEnabled(_ enabled: Bool) {
        send(.setEarconEnabled(enabled))
    }
    func setDuckingEnabled(_ enabled: Bool) {
        send(.setDuckingEnabled(enabled))
    }
    func setInputInterruptEnabled(_ enabled: Bool) {
        inputInterruptEnabled = enabled
        send(.setInputInterruptEnabled(enabled))
    }
    func setInputInterruptResume(_ policy: InputInterruptResume) {
        inputInterruptResume = policy
        send(.setInputInterruptResume(policy))
    }
    func assignVoice(source: String, voice: String) {
        send(.assignVoice(source: source, voice: voice))
    }
    func releaseVoice(source: String) { send(.releaseVoice(source: source)) }

    /// Open the untruncated text of one clip in its own window.
    ///
    /// Confidential by default means it never goes to a file the listener did
    /// not ask for: the window reads what the snapshot already carries.
    func readFullText(of item: Utterance) {
        readingFullText = FullTextSubject(
            id: item.id,
            text: item.text,
            voice: item.voice,
            source: item.source,
            segmentCount: item.segmentCount,
            activeSegmentText: item.activeSegment?.text
        )
    }

    func closeFullText() { readingFullText = nil }

    func purgeCachedAudio() {
        purgingCachedAudio = true
        cachePurgeReceipt = nil
        queue.async { [speech, self] in
            var receipt: CachePurgeReceipt?
            var failure: String?
            do {
                receipt = try speech.purgeCachedAudio()
                if let receipt, receipt.failedFiles > 0 {
                    failure = "Could not remove \(receipt.failedFiles) cached audio file(s)."
                }
            } catch let SpeechServiceError.rejected(_, message) {
                failure = message
            } catch {
                failure = "daemon unreachable"
            }
            Task { @MainActor [weak self] in
                self?.cachePurgeReceipt = receipt
                self?.purgingCachedAudio = false
                self?.lastError = failure
                self?.refresh()
            }
        }
    }

    func enqueueFile(_ url: URL) {
        queue.async { [documentEnqueuer, self] in
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
        composer.priorApplication = processIdentifier
    }

    func enqueueCurrentSelection() {
        let processIdentifier = priorApplicationProcessIdentifier
        queue.async { [currentSelectionEnqueuer, self] in
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
        queue.async { [clipboardEnqueuer, self] in
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
        guard canReorderQueue else { return }
        let byID = Dictionary(uniqueKeysWithValues: upcoming.map { ($0.id, $0) })
        guard ids.count == byID.count, ids.allSatisfy({ byID[$0] != nil }) else { return }
        let upcomingIDs = Set(byID.keys)
        plan = plan.filter { !upcomingIDs.contains($0.id) } + ids.compactMap { byID[$0] }
        send(.reorder(ids: ids))
    }
    func setVoice(_ voice: String) {
        voiceNotice = nil
        queue.async { [self, speech] in
            do {
                try speech.perform(.setVoice(voice))
                Task { @MainActor [weak self] in
                    self?.lastError = nil
                    self?.voiceNotice = "Voice set to \(voice). New clips use this voice unless a caller or voice assignment overrides it."
                    self?.refresh()
                }
            } catch {
                Task { @MainActor [weak self] in self?.lastError = "Could not change voice." }
            }
        }
    }
    func setSpeed(_ speed: Double) { send(.setSynthesisSpeed(speed)) }
    func setPlaybackRate(_ rate: Double) {
        playbackRate = rate
        send(.setPlaybackRate(rate))
    }
    /// Shows History in the popover body, which the inline composer otherwise occupies.
    func revealHistory() {
        selectedTab = .history
        showingComposer = false
    }

    var composerToggleTitle: String { showingComposer ? "Close editor" : "Speak…" }

    var composerToggleHelp: String {
        showingComposer ? "Close the speech editor and keep the draft" : "Type, paste, or attach text to speak"
    }

    var captionControlLabel: String {
        captionsEnabled ? "CC: \(captionPosition.rawValue)" : "CC: Off"
    }

    func cycleCaptions() {
        if !captionsEnabled {
            setCaptionPosition(.bottom)
            setCaptionsEnabled(true)
        } else if captionPosition == .bottom {
            setCaptionPosition(.top)
        } else {
            setCaptionsEnabled(false)
        }
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
        queue.async { [speech, self] in
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
