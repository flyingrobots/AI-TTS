// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// One playback surface: the current clip stays pinned above a Queue/History
// switcher. Queue is the exact upcoming playback plan, regardless of synthesis
// state. History is newest-first and keeps original priority as provenance.

import AITTSApplication
import AITTSMacAdapters
import AppKit
import SwiftUI

enum PlaybackTab: String, CaseIterable {
    case queue = "Queue"
    case history = "History"
}

// MARK: - Shell

struct PopoverView: View {
    @EnvironmentObject var state: AppState
    @State private var tab: PlaybackTab = .queue
    @State private var showingSettings = false

    var body: some View {
        VStack(spacing: 0) {
            PopoverHeader(showingSettings: $showingSettings)
            Divider()
            if state.reachable {
                EnginePreparationBanner()
                InterruptionNotice()
                CurrentPlaybackCard()
                PlaybackTabBar(selected: $tab)
                Divider()
                Group {
                    switch tab {
                    case .queue: QueueView()
                    case .history: HistoryView()
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                Divider()
                ModelHealthFooter()
            } else {
                UnreachableView()
            }
        }
        .frame(width: 368, height: 500)
        .onAppear { state.startPolling(interval: 0.5) }
        .onDisappear { state.stopPolling() }
        .sheet(isPresented: $showingSettings) {
            SettingsSheet(isPresented: $showingSettings)
                .environmentObject(state)
        }
    }
}

/// Why nothing is being spoken on a fresh install.
///
/// The engine's weights are around 330 MB and arrive on first use. Until then
/// a clip sits in Synthesizing, which is exactly what a wedged daemon looks
/// like — so the wait says what it is waiting for.
struct EnginePreparationBanner: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        if let preparing = state.enginePreparing {
            let notice = EnginePreparationNotice(preparing: preparing)
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    ProgressView()
                        .controlSize(.small)
                    Text(notice.title)
                        .font(.caption.weight(.semibold))
                    Spacer()
                }
                Text(notice.detail)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.accentColor.opacity(0.10), in: RoundedRectangle(cornerRadius: 9))
            .padding(.horizontal, 10)
            .padding(.top, 8)
            // Read as one element: a listener who cannot see the spinner still
            // needs to hear that the silence has a reason and an end.
            .accessibilityElement(children: .combine)
            .accessibilityLabel("\(notice.title). \(notice.detail)")
        }
    }
}

/// Why speech stopped, when it stopped because the listener started talking.
///
/// Without this the hold is indistinguishable from a pause they set and forgot
/// — silence with nothing on screen to explain it.
struct InterruptionNotice: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        if let interruption = state.interruption {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 6) {
                    Image(systemName: "mic.fill")
                        .font(.system(size: 10, weight: .semibold))
                    Text("PLAYBACK INTERRUPTED")
                        .font(.caption2.smallCaps().weight(.semibold))
                    Spacer()
                    if state.status?.inputActive == true {
                        Text("mic in use")
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.tertiary)
                    }
                }
                .foregroundStyle(.orange)

                Text(
                    interruption.resumeArmed
                        ? "You started speaking. Playback will continue once your mic goes quiet."
                        : "You started speaking, so playback stopped and is waiting for you."
                )
                .font(.caption)
                .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: 8) {
                    Button("Resume") { state.resume() }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.small)
                    Button("Resume when mic is cold") { state.resumeWhenInputIdle() }
                        .controlSize(.small)
                        .disabled(interruption.resumeArmed)
                        .help(
                            interruption.resumeArmed
                                ? "Already waiting for your mic to go quiet"
                                : "Continue by itself once nothing is using the mic"
                        )
                    Button("Skip") { state.skip() }
                        .controlSize(.small)
                        .help("Give up on this clip and move on")
                }
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.orange.opacity(0.11), in: RoundedRectangle(cornerRadius: 9))
            .overlay(
                RoundedRectangle(cornerRadius: 9)
                    .strokeBorder(Color.orange.opacity(0.35), lineWidth: 1)
            )
            .padding(.horizontal, 10)
            .padding(.top, 8)
            // The one message in this app that must arrive without being
            // looked for: playback stopped because the listener started
            // speaking. A screen-reader user given no announcement simply
            // hears silence and no reason for it.
            .accessibilityElement(children: .combine)
            .accessibilityAddTraits(.isSummaryElement)
            .onAppear { announce(interruption) }
        }
    }

    private func announce(_ interruption: SpeechInterruption) -> Void {
        let message =
            interruption.resumeArmed
            ? "Playback interrupted. It will continue once your microphone goes quiet."
            : "Playback interrupted because you started speaking. It is waiting for you."
        NSAccessibility.post(
            element: NSApp as Any,
            notification: .announcementRequested,
            userInfo: [
                .announcement: message,
                .priority: NSAccessibilityPriorityLevel.high.rawValue,
            ]
        )
    }
}

struct PopoverHeader: View {
    @EnvironmentObject var state: AppState
    @Binding var showingSettings: Bool

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "waveform.circle.fill")
                .font(.title3)
                .foregroundStyle(Color.accentColor)
            VStack(alignment: .leading, spacing: 1) {
                Text("AI-TTS").font(.headline)
                Text(statusLabel)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button {
                showingSettings = true
            } label: {
                Image(systemName: "gearshape")
                    .frame(width: 24, height: 24)
            }
            .buttonStyle(.borderless)
            .help("Settings")
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }

    private var statusLabel: String {
        guard state.reachable else { return "Daemon unavailable" }
        switch state.status?.playbackState {
        case "playing": return "Speaking"
        case "paused": return "Playback paused"
        case "synthesizing": return "Preparing speech"
        default: return "Ready"
        }
    }
}

struct PlaybackTabBar: View {
    @Binding var selected: PlaybackTab

    var body: some View {
        HStack(spacing: 3) {
            ForEach(PlaybackTab.allCases, id: \.self) { tab in
                Button {
                    selected = tab
                } label: {
                    Text(tab.rawValue)
                        .font(.caption.weight(.semibold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 5)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .foregroundStyle(selected == tab ? Color.accentColor : Color.secondary)
                .background(
                    selected == tab ? Color.accentColor.opacity(0.16) : Color.clear,
                    in: RoundedRectangle(cornerRadius: 5)
                )
                .accessibilityAddTraits(selected == tab ? .isSelected : [])
            }
        }
        .padding(3)
        .background(Color.primary.opacity(0.055), in: RoundedRectangle(cornerRadius: 7))
        .padding(.horizontal, 12)
        .padding(.vertical, 7)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Playback view")
    }
}

struct UnreachableView: View {
    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: "exclamationmark.bubble").font(.largeTitle)
            Text("The daemon is not running").font(.headline)
            Text("Start it with:  ai-tts daemon")
                .font(.system(.caption, design: .monospaced))
        }
        .foregroundStyle(.secondary)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Current playback

struct CurrentPlaybackCard: View {
    @EnvironmentObject var state: AppState

    private var current: Utterance? { state.status?.current }
    private var isPaused: Bool { state.status?.playbackState == "paused" }

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text(isPaused ? "PLAYBACK PAUSED" : current == nil ? "CURRENT" : "NOW SPEAKING")
                    .font(.caption2.smallCaps().weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                if let current {
                    Text(current.voice)
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(.tertiary)
                }
                Button {
                    isPaused ? state.resume() : state.pause()
                } label: {
                    Label(
                        isPaused ? "RESUME" : "PAUSE",
                        systemImage: isPaused ? "play.fill" : "pause.fill"
                    )
                    .font(.system(size: 10, weight: .semibold))
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
                .help(
                    isPaused
                        ? "Resume all playback"
                        : "Pause all playback; incoming clips will stay queued"
                )
            }

            if let current {
                Button {
                    state.readFullText(of: current)
                } label: {
                    Text(current.text)
                        .font(.system(size: 13, weight: .medium))
                        .lineLimit(3)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.plain)
                .help("Read the whole thing in its own window")
                chunkProgress(for: current)
                progress(for: current)
                HStack(spacing: 14) {
                    ForEach(TransportAction.allCases, id: \.self) { action in
                        if !action.needsChunks || current.segmentCount > 1 {
                            transportButton(action, current: current)
                        }
                    }
                    Spacer()
                    Button {
                        state.setCaptionsEnabled(!state.captionsEnabled)
                    } label: {
                        Image(
                            systemName: state.captionsEnabled
                                ? "captions.bubble.fill" : "captions.bubble")
                    }
                    .help(state.captionsEnabled ? "Hide on-screen captions" : "Show on-screen captions")
                    .accessibilityLabel(
                        state.captionsEnabled ? "Hide on-screen captions" : "Show on-screen captions")
                    Picker("Playback speed", selection: playbackRate) {
                        ForEach(PlaybackRate.allCases, id: \.self) { rate in
                            Text(rate.label).tag(rate)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(width: 72)
                    .help("Change playback speed immediately")
                    .accessibilityLabel("Playback speed")
                }
                .labelStyle(.iconOnly)
                .buttonStyle(.borderless)
            } else {
                Text(isPaused ? "All playback is paused" : "Nothing is playing")
                    .font(.system(size: 13, weight: .medium))
                Text(
                    isPaused
                        ? "Incoming clips will stay in Queue until you resume."
                        : "Queued clips will begin here in playback order."
                )
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.primary.opacity(0.045), in: RoundedRectangle(cornerRadius: 9))
        .padding(.horizontal, 10)
        .padding(.top, 8)
    }

    /// One transport control, labelled and keyed from its action.
    @ViewBuilder
    private func transportButton(_ action: TransportAction, current: Utterance) -> some View {
        Button {
            switch action {
            case .restart: state.rewind()
            case .previousChunk: state.previousChunk()
            case .nextChunk: state.nextChunk()
            case .skip: state.skip()
            case .fullText: state.readFullText(of: current)
            }
        } label: {
            Label(action.label, systemImage: action.systemImage)
        }
        .disabled(isDisabled(action, current: current))
        .keyboardShortcut(action.shortcut, modifiers: [])
        .help(helpText(action))
        .accessibilityLabel(action.label)
    }

    private func isDisabled(_ action: TransportAction, current: Utterance) -> Bool {
        switch action {
        case .fullText, .skip:
            return false
        case .restart:
            return isPaused
        case .previousChunk:
            return isPaused || (current.activeSegment?.index ?? 0) == 0
        case .nextChunk:
            return isPaused || isOnLastChunk(current)
        }
    }

    private func helpText(_ action: TransportAction) -> String {
        if isPaused, action == .restart || action.needsChunks {
            return "Resume playback before using \(action.label.lowercased())"
        }
        return action.label
    }

    /// Elapsed and total time as words, because a bar conveys nothing spoken.
    private func spokenProgress(position: Int, duration: Int) -> String {
        let elapsed = Int((Double(position) / 1000).rounded())
        let total = Int((Double(duration) / 1000).rounded())
        return "\(elapsed) seconds of \(total)"
    }

    private func isOnLastChunk(_ current: Utterance) -> Bool {
        guard let active = current.activeSegment else { return true }
        return active.index >= current.segmentCount - 1
    }

    /// Which chunk of a document is being heard, and how many there are.
    @ViewBuilder
    private func chunkProgress(for current: Utterance) -> some View {
        if let active = current.activeSegment, current.segmentCount > 1 {
            HStack(spacing: 5) {
                Text("Chunk \(active.number) of \(active.count)")
                    .font(.system(.caption2, design: .monospaced))
                    .foregroundStyle(.secondary)
                // Array, not a Range: ForEach reads only a Range's initial
                // count, and this one changes with every clip.
                ForEach(Array(0..<current.segmentCount), id: \.self) { index in
                    Capsule()
                        .fill(
                            index == active.index
                                ? Color.accentColor
                                : Color.primary.opacity(index < active.index ? 0.28 : 0.12)
                        )
                        .frame(height: 3)
                }
            }
            // The pips restate the counter beside them; announcing both would
            // read the same fact twice.
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Chunk \(active.number) of \(active.count)")
        }
    }

    private var playbackRate: Binding<PlaybackRate> {
        Binding(
            get: { PlaybackRate(rawValue: state.playbackRate) ?? .normal },
            set: { state.setPlaybackRate($0.rawValue) }
        )
    }

    @ViewBuilder
    private func progress(for current: Utterance) -> some View {
        if let duration = current.durationMs, duration > 0 {
            let position = current.positionMs ?? current.playedMs ?? 0
            VStack(spacing: 2) {
                ProgressView(
                    value: min(Double(position), Double(duration)),
                    total: Double(duration)
                )
                .accessibilityLabel("Playback progress")
                .accessibilityValue(spokenProgress(position: position, duration: duration))
                HStack {
                    Text(clock(position))
                    Spacer()
                    Text(clock(duration))
                }
                .font(.system(.caption2, design: .monospaced))
                .foregroundStyle(.secondary)
            }
        }
    }
}

// MARK: - Unified queue

struct QueueView: View {
    @EnvironmentObject var state: AppState
    @State private var confirmingClear = false
    @State private var showingFileImporter = false

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(queueSummary)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Menu {
                    Button("Read Current Selection…") {
                        state.enqueueCurrentSelection()
                    }
                    Button("Read Clipboard") {
                        state.enqueueClipboard()
                    }
                    Divider()
                    Button("Read File…") {
                        showingFileImporter = true
                    }
                } label: {
                    Label("Read…", systemImage: "text.badge.plus")
                }
                .menuStyle(.borderlessButton)
                .help("Read selected text, clipboard text, or a document")
                Button("Clear queue…") { confirmingClear = true }
                    .buttonStyle(.borderless)
                    .disabled(state.upcoming.isEmpty)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)

            Divider()

            if state.upcoming.isEmpty {
                EmptyPane(
                    icon: "text.line.first.and.arrowtriangle.forward",
                    title: "Queue is empty",
                    detail: "New clips will appear here in playback order."
                )
            } else {
                List {
                    ForEach(state.upcoming) { item in
                        QueueRow(item: item)
                    }
                    .onMove(perform: move)
                }
                .listStyle(.plain)
            }
        }
        .confirmationDialog(
            "Clear the queue?",
            isPresented: $confirmingClear,
            titleVisibility: .visible
        ) {
            Button("Clear Queue", role: .destructive) { state.clearQueue() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Every upcoming clip, including clips being synthesized, will be cancelled. The current clip will keep playing.")
        }
        .fileImporter(
            isPresented: $showingFileImporter,
            allowedContentTypes: LocalSpeechDocumentReader.allowedContentTypes,
            allowsMultipleSelection: false
        ) { result in
            switch result {
            case .success(let urls):
                if let url = urls.first { state.enqueueFile(url) }
            case .failure(let error):
                state.reportFilePickerFailure(error)
            }
        }
    }

    private var queueSummary: String {
        let count = state.upcoming.count
        let urgent = state.upcoming.filter { $0.priority == .urgent }.count
        let noun = count == 1 ? "clip" : "clips"
        return urgent == 0 ? "\(count) upcoming \(noun)" : "\(count) upcoming · \(urgent) urgent"
    }

    private func move(from offsets: IndexSet, to destination: Int) {
        var reordered = state.upcoming
        reordered.move(fromOffsets: offsets, toOffset: destination)
        state.reorderQueue(reordered.map(\.id))
    }
}

struct QueueRow: View {
    @EnvironmentObject var state: AppState
    let item: Utterance

    var body: some View {
        HStack(alignment: .center, spacing: 8) {
            Image(systemName: "line.3.horizontal")
                .font(.caption)
                .foregroundStyle(.tertiary)
                .help("Drag to reorder")
            VStack(alignment: .leading, spacing: 4) {
                Text(item.text)
                    .font(.system(size: 12))
                    .lineLimit(2)
                HStack(spacing: 6) {
                    StatePill(state: item.state)
                    if item.priority == .urgent {
                        PriorityBadge()
                    }
                    Text(item.voice)
                        .font(.system(size: 9, design: .monospaced))
                        .foregroundStyle(.tertiary)
                }
            }
            Spacer(minLength: 4)
            Button {
                state.cancel(item.id)
            } label: {
                Image(systemName: "xmark.circle")
            }
            .buttonStyle(.borderless)
            .help("Remove from queue")
        }
        .padding(.vertical, 2)
    }
}

struct StatePill: View {
    let state: String

    var body: some View {
        Text(label)
            .font(.caption2.weight(.medium))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.16), in: Capsule())
            .foregroundStyle(color)
    }

    private var label: String {
        state == "Synthesizing" ? "Synthesizing…" : state
    }

    private var color: Color {
        switch state {
        case "Ready": return .green
        case "Synthesizing": return .orange
        case "Failed": return .red
        default: return .secondary
        }
    }
}

struct PriorityBadge: View {
    var body: some View {
        Text("↑ Urgent")
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(Color.blue.opacity(0.14), in: Capsule())
            .foregroundStyle(Color.blue)
    }
}

// MARK: - History

struct HistoryView: View {
    @EnvironmentObject var state: AppState
    @State private var query = ""
    @State private var confirmingClear = false

    private var filtered: [Utterance] {
        guard !query.isEmpty else { return state.history }
        return state.history.filter { $0.text.localizedCaseInsensitiveContains(query) }
    }

    private var groups: [(day: String, items: [Utterance])] {
        let calendar = Calendar.current
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        var ordered: [(String, [Utterance])] = []
        for item in filtered {
            let date = Date(timeIntervalSince1970: item.finishedAt ?? item.enqueuedAt ?? 0)
            let day =
                calendar.isDateInToday(date)
                ? "Today"
                : calendar.isDateInYesterday(date)
                    ? "Yesterday" : formatter.string(from: date)
            if ordered.last?.0 == day {
                ordered[ordered.count - 1].1.append(item)
            } else {
                ordered.append((day, [item]))
            }
        }
        return ordered.map { (day: $0.0, items: $0.1) }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                TextField("Search history", text: $query)
                    .textFieldStyle(.roundedBorder)
                Button("Clear history…") { confirmingClear = true }
                    .buttonStyle(.borderless)
                    .disabled(state.history.isEmpty)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 6)

            Divider()

            if filtered.isEmpty {
                EmptyPane(
                    icon: "clock.arrow.circlepath",
                    title: query.isEmpty ? "Nothing spoken yet" : "No matches",
                    detail: query.isEmpty
                        ? "Finished clips will appear newest-first."
                        : "\(state.history.count) clips remain in history."
                )
            } else {
                List {
                    ForEach(groups, id: \.day) { group in
                        Section {
                            ForEach(group.items) { item in
                                HistoryRow(item: item)
                            }
                        } header: {
                            Text(group.day).font(.caption2.smallCaps())
                        }
                    }
                }
                .listStyle(.plain)
            }
        }
        .confirmationDialog(
            "Clear history?",
            isPresented: $confirmingClear,
            titleVisibility: .visible
        ) {
            Button("Clear History", role: .destructive) { state.clearHistory() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("History records will be removed. Cached audio remains managed separately.")
        }
    }
}

struct HistoryRow: View {
    @EnvironmentObject var state: AppState
    let item: Utterance

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter
    }()

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .top, spacing: 7) {
                Text(time)
                    .font(.system(.caption2, design: .monospaced))
                    .foregroundStyle(.tertiary)
                    .frame(width: 34, alignment: .leading)
                Button {
                    state.readFullText(of: item)
                } label: {
                    Text(item.text)
                        .font(.system(size: 12))
                        .lineLimit(2)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.plain)
                .help("Read the whole thing in its own window")
                Spacer(minLength: 2)
                if item.segmentCount > 1 {
                    Text("\(item.segmentCount)◦")
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(.tertiary)
                        .help("\(item.segmentCount) chunks")
                }
                Button {
                    state.readFullText(of: item)
                } label: {
                    Image(systemName: "text.alignleft")
                }
                .buttonStyle(.borderless)
                .help("Read the whole thing in its own window")
                Button {
                    state.removeHistory(item.id)
                } label: {
                    Image(systemName: "xmark.circle")
                }
                .buttonStyle(.borderless)
                .help("Remove from history")
            }

            HStack(spacing: 6) {
                Text(detail)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                if item.priority == .urgent {
                    PriorityBadge()
                }
                Spacer()
                RequeueControl(id: item.id)
            }
            .padding(.leading, 41)

            if let error = item.error {
                Text(error)
                    .font(.caption2)
                    .foregroundStyle(.red)
                    .padding(.leading, 41)
            }
        }
        .padding(.vertical, 2)
    }

    private var time: String {
        guard let at = item.finishedAt ?? item.enqueuedAt else { return "–" }
        return Self.timeFormatter.string(from: Date(timeIntervalSince1970: at))
    }

    private var detail: String {
        let final = item.finalState ?? item.state
        if final == "Skipped", let played = item.playedMs, let total = item.durationMs {
            return "Skipped at \(clock(played)) of \(clock(total))"
        }
        if let source = item.source {
            return "\(final) · \(source)"
        }
        return final
    }
}

struct RequeueControl: View {
    @EnvironmentObject var state: AppState
    let id: String

    var body: some View {
        HStack(spacing: 0) {
            Button("Re-queue") {
                state.requeue(id)
            }
            .buttonStyle(.plain)
            .padding(.leading, 7)
            .padding(.trailing, 5)
            .padding(.vertical, 3)
            .help("Add to end of Queue")

            Divider().frame(height: 17)

            Menu {
                Button {
                    state.requeue(id, priority: .normal)
                } label: {
                    Label("Normal — Add to end of Queue", systemImage: "checkmark")
                }
                Button("Urgent — Play next after current") {
                    state.requeue(id, priority: .urgent)
                }
            } label: {
                Image(systemName: "chevron.down")
                    .font(.system(size: 9, weight: .semibold))
                    .frame(width: 20, height: 20)
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
            .help("Choose re-queue urgency")
        }
        .background(Color.primary.opacity(0.06), in: RoundedRectangle(cornerRadius: 5))
        .overlay {
            RoundedRectangle(cornerRadius: 5)
                .stroke(Color.primary.opacity(0.12), lineWidth: 0.5)
        }
        .controlSize(.small)
    }
}

// MARK: - Settings

struct SettingsSheet: View {
    @Binding var isPresented: Bool

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Settings").font(.headline)
                Spacer()
                Button("Done") { isPresented = false }
                    .keyboardShortcut(.defaultAction)
            }
            .padding(12)
            Divider()
            SettingsView()
        }
        .frame(width: 340, height: 430)
    }
}

struct SettingsView: View {
    @EnvironmentObject var state: AppState
    @State private var draftSpeed: Double?
    @State private var confirmingCachePurge = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Default voice").font(.caption.smallCaps()).foregroundStyle(.secondary)
                Text("Used for anything you read yourself, and for clients with no voice of their own.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                ForEach(VoiceLanguage.groups(of: state.voices), id: \.name) { group in
                    Text(group.name)
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.tertiary)
                    VStack(spacing: 0) {
                        ForEach(group.voices, id: \.self) { voice in
                            VoiceRow(voice: voice, selected: voice == state.status?.voice)
                            if voice != group.voices.last { Divider() }
                        }
                    }
                    .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 8))
                }

                Divider()

                Text("Agent voices").font(.caption.smallCaps()).foregroundStyle(.secondary)
                AgentVoiceSettings()

                Divider()

                Text("When you speak").font(.caption.smallCaps()).foregroundStyle(.secondary)
                InputInterruptSettings()

                Text("Voice generation speed")
                    .font(.caption.smallCaps())
                    .foregroundStyle(.secondary)
                HStack {
                    Slider(
                        value: Binding(
                            get: { draftSpeed ?? state.speed },
                            set: { draftSpeed = $0 }
                        ),
                        in: 0.5...2.0
                    ) { editing in
                        if !editing, let speed = draftSpeed {
                            state.setSpeed((speed * 20).rounded() / 20)
                            draftSpeed = nil
                        }
                    }
                    Text(String(format: "%.2f×", draftSpeed ?? state.speed))
                        .font(.system(.caption, design: .monospaced))
                        .frame(width: 44, alignment: .trailing)
                }

                Toggle(
                    "On-screen captions",
                    isOn: Binding(
                        get: { state.captionsEnabled },
                        set: { state.setCaptionsEnabled($0) }
                    )
                )
                Text("Shows the exact segment currently being spoken without taking focus.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Text("Storage").font(.caption.smallCaps()).foregroundStyle(.secondary)
                VStack(alignment: .leading, spacing: 7) {
                    Button("Purge Cached Audio…", role: .destructive) {
                        confirmingCachePurge = true
                    }
                    .disabled(state.purgingCachedAudio)

                    Text(
                        "Removes reusable speech audio. History text remains, and audio needed "
                            + "by current or queued speech is kept."
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)

                    if state.purgingCachedAudio {
                        ProgressView("Purging cached audio…")
                            .controlSize(.small)
                    } else if let receipt = state.cachePurgeReceipt {
                        Text(cachePurgeSummary(receipt))
                            .font(.caption)
                            .foregroundStyle(
                                receipt.failedFiles == 0 ? Color.secondary : Color.red)
                    }
                }

                Divider()
                Button("Quit AI-TTS Menu Bar") { NSApp.terminate(nil) }
            }
            .padding(12)
        }
        .confirmationDialog(
            "Purge cached audio?",
            isPresented: $confirmingCachePurge,
            titleVisibility: .visible
        ) {
            Button("Purge Cached Audio", role: .destructive) { state.purgeCachedAudio() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(
                "Reusable and orphaned audio will be deleted. Files needed by current or "
                    + "queued speech are kept so playback is not interrupted. History text remains."
            )
        }
    }

    private func cachePurgeSummary(_ receipt: CachePurgeReceipt) -> String {
        let removed = ByteCountFormatter.string(
            fromByteCount: Int64(receipt.removedBytes), countStyle: .file)
        let protected = ByteCountFormatter.string(
            fromByteCount: Int64(receipt.protectedBytes), countStyle: .file)
        let failed = ByteCountFormatter.string(
            fromByteCount: Int64(receipt.failedBytes), countStyle: .file)
        return "Last purge: removed \(fileCount(receipt.removedFiles)), \(removed); "
            + "kept \(fileCount(receipt.protectedFiles)) needed for playback, \(protected); "
            + "\(failureCount(receipt.failedFiles)), \(failed)."
    }

    private func fileCount(_ count: Int) -> String {
        "\(count) \(count == 1 ? "file" : "files")"
    }

    private func failureCount(_ count: Int) -> String {
        "\(count) \(count == 1 ? "failure" : "failures")"
    }
}

/// Kokoro encodes a voice's language in the first letter of its id.
enum VoiceLanguage {
    struct Group {
        let name: String
        let voices: [String]
    }

    private static let names: [Character: String] = [
        "a": "American English",
        "b": "British English",
        "e": "Spanish",
        "f": "French",
        "h": "Hindi",
        "i": "Italian",
        "p": "Brazilian Portuguese",
        "j": "Japanese",
        "z": "Mandarin Chinese",
    ]

    private static let order = "abefhipjz"

    static func name(of voice: String) -> String {
        guard let first = voice.first, let name = names[first] else { return "Other" }
        return name
    }

    /// Group voices by language, in a stable order, so 41 rows stay readable.
    static func groups(of voices: [String]) -> [Group] {
        let byLanguage = Dictionary(grouping: voices, by: name(of:))
        return byLanguage.keys
            .sorted { left, right in rank(left) < rank(right) }
            .map { Group(name: $0, voices: byLanguage[$0]?.sorted() ?? []) }
    }

    private static func rank(_ languageName: String) -> Int {
        for (offset, letter) in order.enumerated() where names[letter] == languageName {
            return offset
        }
        return order.count
    }
}

/// Which voice each speaking client holds, and the listener's override.
struct AgentVoiceSettings: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        if state.voiceAssignments.isEmpty {
            Text("No client has spoken yet. Each one claims its own voice the first time it does.")
                .font(.caption2)
                .foregroundStyle(.secondary)
        } else {
            Text("A voice you set here wins over whatever the client asks for.")
                .font(.caption2)
                .foregroundStyle(.secondary)
            VStack(spacing: 0) {
                ForEach(state.voiceAssignments) { assignment in
                    AgentVoiceRow(assignment: assignment)
                    if assignment.id != state.voiceAssignments.last?.id { Divider() }
                }
            }
            .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 8))
        }
    }
}

struct AgentVoiceRow: View {
    @EnvironmentObject var state: AppState
    let assignment: VoiceAssignment

    var body: some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 1) {
                Text(assignment.source)
                    .font(.system(size: 12, weight: .medium))
                Text(assignment.pinned ? "set by you" : "claimed automatically")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            Spacer()
            Picker("Voice", selection: voiceBinding) {
                ForEach(state.voices, id: \.self) { voice in
                    Text(voice).tag(voice)
                }
            }
            .labelsHidden()
            .pickerStyle(.menu)
            .frame(width: 132)
            Button {
                state.releaseVoice(source: assignment.source)
            } label: {
                Image(systemName: "arrow.uturn.backward")
            }
            .buttonStyle(.borderless)
            .disabled(!assignment.pinned)
            .help(
                assignment.pinned
                    ? "Forget your override and let this client claim a voice again"
                    : "Nothing to undo: this voice was claimed automatically"
            )
        }
        .padding(.horizontal, 9)
        .padding(.vertical, 6)
    }

    private var voiceBinding: Binding<String> {
        Binding(
            get: { assignment.voice },
            set: { state.assignVoice(source: assignment.source, voice: $0) }
        )
    }
}

/// What playback does when the listener starts talking.
struct InputInterruptSettings: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        Toggle(
            "Stop playback when I start speaking",
            isOn: Binding(
                get: { state.inputInterruptEnabled },
                set: { state.setInputInterruptEnabled($0) }
            )
        )
        .toggleStyle(.switch)
        .controlSize(.small)
        Text(
            "Detected from the microphone being in use. The reading stays true for a while "
                + "after you stop, so playback stops once when you begin and then waits."
        )
        .font(.caption2)
        .foregroundStyle(.secondary)

        Picker(
            "Afterwards",
            selection: Binding(
                get: { state.inputInterruptResume },
                set: { state.setInputInterruptResume($0) }
            )
        ) {
            ForEach(InputInterruptResume.allCases, id: \.self) { policy in
                Text(policy.label).tag(policy)
            }
        }
        .pickerStyle(.radioGroup)
        .disabled(!state.inputInterruptEnabled)

        switch state.status?.inputActive {
        case .some(true):
            Label("Something is using the microphone right now.", systemImage: "mic.fill")
                .font(.caption2)
                .foregroundStyle(.orange)
        case .none where state.reachable:
            // The toggle being on is not the same as the watch running. Saying
            // nothing here would let the listener believe their voice takes
            // precedence while nothing is watching for it.
            Label(
                "Microphone monitoring is unavailable, so playback will not stop when you speak.",
                systemImage: "exclamationmark.triangle.fill"
            )
            .font(.caption2)
            .foregroundStyle(.red)
        default:
            EmptyView()
        }
    }
}

struct VoiceRow: View {
    @EnvironmentObject var state: AppState
    let voice: String
    let selected: Bool

    var body: some View {
        HStack {
            Image(systemName: selected ? "largecircle.fill.circle" : "circle")
                .foregroundStyle(selected ? Color.accentColor : Color.secondary)
            Text(voice).font(.system(size: 12, design: .monospaced))
            Spacer()
            Button {
                state.preview(voice)
            } label: {
                Image(systemName: "play.circle")
            }
            .buttonStyle(.borderless)
            .help("Preview this voice")
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .contentShape(Rectangle())
        .onTapGesture { state.setVoice(voice) }
    }
}

// MARK: - Shared details

struct EmptyPane: View {
    let icon: String
    let title: String
    let detail: String

    var body: some View {
        VStack(spacing: 7) {
            Image(systemName: icon)
                .font(.title2)
                .foregroundStyle(.tertiary)
            Text(title).font(.headline)
            Text(detail)
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct ModelHealthFooter: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(state.lastError == nil ? Color.green : Color.red)
                .frame(width: 6, height: 6)
            if let error = state.lastError {
                Text(error).foregroundStyle(.red)
            } else {
                Text("Model hot · \(state.status?.engine ?? "?") · \(state.status?.voice ?? "")")
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .font(.caption2)
        .lineLimit(1)
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
    }
}

func clock(_ ms: Int) -> String {
    let seconds = ms / 1000
    return String(format: "%d:%02d", seconds / 60, seconds % 60)
}
