// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// Settings: voice, speed, captions, interruption, and the voice register.
//
// Voices are enumerated from the daemon and grouped by language; nothing
// here hardcodes a voice id. The register view is where the listener's
// assignment outranks whatever an agent asks for.

import AITTSApplication
import SwiftUI

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
