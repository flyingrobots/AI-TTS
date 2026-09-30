// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import AITTSApplication
import SwiftUI

struct GeneratedStorageSheet: View {
    @EnvironmentObject var state: AppState
    @State private var deleting: [String] = []
    @State private var confirmingDelete = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Generated Files").font(.headline)
                Spacer()
                Button("Open in Finder") { state.openDataFolder() }
                Button("Done") { state.showingStorage = false }.keyboardShortcut(.defaultAction)
            }
            if let snapshot = state.storageSnapshot {
                Text("\(snapshot.entries.count) clip directories · \(ByteCountFormatter.string(fromByteCount: snapshot.totalBytes, countStyle: .file))")
                    .foregroundStyle(.secondary)
                Picker("Automatically delete unused files after", selection: Binding(
                    get: { snapshot.retentionDays }, set: { state.manageStorage(retentionDays: $0) }
                )) {
                    Text("Never").tag(0)
                    Text("1 day").tag(1)
                    Text("7 days").tag(7)
                    Text("30 days").tag(30)
                    Text("90 days").tag(90)
                }.disabled(state.storageBusy)
                Text("Deletes eligible audio, source copies, and evidence logs. History remains. Current and queued clips stay protected. The audio cache size limit still applies.")
                    .font(.caption).foregroundStyle(.secondary)
                List(snapshot.entries) { item in
                    HStack {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(item.preview).lineLimit(2)
                            Text("\(ByteCountFormatter.string(fromByteCount: item.bytes, countStyle: .file)) · \(Date(timeIntervalSince1970: item.modifiedAt).formatted())")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        if item.protected {
                            Label("In use", systemImage: "lock").font(.caption)
                        } else {
                            Button("Delete…") { deleting = [item.id]; confirmingDelete = true }
                                .disabled(state.storageBusy)
                        }
                    }
                }
                HStack {
                    Button("Delete All Eligible Files…", role: .destructive) {
                        deleting = snapshot.entries.filter { !$0.protected }.map(\.id)
                        confirmingDelete = true
                    }.disabled(state.storageBusy || snapshot.entries.allSatisfy(\.protected))
                    Spacer()
                    Button("Refresh") { state.manageStorage() }.disabled(state.storageBusy)
                }
            }
            if state.storageBusy { ProgressView().controlSize(.small) }
            if let message = state.storageMessage { Text(message).font(.caption) }
        }
        .padding(16)
        .frame(width: 600, height: 440)
        .onAppear { state.manageStorage() }
        .confirmationDialog("Delete generated files?", isPresented: $confirmingDelete) {
            Button("Delete Files", role: .destructive) { state.manageStorage(deleting: deleting) }
            Button("Cancel", role: .cancel) {}
        } message: { Text("Audio and evidence for these clips will be removed. History text remains; missing audio can be regenerated when re-queued.") }
    }
}
