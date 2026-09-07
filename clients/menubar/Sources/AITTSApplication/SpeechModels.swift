// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

/// A segment currently being synthesized or spoken inside one document.
public struct ActiveSegment: Equatable, Sendable {
    public let index: Int
    public let number: Int
    public let count: Int
    public let text: String
    public let state: String
    public let durationMs: Int?
    public let positionMs: Int?

    public init(
        index: Int,
        number: Int,
        count: Int,
        text: String,
        state: String,
        durationMs: Int?,
        positionMs: Int?
    ) {
        self.index = index
        self.number = number
        self.count = count
        self.text = text
        self.state = state
        self.durationMs = durationMs
        self.positionMs = positionMs
    }
}

/// A playback hold the listener's own voice caused.
///
/// The reading behind it is coarse: dictation software holds the input device
/// open for minutes after a recording, so the hold is raised on the moment the
/// floor changed hands and then left alone. Nothing releases it but the
/// listener, unless they asked for it to release itself.
public struct SpeechInterruption: Equatable, Sendable {
    public let reason: String
    public let at: Double
    /// Whether the hold will release itself once the input goes quiet.
    public let resumeArmed: Bool

    public init(reason: String, at: Double, resumeArmed: Bool) {
        self.reason = reason
        self.at = at
        self.resumeArmed = resumeArmed
    }
}

/// Which voice one speaking client holds, and who decided it.
public struct VoiceAssignment: Identifiable, Equatable, Sendable {
    public let source: String
    public let voice: String
    /// True when the listener assigned it, which outranks the client's request.
    public let pinned: Bool
    public let assignedAt: Double

    public var id: String { source }

    public init(source: String, voice: String, pinned: Bool, assignedAt: Double) {
        self.source = source
        self.voice = voice
        self.pinned = pinned
        self.assignedAt = assignedAt
    }
}

/// What the daemon does by itself when the listener starts speaking.
public enum InputInterruptResume: String, CaseIterable, Equatable, Sendable {
    /// Stay held until the listener says otherwise.
    case manual
    /// Release the hold once the input goes quiet again.
    case whenIdle = "when_idle"

    public var label: String {
        switch self {
        case .manual: "Stay paused"
        case .whenIdle: "Resume when the mic goes quiet"
        }
    }
}

/// The application-facing representation of one top-level queue item.
public struct Utterance: Identifiable, Equatable, Sendable {
    public let id: String
    public let text: String
    public let voice: String
    public let state: String
    public let durationMs: Int?
    public let playedMs: Int?
    public let positionMs: Int?
    public let error: String?
    public let finalState: String?
    public let source: String?
    public let priority: RequeuePriority
    public let enqueuedAt: Double?
    public let finishedAt: Double?
    public let segmentCount: Int
    public let completedSegments: Int
    public let activeSegment: ActiveSegment?

    public init(
        id: String,
        text: String,
        voice: String,
        state: String,
        durationMs: Int?,
        playedMs: Int?,
        positionMs: Int?,
        error: String?,
        finalState: String?,
        source: String?,
        priority: RequeuePriority,
        enqueuedAt: Double?,
        finishedAt: Double?,
        segmentCount: Int,
        completedSegments: Int,
        activeSegment: ActiveSegment?
    ) {
        self.id = id
        self.text = text
        self.voice = voice
        self.state = state
        self.durationMs = durationMs
        self.playedMs = playedMs
        self.positionMs = positionMs
        self.error = error
        self.finalState = finalState
        self.source = source
        self.priority = priority
        self.enqueuedAt = enqueuedAt
        self.finishedAt = finishedAt
        self.segmentCount = segmentCount
        self.completedSegments = completedSegments
        self.activeSegment = activeSegment
    }
}

public struct DaemonStatus: Equatable, Sendable {
    public let playbackState: String
    public let current: Utterance?
    public let counts: [String: Int]
    public let voice: String
    public let engine: String
    /// Whether some process is capturing audio input right now.
    public let inputActive: Bool
    public let interruption: SpeechInterruption?

    public init(
        playbackState: String,
        current: Utterance?,
        counts: [String: Int],
        voice: String,
        engine: String,
        inputActive: Bool = false,
        interruption: SpeechInterruption? = nil
    ) {
        self.playbackState = playbackState
        self.current = current
        self.counts = counts
        self.voice = voice
        self.engine = engine
        self.inputActive = inputActive
        self.interruption = interruption
    }
}

/// Everything a presentation adapter needs to render current speech state.
public struct Snapshot: Equatable, Sendable {
    public let status: DaemonStatus
    public let plan: [Utterance]
    public let input: [Utterance]
    public let history: [Utterance]
    public let voices: [String]
    public let speed: Double
    public let playbackRate: Double
    public let captionsEnabled: Bool
    public let captionsEnabledConfigured: Bool
    public let voiceAssignments: [VoiceAssignment]
    public let inputInterruptEnabled: Bool
    public let inputInterruptResume: InputInterruptResume

    public init(
        status: DaemonStatus,
        plan: [Utterance],
        input: [Utterance],
        history: [Utterance],
        voices: [String],
        speed: Double,
        playbackRate: Double,
        captionsEnabled: Bool = false,
        captionsEnabledConfigured: Bool = false,
        voiceAssignments: [VoiceAssignment] = [],
        inputInterruptEnabled: Bool = true,
        inputInterruptResume: InputInterruptResume = .manual
    ) {
        self.status = status
        self.plan = plan
        self.input = input
        self.history = history
        self.voices = voices
        self.speed = speed
        self.playbackRate = playbackRate
        self.captionsEnabled = captionsEnabled
        self.captionsEnabledConfigured = captionsEnabledConfigured
        self.voiceAssignments = voiceAssignments
        self.inputInterruptEnabled = inputInterruptEnabled
        self.inputInterruptResume = inputInterruptResume
    }
}
