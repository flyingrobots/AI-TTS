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

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 6) {
                Circle()
                    .fill(state.lastError == nil ? Color.green : Color.red)
                    .frame(width: 6, height: 6)
                Text("Model hot · \(state.status?.engine ?? "?") ·")
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
            if let error = state.lastError { Text(error).foregroundStyle(.red) }
            if let notice = state.voiceNotice {
                HStack(alignment: .top) {
                    Text(notice).fixedSize(horizontal: false, vertical: true)
                    Button { state.voiceNotice = nil } label: { Image(systemName: "xmark") }
                        .buttonStyle(.borderless).help("Dismiss voice confirmation")
                }
            }
            HStack {
                Button("Open Data Folder", systemImage: "folder") { state.openDataFolder() }
            }.buttonStyle(.borderless)
        }
        .font(.caption2)
        .padding(.horizontal, 12)
        .padding(.vertical, 6)

    }
}

func clock(_ ms: Int) -> String {
    let seconds = ms / 1000
    return String(format: "%d:%02d", seconds / 60, seconds % 60)
}
