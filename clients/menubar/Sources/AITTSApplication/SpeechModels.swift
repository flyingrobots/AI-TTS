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

    public init(
        playbackState: String,
        current: Utterance?,
        counts: [String: Int],
        voice: String,
        engine: String
    ) {
        self.playbackState = playbackState
        self.current = current
        self.counts = counts
        self.voice = voice
        self.engine = engine
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

    public init(
        status: DaemonStatus,
        plan: [Utterance],
        input: [Utterance],
        history: [Utterance],
        voices: [String],
        speed: Double,
        playbackRate: Double
    ) {
        self.status = status
        self.plan = plan
        self.input = input
        self.history = history
        self.voices = voices
        self.speed = speed
        self.playbackRate = playbackRate
    }
}
