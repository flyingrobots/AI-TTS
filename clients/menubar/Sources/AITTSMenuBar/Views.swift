// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// The popover, built to the interaction design in docs/design/ui-design.md:
// Now Playing is the default and usually the only view needed; the playback
// plan shows everything scheduled including items still waiting for
// synthesis; history is grouped by day with a fixed time column; per-row
// actions appear on hover; the transport is reachable from every tab.

import SwiftUI

enum Tab: String, CaseIterable {
    case now = "Now Playing"
    case upNext = "Up Next"
    case synthesis = "Queue"
    case history = "History"
    case settings = "Settings"

    var icon: String {
        switch self {
        case .now: return "waveform"
        case .upNext: return "list.bullet"
        case .synthesis: return "gearshape.arrow.triangle.2.circlepath"
        case .history: return "clock"
        case .settings: return "slider.horizontal.3"
        }
    }
}

// MARK: - Shell

struct PopoverView: View {
    @EnvironmentObject var state: AppState
    @State private var tab: Tab = .now

    var body: some View {
        VStack(spacing: 0) {
            TabBar(selected: $tab)
            Divider()
            Group {
                if !state.reachable {
                    UnreachableView()
                } else {
                    switch tab {
                    case .now: NowPlayingView()
                    case .upNext: UpNextView()
                    case .synthesis: SynthesisQueueView()
                    case .history: HistoryView()
                    case .settings: SettingsView()
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            Divider()
            TransportBar()
        }
        .frame(width: 360, height: 480)
        .onAppear { state.startPolling(interval: 0.5) }
    }
}

struct TabBar: View {
    @Binding var selected: Tab

    var body: some View {
        HStack(spacing: 2) {
            ForEach(Tab.allCases, id: \.self) { tab in
                Button {
                    selected = tab
                } label: {
                    VStack(spacing: 3) {
                        Image(systemName: tab.icon).font(.system(size: 14))
                        Text(shortLabel(tab)).font(.system(size: 9))
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .foregroundStyle(selected == tab ? Color.accentColor : Color.secondary)
                .background(
                    selected == tab ? Color.accentColor.opacity(0.12) : Color.clear,
                    in: RoundedRectangle(cornerRadius: 7)
                )
                .help(tab.rawValue)
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
    }

    private func shortLabel(_ tab: Tab) -> String {
        switch tab {
        case .now: return "Playing"
        case .upNext: return "Up Next"
        case .synthesis: return "Queue"
        case .history: return "History"
        case .settings: return "Settings"
        }
    }
}

struct UnreachableView: View {
    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: "exclamationmark.bubble").font(.largeTitle)
            Text("The daemon is not running").font(.headline)
            Text("Start it with:  ai-tts daemon").font(.system(.caption, design: .monospaced))
        }
        .foregroundStyle(.secondary)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Now Playing

struct NowPlayingView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let current = state.status?.current {
                HStack {
                    Text(caption(current))
                        .font(.caption.smallCaps())
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(current.voice)
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(.tertiary)
                }
                ScrollView {
                    Text(current.text)
                        .font(.system(size: 13.5))
                        .lineSpacing(2.5)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                if let duration = current.durationMs, duration > 0 {
                    let position = current.positionMs ?? current.playedMs ?? 0
                    VStack(spacing: 3) {
                        ProgressView(
                            value: min(Double(position), Double(duration)),
                            total: Double(duration))
                        HStack {
                            Text(clock(position)).font(
                                .system(.caption2, design: .monospaced))
                            Spacer()
                            Text(clock(duration)).font(
                                .system(.caption2, design: .monospaced))
                        }
                        .foregroundStyle(.secondary)
                    }
                }
                if let next = state.plan.first(where: { $0.id != current.id }) {
                    Divider()
                    HStack(spacing: 6) {
                        Text("Up next").font(.caption2.smallCaps()).foregroundStyle(.tertiary)
                        Text(next.text).font(.caption).lineLimit(1)
                            .foregroundStyle(.secondary)
                    }
                }
            } else {
                Spacer()
                VStack(spacing: 8) {
                    Text("Nothing to say right now").foregroundStyle(.secondary)
                    if let last = state.history.first {
                        HStack(spacing: 6) {
                            Text(last.text).lineLimit(1).font(.caption)
                                .foregroundStyle(.tertiary)
                            ReplayButton(id: last.id)
                        }
                        .padding(.horizontal, 24)
                    }
                    Text("Send text with:  ai-tts say \"…\"")
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(.tertiary)
                }
                .frame(maxWidth: .infinity)
                Spacer()
            }
        }
        .padding(12)
    }

    private func caption(_ current: Utterance) -> String {
        current.state == "Playing" ? "Now speaking" : current.state
    }
}

func clock(_ ms: Int) -> String {
    let seconds = ms / 1000
    return String(format: "%d:%02d", seconds / 60, seconds % 60)
}

struct ReplayButton: View {
    @EnvironmentObject var state: AppState
    let id: String

    var body: some View {
        Button {
            state.playNow(id)
        } label: {
            Image(systemName: "arrow.counterclockwise")
        }
        .buttonStyle(.borderless)
        .help("Replay")
    }
}

// MARK: - Up Next (the speaking plan, waiting-for-synthesis included)

struct UpNextView: View {
    @EnvironmentObject var state: AppState
    @State private var hovered: String?

    var body: some View {
        if state.plan.isEmpty {
            EmptyPane(text: "Nothing queued.")
        } else {
            List(state.plan) { item in
                PlanRow(item: item, hovered: hovered == item.id)
                    .onHover { inside in hovered = inside ? item.id : nil }
                    .listRowSeparator(.visible)
            }
            .listStyle(.plain)
        }
    }
}

struct PlanRow: View {
    @EnvironmentObject var state: AppState
    let item: Utterance
    let hovered: Bool

    private var isCurrent: Bool { item.state == "Playing" || item.state == "Paused" }

    var body: some View {
        HStack(alignment: .center, spacing: 8) {
            RoundedRectangle(cornerRadius: 1.5)
                .fill(isCurrent ? Color.accentColor : Color.clear)
                .frame(width: 3)
            VStack(alignment: .leading, spacing: 3) {
                Text(item.text)
                    .lineLimit(2)
                    .font(.system(size: isCurrent ? 12.5 : 12,
                                  weight: isCurrent ? .medium : .regular))
                HStack(spacing: 6) {
                    Text(subtitle).font(.caption2).foregroundStyle(.secondary)
                    if isCurrent, let duration = item.durationMs, duration > 0 {
                        ProgressView(
                            value: Double(item.playedMs ?? 0), total: Double(duration)
                        )
                        .controlSize(.small)
                        .frame(width: 90)
                    }
                }
            }
            Spacer(minLength: 4)
            if hovered && !isCurrent {
                Button {
                    state.playNow(item.id)
                } label: {
                    Image(systemName: "text.line.first.and.arrowtriangle.forward")
                }
                .buttonStyle(.borderless)
                .help("Move to the top")
                Button {
                    state.cancel(item.id)
                } label: {
                    Image(systemName: "xmark.circle")
                }
                .buttonStyle(.borderless)
                .help("Remove")
            } else {
                StatePill(state: item.state)
            }
        }
        .padding(.vertical, 2)
        .background(isCurrent ? Color.accentColor.opacity(0.07) : Color.clear)
    }

    private var subtitle: String {
        switch item.state {
        case "Queued": return "waiting for synthesis"
        case "Synthesizing": return "generating…"
        case "Ready":
            if let duration = item.durationMs { return clock(duration) }
            return "ready"
        case "Playing": return "speaking"
        case "Paused": return "paused"
        default: return item.state.lowercased()
        }
    }
}

// MARK: - Synthesis queue (active work plus ready results)

struct SynthesisQueueView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        VStack(spacing: 0) {
            if state.synthesisQueueIsEmpty {
                EmptyPane(text: "The queue is clear.")
            } else {
                List {
                    if !state.inputQueue.isEmpty {
                        Section("WAITING / GENERATING") {
                            ForEach(state.inputQueue) { item in
                                SynthesisQueueRow(item: item)
                            }
                        }
                    }
                    if !state.readyForPlayback.isEmpty {
                        Section("READY FOR PLAYBACK") {
                            ForEach(state.readyForPlayback) { item in
                                SynthesisQueueRow(item: item)
                            }
                        }
                    }
                }
                .listStyle(.plain)
            }
            Divider()
            HStack {
                Circle().fill(.green).frame(width: 6, height: 6)
                Text("Model hot · \(state.status?.engine ?? "?") · \(state.status?.voice ?? "")")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Spacer()
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
        }
    }
}

struct SynthesisQueueRow: View {
    @EnvironmentObject var state: AppState
    let item: Utterance

    var body: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 2) {
                Text(item.text).lineLimit(2).font(.system(size: 12))
                if let error = item.error {
                    Text(error).font(.caption2).foregroundStyle(.red)
                }
            }
            Spacer()
            StatePill(state: item.state)
            Button {
                state.cancel(item.id)
            } label: {
                Image(systemName: "xmark.circle")
            }
            .buttonStyle(.borderless)
            .help("Cancel")
        }
    }
}

struct EmptyPane: View {
    let text: String

    var body: some View {
        VStack { Text(text).foregroundStyle(.secondary) }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct StatePill: View {
    let state: String

    var body: some View {
        Text(state)
            .font(.caption2.weight(.medium))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.18), in: Capsule())
            .foregroundStyle(color)
    }

    private var color: Color {
        switch state {
        case "Playing": return .blue
        case "Ready": return .green
        case "Synthesizing": return .orange
        case "Failed": return .red
        case "Paused": return .gray
        default: return .secondary
        }
    }
}

// MARK: - History (day-grouped, fixed time column, expand in place)

struct HistoryView: View {
    @EnvironmentObject var state: AppState
    @State private var query = ""
    @State private var expanded: Set<String> = []

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
            TextField("Search history", text: $query)
                .textFieldStyle(.roundedBorder)
                .padding(8)
            if filtered.isEmpty {
                Spacer()
                Text(query.isEmpty ? "Nothing spoken yet" : "No matches for “\(query)”")
                    .foregroundStyle(.secondary)
                if !query.isEmpty {
                    Text("\(state.history.count) items in history")
                        .font(.caption2).foregroundStyle(.tertiary)
                }
                Spacer()
            } else {
                List {
                    ForEach(groups, id: \.day) { group in
                        Section {
                            ForEach(group.items) { item in
                                HistoryRow(item: item, expanded: expanded.contains(item.id))
                                    .contentShape(Rectangle())
                                    .onTapGesture { toggle(item.id) }
                            }
                        } header: {
                            Text(group.day).font(.caption2.smallCaps())
                        }
                    }
                }
                .listStyle(.plain)
            }
        }
    }

    private func toggle(_ id: String) {
        if expanded.contains(id) { expanded.remove(id) } else { expanded.insert(id) }
    }
}

struct HistoryRow: View {
    @EnvironmentObject var state: AppState
    let item: Utterance
    let expanded: Bool

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter
    }()

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Text(time)
                .font(.system(.caption2, design: .monospaced))
                .foregroundStyle(.tertiary)
                .frame(width: 34, alignment: .leading)
            VStack(alignment: .leading, spacing: 2) {
                Text(item.text)
                    .font(.system(size: 12))
                    .lineLimit(expanded ? nil : 2)
                HStack(spacing: 6) {
                    Text(detail).font(.caption2).foregroundStyle(.secondary)
                    if let source = item.source {
                        Text(source)
                            .font(.system(size: 9, design: .monospaced))
                            .foregroundStyle(.tertiary)
                    }
                }
                if let error = item.error {
                    Text(error).font(.caption2).foregroundStyle(.red)
                }
            }
            Spacer(minLength: 4)
            ReplayButton(id: item.id)
        }
        .padding(.vertical, 1)
    }

    private var time: String {
        guard let at = item.finishedAt ?? item.enqueuedAt else { return "–" }
        return Self.timeFormatter.string(from: Date(timeIntervalSince1970: at))
    }

    private var detail: String {
        let final = item.finalState ?? item.state
        if final == "Skipped", let played = item.playedMs, let total = item.durationMs {
            return "skipped at \(clock(played)) of \(clock(total))"
        }
        return final
    }
}

// MARK: - Settings

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

// MARK: - Transport (reachable from every tab)

struct TransportBar: View {
    @EnvironmentObject var state: AppState

    private var isPaused: Bool { state.status?.state == "paused" }
    private var hasCurrent: Bool { state.status?.current != nil }

    var body: some View {
        HStack(spacing: 20) {
            Button {
                state.rewind()
            } label: {
                Image(systemName: "backward.end")
            }
            .disabled(!hasCurrent)
            .help("Restart the current utterance")

            Button {
                isPaused ? state.resume() : state.pause()
            } label: {
                Image(systemName: isPaused ? "play.fill" : "pause.fill").font(.title3)
            }
            .disabled(!state.reachable)
            .help(isPaused ? "Resume" : "Pause")

            Button {
                state.skip()
            } label: {
                Image(systemName: "forward.end")
            }
            .disabled(!hasCurrent)
            .help("Skip")

            Spacer()

            if let error = state.lastError {
                Text(error).font(.caption2).foregroundStyle(.red).lineLimit(1)
            }
        }
        .buttonStyle(.borderless)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }
}
