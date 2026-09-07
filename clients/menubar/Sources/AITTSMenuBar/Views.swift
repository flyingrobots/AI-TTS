// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// The popover shell: what is always on screen, and in what order.
//
// The current clip stays pinned above a Queue/History switcher, and the two
// notices that explain silence sit above it — a first run still fetching the
// engine, and a hold the listener's own voice caused.

import AITTSApplication
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
