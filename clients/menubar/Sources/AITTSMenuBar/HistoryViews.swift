// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// History: newest first, with original priority kept as provenance.
//
// Re-queueing defaults to appending and offers playing next as an explicit
// choice, because the common case is wanting to hear something again rather
// than wanting it to interrupt.

import AITTSApplication
import SwiftUI

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
