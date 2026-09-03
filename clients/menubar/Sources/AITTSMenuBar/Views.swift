// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// One playback surface: the current clip stays pinned above a Queue/History
// switcher. Queue is the exact upcoming playback plan, regardless of synthesis
// state. History is newest-first and keeps original priority as provenance.

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
        switch state.status?.state {
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
    private var isPaused: Bool { state.status?.state == "paused" }

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text(current == nil ? "CURRENT" : isPaused ? "PAUSED" : "NOW SPEAKING")
                    .font(.caption2.smallCaps().weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                if let current {
                    Text(current.voice)
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(.tertiary)
                }
            }

            if let current {
                Text(current.text)
                    .font(.system(size: 13, weight: .medium))
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
                progress(for: current)
                HStack(spacing: 14) {
                    Button {
                        state.rewind()
                    } label: {
                        Label("Restart", systemImage: "backward.end.fill")
                    }
                    .help("Restart the current clip")
                    Button {
                        isPaused ? state.resume() : state.pause()
                    } label: {
                        Label(isPaused ? "Resume" : "Pause",
                              systemImage: isPaused ? "play.fill" : "pause.fill")
                    }
                    Button {
                        state.skip()
                    } label: {
                        Label("Skip", systemImage: "forward.end.fill")
                    }
                    Spacer()
                }
                .labelStyle(.iconOnly)
                .buttonStyle(.borderless)
            } else {
                Text(isPaused ? "Playback is paused" : "Nothing is playing")
                    .font(.system(size: 13, weight: .medium))
                Text(
                    isPaused
                        ? "Resume when you are ready to continue the Queue."
                        : "Queued clips will begin here in playback order."
                )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if isPaused {
                    Button {
                        state.resume()
                    } label: {
                        Label("Resume", systemImage: "play.fill")
                    }
                    .buttonStyle(.borderless)
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.primary.opacity(0.045), in: RoundedRectangle(cornerRadius: 9))
        .padding(.horizontal, 10)
        .padding(.top, 8)
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

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(queueSummary)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
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
                Text(item.text)
                    .font(.system(size: 12))
                    .lineLimit(2)
                Spacer(minLength: 2)
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

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Voice").font(.caption.smallCaps()).foregroundStyle(.secondary)
                VStack(spacing: 0) {
                    ForEach(state.voices, id: \.self) { voice in
                        VoiceRow(voice: voice, selected: voice == state.status?.voice)
                        if voice != state.voices.last { Divider() }
                    }
                }
                .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 8))

                Text("Speed").font(.caption.smallCaps()).foregroundStyle(.secondary)
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

                Divider()
                Button("Quit AI-TTS Menu Bar") { NSApp.terminate(nil) }
            }
            .padding(12)
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
