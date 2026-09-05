# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Inbound application ports, expressed only in public speech schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from aitts.application.schemas import (
        CancelSpeech,
        CancelSpeechReceipt,
        CaptionSettings,
        ClearQueueReceipt,
        EnqueueSpeech,
        EnqueueSpeechReceipt,
        HistoryQuery,
        HistoryView,
        PlaybackControlReceipt,
        QueueView,
        RequeueSpeech,
        RequeueSpeechReceipt,
        SetCaptionsEnabled,
        SpeechStatus,
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

    def cancel_speech(self, request: CancelSpeech) -> CancelSpeechReceipt:
        """Cancel one pending clip that has not started playing."""
        ...

    def requeue_speech(self, request: RequeueSpeech) -> RequeueSpeechReceipt:
        """Create a new hearing of a history item at the requested priority."""
        ...

    def clear_queue(self) -> ClearQueueReceipt:
        """Cancel every pending clip without interrupting the current clip."""
        ...
