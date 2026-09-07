// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// The pinned current clip: transport, progress, and chunk position.
//
// Every transport control is rendered from TransportAction so its label and
// shortcut are a value that can be asserted rather than a modifier somebody
// has to remember. This tool is for people who are listening rather than
// looking, so an unlabelled transport is a pointed failure here.

import AITTSApplication
import SwiftUI

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
                .keyboardShortcut(TransportAction.playPause.shortcut, modifiers: [])
                .accessibilityLabel(isPaused ? "Resume playback" : "Pause playback")
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
                    ForEach(TransportAction.allCases.filter { !$0.isPrimary }, id: \.self) {
                        action in
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
            case .playPause: isPaused ? state.resume() : state.pause()
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
        case .playPause, .fullText, .skip:
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
