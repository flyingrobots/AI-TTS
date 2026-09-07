# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Unix-socket adapter for the public speech application port."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from pydantic import ValidationError

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
    PublicSchema,
    PurgeCachedAudioReceipt,
    QueueView,
    RequeueSpeech,
    RequeueSpeechReceipt,
    SegmentStepReceipt,
    SetCaptionsEnabled,
    SpeechServiceError,
    SpeechStatus,
    VoiceAssignmentView,
    VoiceCatalog,
)
from aitts.client import Client, DaemonError, DaemonUnreachableError

if TYPE_CHECKING:
    from pathlib import Path

SchemaT = TypeVar("SchemaT", bound=PublicSchema)


class DaemonRequestClient(Protocol):
    """Raw request boundary consumed by this encoding adapter."""

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Exchange one daemon NDJSON request and response."""
        ...


class UnixSocketSpeechAdapter:
    """Encode public commands to daemon NDJSON and decode typed public results."""

    def __init__(self, client: DaemonRequestClient) -> None:
        """Wrap a raw daemon request client."""
        self._client = client

    @classmethod
    def connect(cls, socket_path: Path) -> UnixSocketSpeechAdapter:
        """Connect the adapter to a daemon Unix-socket path."""
        return cls(Client(socket_path))

    def enqueue_speech(self, request: EnqueueSpeech) -> EnqueueSpeechReceipt:
        """Encode one speech request and decode its admission receipt."""
        payload = {"op": "submit", **request.model_dump(mode="json", exclude_none=True)}
        return self._exchange(payload, EnqueueSpeechReceipt)

    def speech_status(self) -> SpeechStatus:
        """Decode daemon admission and playback state."""
        return self._exchange({"op": "status"}, SpeechStatus)

    def list_queue(self) -> QueueView:
        """Decode the daemon snapshot's unified pending plan."""
        response = self._request({"op": "snapshot", "limit": 1})
        return self._decode(QueueView, {"items": response.get("plan")})

    def list_history(self, query: HistoryQuery) -> HistoryView:
        """Encode history pagination and decode terminal items."""
        payload = {"op": "history", **query.model_dump(mode="json", exclude_none=True)}
        response = self._request(payload)
        return self._decode(HistoryView, {"items": response.get("items")})

    def list_voices(self) -> VoiceCatalog:
        """Decode the daemon's current voice catalog."""
        return self._exchange({"op": "voices"}, VoiceCatalog)

    def get_caption_settings(self) -> CaptionSettings:
        """Decode the shared on-screen caption preference."""
        response = self._request({"op": "settings"})
        return self._decode_caption_settings(response)

    def set_captions_enabled(self, request: SetCaptionsEnabled) -> CaptionSettings:
        """Persist and decode the shared on-screen caption preference."""
        response = self._request({"op": "settings", "set": {"captions_enabled": request.enabled}})
        return self._decode_caption_settings(response)

    def pause_playback(self) -> PlaybackControlReceipt:
        """Send a global playback hold."""
        return self._exchange({"op": "pause"}, PlaybackControlReceipt)

    def resume_playback(self) -> PlaybackControlReceipt:
        """Release the global playback hold."""
        return self._exchange({"op": "resume"}, PlaybackControlReceipt)

    def skip_current(self) -> PlaybackControlReceipt:
        """Skip the current clip."""
        return self._exchange({"op": "skip"}, PlaybackControlReceipt)

    def restart_current(self) -> PlaybackControlReceipt:
        """Restart the current clip from zero."""
        return self._exchange({"op": "rewind"}, PlaybackControlReceipt)

    def next_segment(self) -> SegmentStepReceipt:
        """Give up the current chunk and move to the next one."""
        return self._exchange({"op": "next_segment"}, SegmentStepReceipt)

    def previous_segment(self) -> SegmentStepReceipt:
        """Replay the chunk before the current one."""
        return self._exchange({"op": "previous_segment"}, SegmentStepReceipt)

    def resume_when_input_idle(self) -> PlaybackControlReceipt:
        """Arm a release of the hold for when audio input goes quiet."""
        return self._exchange({"op": "resume_when_input_idle"}, PlaybackControlReceipt)

    def list_voice_assignments(self) -> VoiceAssignmentView:
        """Read the voice register."""
        return self._exchange({"op": "voice_assignments"}, VoiceAssignmentView)

    def assign_voice(self, request: AssignVoice) -> AssignVoiceReceipt:
        """Assign or release one client's voice.

        A null voice is omitted rather than sent: the protocol spells release
        by leaving the field out.
        """
        payload: dict[str, Any] = {"op": "assign_voice", "source": request.source}
        if request.voice is not None:
            payload["voice"] = request.voice
        return self._exchange(payload, AssignVoiceReceipt)

    def cancel_speech(self, request: CancelSpeech) -> CancelSpeechReceipt:
        """Encode a targeted cancellation."""
        return self._exchange({"op": "cancel", "id": request.id}, CancelSpeechReceipt)

    def requeue_speech(self, request: RequeueSpeech) -> RequeueSpeechReceipt:
        """Encode a history replay with explicit urgency."""
        payload = {"op": "requeue", **request.model_dump(mode="json")}
        return self._exchange(payload, RequeueSpeechReceipt)

    def clear_queue(self) -> ClearQueueReceipt:
        """Cancel every pending clip without touching the current clip."""
        return self._exchange({"op": "clear", "queue": "queue"}, ClearQueueReceipt)

    def purge_cached_audio(self) -> PurgeCachedAudioReceipt:
        """Remove cached audio not owned by current or pending speech."""
        return self._exchange({"op": "purge_cache"}, PurgeCachedAudioReceipt)

    def _exchange(self, payload: dict[str, Any], schema: type[SchemaT]) -> SchemaT:
        response = self._request(payload)
        public = {key: value for key, value in response.items() if key != "ok"}
        return self._decode(schema, public)

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._client.request(payload)
        except DaemonError as exc:
            raise SpeechServiceError(exc.error_type, str(exc)) from exc
        except DaemonUnreachableError as exc:
            code = "unreachable"
            raise SpeechServiceError(code, str(exc)) from exc

    @classmethod
    def _decode_caption_settings(cls, response: dict[str, Any]) -> CaptionSettings:
        settings = response.get("settings")
        enabled = settings.get("captions_enabled") if isinstance(settings, dict) else None
        return cls._decode(CaptionSettings, {"enabled": enabled})

    @staticmethod
    def _decode(schema: type[SchemaT], payload: object) -> SchemaT:
        try:
            return schema.model_validate(payload)
        except ValidationError as exc:
            msg = f"daemon returned a response outside the public {schema.__name__} schema"
            code = "invalid_response"
            raise SpeechServiceError(code, msg) from exc
