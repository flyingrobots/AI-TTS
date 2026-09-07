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
        HStack(spacing: 6) {
            Circle()
                .fill(state.lastError == nil ? Color.green : Color.red)
                .frame(width: 6, height: 6)
            if let error = state.lastError {
                Text(error).foregroundStyle(.red)
            } else {
                Text("Model hot · \(state.status?.engine ?? "?") · \(state.status?.voice ?? "")")
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .font(.caption2)
        .lineLimit(1)
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
    }
}

func clock(_ ms: Int) -> String {
    let seconds = ms / 1000
    return String(format: "%d:%02d", seconds / 60, seconds % 60)
}
