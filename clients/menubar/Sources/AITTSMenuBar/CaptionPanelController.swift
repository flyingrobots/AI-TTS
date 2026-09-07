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

/// The caption overlay is deliberately invisible to assistive technology.
///
/// An audit recommended marking it as accessibility-announcing, on the general
/// principle that a region changing on screen should be announced. Here that
/// would be actively harmful: this panel shows the text a speech synthesizer
/// is reading aloud *right now*, so announcing it makes VoiceOver read, in a
/// second voice, the words already being spoken.
///
/// Captions exist for someone who wants to *see* what is being said. The
/// audible channel is the product. So the panel is hidden from the
/// accessibility tree rather than announced, and it is non-activating and
/// mouse-transparent so it never takes focus from whatever the listener is
/// actually working in.
struct CaptionOverlayView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        Group {
            if let segment = state.status?.current?.activeSegment {
                CaptionCueView(
                    segment: segment,
                    source: state.status?.current?.source,
                    playbackState: state.status?.playbackState ?? "idle",
                    observedAt: state.statusObservedAt,
                    playbackRate: state.observedPlaybackRate
                )
            }
        }
        .padding(6)
        .allowsHitTesting(false)
        // See the note above this view: announcing captions would have
        // VoiceOver read aloud the words already being spoken aloud.
        .accessibilityHidden(true)
    }
}

private struct CaptionCueView: View {
    let segment: ActiveSegment
    let playbackState: String
    let observedAt: Date
    let playbackRate: Double
    private let track: CaptionCueTrack
    private let metadata: CaptionMetadata

    init(
        segment: ActiveSegment,
        source: String?,
        playbackState: String,
        observedAt: Date,
        playbackRate: Double
    ) {
        self.segment = segment
        self.playbackState = playbackState
        self.observedAt = observedAt
        self.playbackRate = playbackRate
        self.track = CaptionCueTrack(text: segment.text)
        self.metadata = CaptionMetadata(
            source: source,
            segmentNumber: segment.number,
            segmentCount: segment.count
        )
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
                metadataRow
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

    @ViewBuilder
    private var metadataRow: some View {
        if let sourceLabel = metadata.sourceLabel {
            HStack(spacing: 12) {
                Text(sourceLabel)
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(.white.opacity(0.68))
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer(minLength: 0)
                if let partLabel = metadata.partLabel {
                    partText(partLabel)
                }
            }
        } else if let partLabel = metadata.partLabel {
            partText(partLabel)
                .frame(maxWidth: .infinity, alignment: .center)
        }
    }

    private func partText(_ label: String) -> some View {
        Text(label)
            .font(.caption2.smallCaps().weight(.semibold))
            .foregroundStyle(.white.opacity(0.72))
            .fixedSize()
    }
}
