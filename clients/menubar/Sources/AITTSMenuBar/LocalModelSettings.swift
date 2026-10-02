// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import AITTSApplication
import SwiftUI

/// Discover, install and choose models from one place above the voice controls.
struct LocalModelSettings: View {
    @EnvironmentObject var state: AppState
    @State private var setupModel: LocalSpeechModel?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Speech models").font(.caption.smallCaps()).foregroundStyle(.secondary)
            Text("Install a model once, then choose which model speaks new clips. Speech stays on this Mac.")
                .font(.caption2).foregroundStyle(.secondary)
            if state.models.isEmpty {
                Text("Connect to the daemon to see model setup options.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            ForEach(state.models) { model in
                VStack(alignment: .leading, spacing: 5) {
                    HStack {
                        Text(model.title).font(.subheadline.weight(.medium))
                        Spacer()
                        if model.selected {
                            Label("Selected", systemImage: "checkmark.circle.fill")
                                .font(.caption2)
                        }
                    }
                    Text(model.description).font(.caption2).foregroundStyle(.secondary)
                    if let incompatible = model.incompatible {
                        Text(incompatible).font(.caption2).foregroundStyle(.secondary)
                    } else if model.installing {
                        HStack {
                            ProgressView().controlSize(.small)
                            Text(model.message).font(.caption2)
                            Spacer()
                            Button("Cancel") { state.cancelModelSetup() }
                        }
                    } else {
                        HStack {
                            Text(status(model)).font(.caption2).foregroundStyle(.secondary)
                            Spacer()
                            if model.installed && model.state != "failed" && model.state != "cancelled" {
                                if !model.selected {
                                    Button("Use model") { state.setEngine(model.name) }
                                }
                            } else if model.state == "loading" {
                                ProgressView().controlSize(.small)
                            } else {
                                Button(model.state == "failed" || model.state == "cancelled" ? "Retry setup" : "Download & install…") {
                                    setupModel = model
                                }
                                .disabled(state.models.contains(where: { $0.installing }))
                            }
                        }
                        if !model.message.isEmpty && model.state != "ready" {
                            Text(model.message).font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                }
                .padding(9)
                .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 8))
            }
            // Configured local servers remain selectable alongside managed models.
            ForEach(state.engines.filter { engine in !state.models.contains(where: { $0.name == engine.name }) }) { engine in
                HStack {
                    Text(engine.name).font(.caption)
                    Spacer()
                    if engine.name == state.status?.engine {
                        Text("Selected").font(.caption2)
                    } else {
                        Button("Use model") { state.setEngine(engine.name) }
                    }
                }
            }
        }
        .confirmationDialog("Download \(setupModel?.title ?? "speech model")?", isPresented: Binding(
            get: { setupModel != nil }, set: { if !$0 { setupModel = nil } }
        ), titleVisibility: .visible, presenting: setupModel) { model in
            Button("Download & install") {
                state.installModel(model.name)
                setupModel = nil
            }
            Button("Cancel", role: .cancel) { setupModel = nil }
        } message: { model in
            Text("AI-TTS will download \(model.title) and its required runtime. Setup may take several minutes and use substantial disk space. Your current model will keep working; choose Use model when setup finishes.")
        }
    }

    private func status(_ model: LocalSpeechModel) -> String {
        switch model.state {
        case "ready": return "Installed"
        case "loading": return "Preparing model…"
        case "failed": return "Setup needs attention"
        case "cancelled": return "Setup cancelled"
        default: return model.installed ? "Installed" : "Not installed"
        }
    }
}
