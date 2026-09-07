# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Transport-neutral public schemas for the speech application port."""

from __future__ import annotations

import enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from aitts.model import ContentFormat, Priority, Sensitivity, State

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
UtteranceId = Annotated[str, StringConstraints(pattern=r"^utt_[0-9a-f]{32}$")]
PlaybackSpeed = Annotated[float, Field(ge=0.5, le=2.0)]
PositiveLimit = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
SegmentCount = Annotated[int, Field(ge=1)]


class PublicSchema(BaseModel):
    """Strict, immutable base for every value crossing the application port."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SubmissionDisposition(enum.StrEnum):
    """What accepted speech will do next."""

    QUEUED_FOR_PLAYBACK = "queued_for_playback"
    SPOOLED_UNTIL_RESUME = "spooled_until_resume"


class PlaybackState(enum.StrEnum):
    """User-visible state of the serialized playback worker."""

    IDLE = "idle"
    SYNTHESIZING = "synthesizing"
    PLAYING = "playing"
    PAUSED = "paused"


class EnqueueSpeech(PublicSchema):
    """One request to synthesize and speak text."""

    text: NonEmptyText
    content_format: ContentFormat = ContentFormat.PLAIN_TEXT
    voice: NonEmptyText | None = None
    speed: PlaybackSpeed | None = None
    sensitivity: Sensitivity = Sensitivity.CONFIDENTIAL
    priority: Priority = Priority.NORMAL
    source: NonEmptyText | None = None


class SpeechAdmission(PublicSchema):
    """Truthful admission status shared by enqueue and status responses."""

    accepting_speech: Literal[True]
    playback_held: bool
    submission_disposition: SubmissionDisposition
    submission_guidance: NonEmptyText


class EnqueueSpeechReceipt(SpeechAdmission):
    """Receipt proving the daemon accepted a speech request."""

    accepted: Literal[True]
    id: UtteranceId
    state: State
    sensitivity: Sensitivity
    eligible_engines: tuple[str, ...]
    segment_count: SegmentCount = 1
    composite: bool = False


class ActiveSegment(PublicSchema):
    """The exact synthesized child currently owning playback."""

    index: NonNegativeInt
    number: SegmentCount
    count: SegmentCount
    text: str
    state: State
    duration_ms: NonNegativeInt | None
    position_ms: NonNegativeInt | None


class QueueItem(PublicSchema):
    """One clip in the unified pending playback plan."""

    id: UtteranceId
    text: str
    voice: str
    speed: PlaybackSpeed
    sensitivity: Sensitivity
    priority: Priority
    state: State
    enqueued_at: float
    source: str | None
    duration_ms: NonNegativeInt | None
    played_ms: NonNegativeInt | None
    error: str | None
    replay_of: UtteranceId | None
    composite: bool = False
    segment_count: SegmentCount = 1
    completed_segments: NonNegativeInt = 0


class CurrentSpeech(QueueItem):
    """The active clip plus its live playback position."""

    position_ms: NonNegativeInt | None
    active_segment: ActiveSegment | None = None


class HistoryItem(QueueItem):
    """One terminal clip retained in history."""

    final_state: State
    finished_at: float
    audio_cached: bool


class SpeechInterruption(PublicSchema):
    """A playback hold the listener's own voice caused."""

    reason: Literal["listener_speaking"]
    at: float
    resume_armed: bool


class SpeechStatus(SpeechAdmission):
    """Machine-readable service, playback, and queue state."""

    state: Literal["accepting"]
    playback_state: PlaybackState
    current: CurrentSpeech | None
    counts: dict[str, NonNegativeInt]
    engine: NonEmptyText
    voice: str
    # Whether an audio input is capturing right now. Coarse and sticky by
    # nature; it says the device is open, not that anyone is talking.
    input_active: bool = False
    interruption: SpeechInterruption | None = None


class QueueView(PublicSchema):
    """All pending clips in exact playback order."""

    items: tuple[QueueItem, ...]


class HistoryQuery(PublicSchema):
    """Pagination request for most-recent-first history."""

    limit: PositiveLimit = 20
    before: UtteranceId | None = None


class HistoryView(PublicSchema):
    """A page of terminal clips, most recent first."""

    items: tuple[HistoryItem, ...]


class VoiceCatalog(PublicSchema):
    """Voices currently accepted by the configured speech engine."""

    voices: tuple[str, ...]


class CaptionSettings(PublicSchema):
    """The shared on-screen caption preference."""

    enabled: bool


class SetCaptionsEnabled(PublicSchema):
    """Set the shared on-screen caption preference."""

    enabled: bool


class PlaybackControlReceipt(PublicSchema):
    """Playback state immediately after a transport control."""

    state: State | None
    current: UtteranceId | None
    held: bool


class CancelSpeech(PublicSchema):
    """Identify one pending clip to cancel."""

    id: UtteranceId


class CancelSpeechReceipt(PublicSchema):
    """Receipt for a successful pending-clip cancellation."""

    id: UtteranceId
    state: Literal[State.CANCELLED]


class RequeueSpeech(PublicSchema):
    """Create another hearing of a history item with selected urgency."""

    id: UtteranceId
    priority: Priority = Priority.NORMAL


class RequeueSpeechReceipt(PublicSchema):
    """Receipt for the newly created replay clip."""

    id: UtteranceId
    state: State
    priority: Priority


class ClearQueueReceipt(PublicSchema):
    """Count of pending clips cancelled by a queue clear."""

    cleared: NonNegativeInt


class PurgeCachedAudioReceipt(PublicSchema):
    """Outcome of removing audio that no current or pending speech still owns."""

    removed_files: NonNegativeInt
    removed_bytes: NonNegativeInt
    protected_files: NonNegativeInt
    protected_bytes: NonNegativeInt
    failed_files: NonNegativeInt
    failed_bytes: NonNegativeInt


class SpeechServiceError(RuntimeError):
    """A stable application error that does not expose its transport adapter."""

    def __init__(self, code: str, message: str) -> None:
        """Create a public error with a machine-readable code."""
        super().__init__(message)
        self.code = code
