// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// The popover: Now Playing first, the other views one segment away
// (ui-design.md). v1 uses stock SwiftUI controls; the mockups' pixel design
// is the target for a later pass.

import SwiftUI

enum Tab: String, CaseIterable {
    case now = "Now Playing"
    case upNext = "Up Next"
    case synthesis = "Queue"
    case history = "History"
    case settings = "Settings"
}

struct PopoverView: View {
    @EnvironmentObject var state: AppState
    @State private var tab: Tab = .now

    var body: some View {
        VStack(spacing: 0) {
            Picker("", selection: $tab) {
                ForEach(Tab.allCases, id: \.self) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(10)

            Divider()

            Group {
                if !state.reachable {
                    UnreachableView()
                } else {
                    switch tab {
                    case .now: NowPlayingView()
                    case .upNext: QueueListView(kind: .playback)
                    case .synthesis: QueueListView(kind: .input)
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

struct NowPlayingView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let current = state.status?.current {
                Text(stateLabel(current.state))
                    .font(.caption.smallCaps())
                    .foregroundStyle(.secondary)
                ScrollView {
                    Text(current.text)
                        .font(.system(size: 13.5))
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                if let duration = current.durationMs {
                    ProgressView(
                        value: Double(current.playedMs ?? 0),
                        total: Double(max(duration, 1))
                    )
                }
            } else {
                Spacer()
                VStack(spacing: 6) {
                    Text("Nothing to say right now").foregroundStyle(.secondary)
                    if let last = state.history.first {
                        LastSpokenRow(item: last)
                    }
                    Text("Send text with:  ai-tts say \"…\"")
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(.tertiary)
                }
                .frame(maxWidth: .infinity)
                Spacer()
            }
        }
        .padding(12)
    }

    private func stateLabel(_ state: String) -> String {
        state == "Playing" ? "Now speaking" : state
    }
}

struct LastSpokenRow: View {
    @EnvironmentObject var state: AppState
    let item: Utterance

    var body: some View {
        HStack {
            Text(item.text).lineLimit(1).foregroundStyle(.secondary)
            Button {
                state.replay(item.id)
            } label: {
                Image(systemName: "arrow.counterclockwise")
            }
            .buttonStyle(.borderless)
            .help("Replay")
        }
        .padding(.horizontal, 16)
    }
}

enum QueueKind {
    case playback
    case input
}

struct QueueListView: View {
    @EnvironmentObject var state: AppState
    let kind: QueueKind

    private var items: [Utterance] {
        kind == .playback ? state.playbackQueue : state.inputQueue
    }

    var body: some View {
        if items.isEmpty {
            VStack {
                Text(kind == .playback ? "Nothing queued." : "The queue is clear.")
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            List(items) { item in
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(item.text).lineLimit(2).font(.system(size: 12))
                        if let error = item.error {
                            Text(error).font(.caption).foregroundStyle(.red)
                        }
                    }
                    Spacer()
                    StatePill(state: item.state)
                    if item.state != "Playing" {
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
            .listStyle(.plain)
        }
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

struct HistoryView: View {
    @EnvironmentObject var state: AppState
    @State private var query = ""

    private var filtered: [Utterance] {
        guard !query.isEmpty else { return state.history }
        return state.history.filter { $0.text.localizedCaseInsensitiveContains(query) }
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
                Spacer()
            } else {
                List(filtered) { item in
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.text).lineLimit(2).font(.system(size: 12))
                            Text(item.finalState ?? item.state)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button {
                            state.replay(item.id)
                        } label: {
                            Image(systemName: "play.circle")
                        }
                        .buttonStyle(.borderless)
                        .help("Replay")
                    }
                }
                .listStyle(.plain)
            }
        }
    }
}

struct SettingsView: View {
    @EnvironmentObject var state: AppState
    @State private var speed = 1.0

    var body: some View {
        Form {
            Section("Voice") {
                Picker("Voice", selection: voiceBinding) {
                    ForEach(state.voices, id: \.self) { Text($0).tag($0) }
                }
                .labelsHidden()
            }
            Section("Speed") {
                HStack {
                    Slider(value: $speed, in: 0.5...2.0, step: 0.05) { editing in
                        if !editing { state.setSpeed(speed) }
                    }
                    Text(String(format: "%.2f×", speed))
                        .font(.system(.caption, design: .monospaced))
                }
            }
            Section {
                Button("Quit AI-TTS Menu Bar") { NSApp.terminate(nil) }
            }
        }
        .formStyle(.grouped)
    }

    private var voiceBinding: Binding<String> {
        Binding(
            get: { state.status?.voice ?? state.voices.first ?? "" },
            set: { state.setVoice($0) }
        )
    }
}

struct TransportBar: View {
    @EnvironmentObject var state: AppState

    private var isPaused: Bool { state.status?.state == "paused" }

    var body: some View {
        HStack(spacing: 20) {
            Button {
                state.rewind()
            } label: {
                Image(systemName: "backward.end")
            }
            .help("Restart the current utterance")

            Button {
                isPaused ? state.resume() : state.pause()
            } label: {
                Image(systemName: isPaused ? "play.fill" : "pause.fill").font(.title3)
            }
            .help(isPaused ? "Resume" : "Pause")

            Button {
                state.skip()
            } label: {
                Image(systemName: "forward.end")
            }
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
