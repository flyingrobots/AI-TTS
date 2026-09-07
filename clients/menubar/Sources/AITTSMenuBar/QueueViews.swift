// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// Queue: the exact upcoming playback plan, regardless of synthesis state.
//
// One row per clip, once. The former Now Playing, Up Next and synthesis
// queue surfaces were three views of the same list and are deliberately not
// reintroduced here.

import AITTSApplication
import AITTSMacAdapters
import SwiftUI

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
