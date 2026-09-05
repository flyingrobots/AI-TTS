// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// Opt-in, non-activating on-screen captions for the exact segment being heard.

import AITTSApplication
import AppKit
import SwiftUI

enum CaptionPresentation {
    static func shouldShow(enabled: Bool, reachable: Bool, status: DaemonStatus?) -> Bool {
        enabled && reachable && status?.current?.activeSegment != nil
    }
}

@MainActor
protocol CaptionApplicationVisibilityPort: AnyObject {
    var isHidden: Bool { get }
    func unhideWithoutActivation()
}

extension NSApplication: CaptionApplicationVisibilityPort {}

@MainActor
enum CaptionApplicationVisibility {
    static func prepareForPanel(_ application: any CaptionApplicationVisibilityPort) {
        guard application.isHidden else { return }
        application.unhideWithoutActivation()
    }
}

@MainActor
final class CaptionPanelController {
    private let state: AppState
    private let panel: NSPanel

    init(state: AppState) {
        self.state = state
        self.panel = NSPanel(
            contentRect: .zero,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = false
        panel.hidesOnDeactivate = false
        panel.ignoresMouseEvents = true
        panel.isReleasedWhenClosed = false
        panel.animationBehavior = .utilityWindow
        panel.contentViewController = NSHostingController(
            rootView: CaptionOverlayView().environmentObject(state))
    }

    func updateVisibility() {
        guard CaptionPresentation.shouldShow(
            enabled: state.captionsEnabled,
            reachable: state.reachable,
            status: state.status
        ) else {
            panel.orderOut(nil)
            return
        }
        CaptionApplicationVisibility.prepareForPanel(NSApplication.shared)
        positionPanel()
        if !panel.isVisible {
            panel.orderFrontRegardless()
        }
    }

    private func positionPanel() {
        guard let screen = NSScreen.main ?? NSScreen.screens.first else { return }
        let visible = screen.visibleFrame
        let size = NSSize(width: min(760, visible.width - 80), height: 132)
        let origin = NSPoint(
            x: visible.midX - size.width / 2,
            y: visible.minY + 44
        )
        panel.setFrame(NSRect(origin: origin, size: size), display: true)
    }
}

struct CaptionOverlayView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        Group {
            if let segment = state.status?.current?.activeSegment {
                CaptionCueView(
                    segment: segment,
                    playbackState: state.status?.playbackState ?? "idle",
                    observedAt: state.statusObservedAt,
                    playbackRate: state.observedPlaybackRate
                )
            }
        }
        .padding(6)
        .allowsHitTesting(false)
    }
}

private struct CaptionCueView: View {
    let segment: ActiveSegment
    let playbackState: String
    let observedAt: Date
    let playbackRate: Double
    private let track: CaptionCueTrack

    init(
        segment: ActiveSegment,
        playbackState: String,
        observedAt: Date,
        playbackRate: Double
    ) {
        self.segment = segment
        self.playbackState = playbackState
        self.observedAt = observedAt
        self.playbackRate = playbackRate
        self.track = CaptionCueTrack(text: segment.text)
    }

    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.2)) { timeline in
            let position = CaptionPlaybackTimeline.positionMs(
                reportedPositionMs: segment.positionMs,
                observedAt: observedAt,
                now: timeline.date,
                playbackState: playbackState,
                playbackRate: playbackRate,
                durationMs: segment.durationMs
            )
            VStack(spacing: 7) {
                if segment.count > 1 {
                    Text("PART \(segment.number) OF \(segment.count)")
                        .font(.caption2.smallCaps().weight(.semibold))
                        .foregroundStyle(.white.opacity(0.72))
                }
                Text(track.cue(positionMs: position, durationMs: segment.durationMs))
                    .font(.system(size: 22, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
                    .minimumScaleFactor(0.8)
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 14)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(.black.opacity(0.82), in: RoundedRectangle(cornerRadius: 16))
            .overlay {
                RoundedRectangle(cornerRadius: 16)
                    .stroke(.white.opacity(0.16), lineWidth: 1)
            }
        }
    }
}
