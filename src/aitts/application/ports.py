# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Inbound application ports, expressed only in public speech schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from aitts.application.schemas import (
        AssignVoice,
        AssignVoiceReceipt,
        CancelSpeech,
        CancelSpeechReceipt,
        CaptionSettings,
        ClearQueueReceipt,
        EnqueueSpeech,
        EnqueueSpeechReceipt,
        HistoryQuery,
        HistoryView,
        PlaybackControlReceipt,
        PurgeCachedAudioReceipt,
        QueueView,
        RequeueSpeech,
        RequeueSpeechReceipt,
        SegmentStepReceipt,
        SetCaptionsEnabled,
        SpeechMetrics,
        SpeechStatus,
        VoiceAssignmentView,
        VoiceCatalog,
    )


class SpeechServicePort(Protocol):
    """Everything an external speech-control adapter may ask the application to do."""

    def enqueue_speech(self, request: EnqueueSpeech) -> EnqueueSpeechReceipt:
        """Accept speech for synthesis and eventual serialized playback."""
        ...

    def speech_status(self) -> SpeechStatus:
        """Report admission separately from the playback hold."""
        ...

    def list_queue(self) -> QueueView:
        """Return all pending clips in playback order."""
        ...

    def list_history(self, query: HistoryQuery) -> HistoryView:
        """Return terminal clips, most recent first."""
        ...

    def speech_metrics(self) -> SpeechMetrics:
        """Report synthesis and queue latency, depth, cache use and failures."""
        ...

    def list_voices(self) -> VoiceCatalog:
        """Return voices accepted by new speech submissions."""
        ...

    def get_caption_settings(self) -> CaptionSettings:
        """Return the shared on-screen caption preference."""
        ...

    def set_captions_enabled(self, request: SetCaptionsEnabled) -> CaptionSettings:
        """Persist the shared on-screen caption preference."""
        ...

    def pause_playback(self) -> PlaybackControlReceipt:
        """Hold current and future playback while continuing to accept speech."""
        ...

    def resume_playback(self) -> PlaybackControlReceipt:
        """Release the global playback hold."""
        ...

    def skip_current(self) -> PlaybackControlReceipt:
        """Finish the current clip as skipped and advance."""
        ...

    def restart_current(self) -> PlaybackControlReceipt:
        """Restart the current clip from its beginning."""
        ...

    def next_segment(self) -> SegmentStepReceipt:
        """Give up the current chunk of a document and play the next one."""
        ...

    def previous_segment(self) -> SegmentStepReceipt:
        """Replay the chunk before the current one, from its start."""
        ...

    def resume_when_input_idle(self) -> PlaybackControlReceipt:
        """Release the hold once nothing is capturing audio input."""
        ...

    def list_voice_assignments(self) -> VoiceAssignmentView:
        """Report which voice each speaking client holds."""
        ...

    def assign_voice(self, request: AssignVoice) -> AssignVoiceReceipt:
        """Assign a voice to one client, or release the assignment."""
        ...

    def cancel_speech(self, request: CancelSpeech) -> CancelSpeechReceipt:
        """Cancel one pending clip that has not started playing."""
        ...

    def requeue_speech(self, request: RequeueSpeech) -> RequeueSpeechReceipt:
        """Create a new hearing of a history item at the requested priority."""
        ...

    def clear_queue(self) -> ClearQueueReceipt:
        """Cancel every pending clip without interrupting the current clip."""
        ...

    def purge_cached_audio(self) -> PurgeCachedAudioReceipt:
        """Remove reusable audio while retaining artifacts still owed to the listener."""
        ...
