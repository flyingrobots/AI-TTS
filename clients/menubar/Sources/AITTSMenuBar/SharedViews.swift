// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// Small views shared by more than one pane.

import SwiftUI

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
    @State private var confirmingRestart = false

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 6) {
                Circle()
                    .fill(state.runtime?.modelState == "ready" ? Color.green : Color.orange)
                    .frame(width: 6, height: 6)
                Text("Model \(state.runtime?.modelState ?? "unknown") · \(state.status?.engine ?? "?") ·")
                    .foregroundStyle(.secondary)
                Menu {
                    ForEach(state.voices, id: \.self) { voice in
                        Button { state.setVoice(voice) } label: {
                            if voice == state.status?.voice { Label(voice, systemImage: "checkmark") }
                            else { Text(voice) }
                        }
                    }
                } label: { Text(state.status?.voice ?? "Voice") }
                .menuStyle(.borderlessButton)
                .fixedSize()
                .disabled(state.voices.isEmpty)
                .accessibilityLabel("Default voice")
                Spacer(minLength: 0)
            }
            if let error = state.lastError {
                HStack(alignment: .top) {
                    Text(error).foregroundStyle(.red).lineLimit(3)
                    Spacer(minLength: 0)
                    Button { state.dismissError() } label: { Image(systemName: "xmark") }
                        .buttonStyle(.borderless).help("Dismiss error")
                        .accessibilityLabel("Dismiss error")
                }
            }
            if let notice = state.voiceNotice {
                HStack(alignment: .top) {
                    Text(notice).fixedSize(horizontal: false, vertical: true)
                    Button { state.voiceNotice = nil } label: { Image(systemName: "xmark") }
                        .buttonStyle(.borderless).help("Dismiss voice confirmation")
                        .accessibilityLabel("Dismiss voice confirmation")
                }
            }
            if let runtime = state.runtime {
                Text("Daemon connected · PID \(runtime.pid) · up \(clock(Int(runtime.uptimeSeconds * 1000))) · \(runtime.activeSynthesis) generating")
                    .foregroundStyle(.secondary)
            }
            HStack {
                Button("Open Data Folder", systemImage: "folder") { state.openDataFolder() }
                Button("Manage Files…") { state.showingStorage = true }
                Spacer()
                Menu("Maintenance") {
                    Button("Reload Model") { state.reloadModel() }
                        .disabled(state.maintenanceInProgress || state.runtime?.activeSynthesis != 0 || ["loading", "reloading"].contains(state.runtime?.modelState ?? ""))
                    Button("Restart Daemon…") { confirmingRestart = true }
                        .disabled(state.maintenanceInProgress)
                    Button("View Daemon Logs") { state.viewDaemonLogs() }
                }.menuStyle(.borderlessButton).fixedSize()
                if state.maintenanceInProgress { ProgressView().controlSize(.small) }
            }.buttonStyle(.borderless)
        }
        .font(.caption2)
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .confirmationDialog("Restart daemon?", isPresented: $confirmingRestart) {
            Button("Restart Daemon") { state.restartDaemon() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Playback will pause. Queued work will be recovered; resume playback when the daemon reconnects.")
        }
    }
}

func clock(_ ms: Int) -> String {
    let seconds = ms / 1000
    return String(format: "%d:%02d", seconds / 60, seconds % 60)
}
