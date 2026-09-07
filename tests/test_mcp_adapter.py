# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""MCP adapter contracts through the official in-memory MCP client."""

from __future__ import annotations

from typing import Any

import pytest
from mcp import Client as MCPClient

from aitts.adapters.mcp import create_server
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
    PlaybackState,
    PurgeCachedAudioReceipt,
    QueueView,
    RequeueSpeech,
    RequeueSpeechReceipt,
    SegmentStepReceipt,
    SetCaptionsEnabled,
    SpeechServiceError,
    SpeechStatus,
    SubmissionDisposition,
    VoiceAssignmentRecord,
    VoiceAssignmentView,
    VoiceCatalog,
)
from aitts.model import ContentFormat, Priority, Sensitivity, State

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("MCP v2 tool schema plus approved AI-TTS application-port contract"),
]

UTTERANCE_ID = "utt_0123456789abcdef0123456789abcdef"
REPLAY_ID = "utt_fedcba9876543210fedcba9876543210"

TOOL_NAMES = {
    "enqueue_speech",
    "get_caption_settings",
    "set_captions_enabled",
    "speech_status",
    "list_speech_queue",
    "list_speech_history",
    "list_speech_voices",
    "pause_speech_playback",
    "resume_speech_playback",
    "skip_current_speech",
    "restart_current_speech",
    "cancel_queued_speech",
    "requeue_speech",
    "clear_speech_queue",
    "purge_cached_audio",
    # Parity with the tray: nothing it can do is unavailable to an agent.
    "next_speech_chunk",
    "previous_speech_chunk",
    "resume_speech_when_input_idle",
    "list_speech_voice_assignments",
    "assign_speech_voice",
}


def admission(*, held: bool) -> dict[str, Any]:
    """Return approved admission fields for a fake port response."""
    return {
        "accepting_speech": True,
        "playback_held": held,
        "submission_disposition": (
            SubmissionDisposition.SPOOLED_UNTIL_RESUME
            if held
            else SubmissionDisposition.QUEUED_FOR_PLAYBACK
        ),
        "submission_guidance": (
            "Speak freely: playback is paused, but speech is accepted and spooled until Resume."
            if held
            else "Speak freely: speech is accepted into the playback queue."
        ),
    }


class FakeSpeechPort:
    """Owned fake implementing the same public schema contract as the real socket adapter."""

    def __init__(self, *, held: bool = False, fail_status: bool = False) -> None:
        self.segment_steps: list[str] = []
        self.resume_armed = False
        self.assign_calls: list[AssignVoice] = []
        self.assignments: list[VoiceAssignmentRecord] = [
            VoiceAssignmentRecord(source="codex", voice="bm_george", pinned=False, assigned_at=1.0)
        ]
        self.held = held
        self.fail_status = fail_status
        self.captions_enabled = False
        self.enqueued: list[EnqueueSpeech] = []
        self.purge_calls = 0

    def enqueue_speech(self, request: EnqueueSpeech) -> EnqueueSpeechReceipt:
        self.enqueued.append(request)
        return EnqueueSpeechReceipt(
            accepted=True,
            id=UTTERANCE_ID,
            state=State.QUEUED,
            sensitivity=request.sensitivity,
            eligible_engines=("local",),
            **admission(held=self.held),
        )

    def speech_status(self) -> SpeechStatus:
        if self.fail_status:
            code = "unreachable"
            message = "daemon unavailable"
            raise SpeechServiceError(code, message)
        return SpeechStatus(
            state="accepting",
            playback_state=PlaybackState.PAUSED if self.held else PlaybackState.IDLE,
            current=None,
            counts={},
            engine="fake",
            voice="bm_daniel",
            **admission(held=self.held),
        )

    def list_queue(self) -> QueueView:
        return QueueView(items=())

    def list_history(self, query: HistoryQuery) -> HistoryView:
        del query
        return HistoryView(items=())

    def list_voices(self) -> VoiceCatalog:
        return VoiceCatalog(voices=("bm_daniel",))

    def get_caption_settings(self) -> CaptionSettings:
        return CaptionSettings(enabled=self.captions_enabled)

    def set_captions_enabled(self, request: SetCaptionsEnabled) -> CaptionSettings:
        self.captions_enabled = request.enabled
        return CaptionSettings(enabled=self.captions_enabled)

    def pause_playback(self) -> PlaybackControlReceipt:
        self.held = True
        return PlaybackControlReceipt(state=None, current=None, held=True)

    def resume_playback(self) -> PlaybackControlReceipt:
        self.held = False
        return PlaybackControlReceipt(state=None, current=None, held=False)

    def skip_current(self) -> PlaybackControlReceipt:
        return PlaybackControlReceipt(state=None, current=None, held=self.held)

    def restart_current(self) -> PlaybackControlReceipt:
        return PlaybackControlReceipt(state=None, current=None, held=self.held)

    def next_segment(self) -> SegmentStepReceipt:
        self.segment_steps.append("next")
        return SegmentStepReceipt(
            state=State.PLAYING,
            current=None,
            held=self.held,
            segment_index=1,
            segment_number=2,
        )

    def previous_segment(self) -> SegmentStepReceipt:
        self.segment_steps.append("previous")
        return SegmentStepReceipt(
            state=State.PLAYING,
            current=None,
            held=self.held,
            segment_index=0,
            segment_number=1,
        )

    def resume_when_input_idle(self) -> PlaybackControlReceipt:
        self.resume_armed = True
        return PlaybackControlReceipt(state=None, current=None, held=True)

    def list_voice_assignments(self) -> VoiceAssignmentView:
        return VoiceAssignmentView(assignments=tuple(self.assignments))

    def assign_voice(self, request: AssignVoice) -> AssignVoiceReceipt:
        self.assign_calls.append(request)
        if request.voice is None:
            self.assignments = [item for item in self.assignments if item.source != request.source]
            return AssignVoiceReceipt(assignment=None)
        record = VoiceAssignmentRecord(
            source=request.source, voice=request.voice, pinned=True, assigned_at=1.0
        )
        self.assignments = [item for item in self.assignments if item.source != request.source] + [
            record
        ]
        return AssignVoiceReceipt(assignment=record)

    def cancel_speech(self, request: CancelSpeech) -> CancelSpeechReceipt:
        return CancelSpeechReceipt(id=request.id, state=State.CANCELLED)

    def requeue_speech(self, request: RequeueSpeech) -> RequeueSpeechReceipt:
        return RequeueSpeechReceipt(id=REPLAY_ID, state=State.QUEUED, priority=request.priority)

    def clear_queue(self) -> ClearQueueReceipt:
        return ClearQueueReceipt(cleared=0)

    def purge_cached_audio(self) -> PurgeCachedAudioReceipt:
        self.purge_calls += 1
        return PurgeCachedAudioReceipt(
            removed_files=2,
            removed_bytes=13,
            protected_files=1,
            protected_bytes=6,
            failed_files=0,
            failed_bytes=0,
        )


async def test_mcp_publishes_typed_tool_schemas() -> None:
    """Oracle: explicit MCP tool inventory and JSON Schema constraints approved for agents."""
    async with MCPClient(create_server(FakeSpeechPort()), raise_exceptions=True) as client:
        result = await client.list_tools()

    tools = {tool.name: tool for tool in result.tools}
    assert set(tools) == TOOL_NAMES
    assert len(tools) == len(TOOL_NAMES)
    assert all(tool.output_schema is not None for tool in tools.values())
    enqueue_schema = tools["enqueue_speech"].input_schema
    assert enqueue_schema["required"] == ["text"]
    assert enqueue_schema["properties"]["content_format"]["default"] == "plain_text"
    assert enqueue_schema["$defs"]["ContentFormat"]["enum"] == ["plain_text", "markdown"]
    assert enqueue_schema["properties"]["sensitivity"]["default"] == "confidential"
    assert enqueue_schema["$defs"]["Priority"]["enum"] == ["normal", "urgent"]
    purge_annotations = tools["purge_cached_audio"].annotations
    assert purge_annotations is not None
    assert purge_annotations.destructive_hint is True
    assert purge_annotations.idempotent_hint is True


async def test_mcp_enqueue_maps_flat_arguments_to_the_public_command() -> None:
    """Oracle: agent-facing enqueue arguments map exactly once into the application port."""
    port = FakeSpeechPort(held=True)
    async with MCPClient(create_server(port), raise_exceptions=True) as client:
        result = await client.call_tool(
            "enqueue_speech",
            {
                "text": "hello from an agent",
                "content_format": "markdown",
                "voice": "bm_daniel",
                "speed": 1.25,
                "sensitivity": "internal",
                "priority": "urgent",
                "source": "codex",
            },
        )

    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["playback_held"] is True
    assert result.structured_content["submission_disposition"] == "spooled_until_resume"
    assert port.enqueued == [
        EnqueueSpeech(
            text="hello from an agent",
            content_format=ContentFormat.MARKDOWN,
            voice="bm_daniel",
            speed=1.25,
            sensitivity=Sensitivity.INTERNAL,
            priority=Priority.URGENT,
            source="codex",
        )
    ]


async def test_mcp_caption_tools_read_and_persist_the_shared_preference() -> None:
    """Oracle: caption reads and writes cross the typed application port exactly once."""
    port = FakeSpeechPort()
    async with MCPClient(create_server(port), raise_exceptions=True) as client:
        before = await client.call_tool("get_caption_settings", {})
        changed = await client.call_tool("set_captions_enabled", {"enabled": True})
        after = await client.call_tool("get_caption_settings", {})

    assert before.structured_content == {"enabled": False}
    assert changed.structured_content == {"enabled": True}
    assert after.structured_content == {"enabled": True}
    assert port.captions_enabled is True


async def test_mcp_cache_purge_returns_the_typed_storage_receipt() -> None:
    port = FakeSpeechPort()
    async with MCPClient(create_server(port), raise_exceptions=True) as client:
        result = await client.call_tool("purge_cached_audio", {})

    assert result.is_error is False
    assert result.structured_content == {
        "removed_files": 2,
        "removed_bytes": 13,
        "protected_files": 1,
        "protected_bytes": 6,
        "failed_files": 0,
        "failed_bytes": 0,
    }
    assert port.purge_calls == 1


async def test_mcp_status_error_is_visible_to_the_model() -> None:
    """Oracle: MCP tool failures preserve the public error code for agent recovery."""
    async with MCPClient(create_server(FakeSpeechPort(fail_status=True))) as client:
        result = await client.call_tool("speech_status", {})

    assert result.is_error is True
    assert result.structured_content is None
    assert "unreachable: daemon unavailable" in result.content[0].text  # type: ignore[union-attr]


async def test_mcp_chunk_tools_step_within_the_current_document() -> None:
    port = FakeSpeechPort()
    async with MCPClient(create_server(port), raise_exceptions=True) as client:
        forwards = await client.call_tool("next_speech_chunk", {})
        backwards = await client.call_tool("previous_speech_chunk", {})

    assert port.segment_steps == ["next", "previous"]
    assert forwards.structured_content is not None
    assert forwards.structured_content["segment_number"] == 2
    assert backwards.structured_content is not None
    assert backwards.structured_content["segment_number"] == 1


async def test_mcp_can_defer_a_resume_until_the_listener_stops_speaking() -> None:
    port = FakeSpeechPort()
    async with MCPClient(create_server(port), raise_exceptions=True) as client:
        receipt = await client.call_tool("resume_speech_when_input_idle", {})

    assert port.resume_armed is True
    # The hold is still in force; it releases itself later.
    assert receipt.structured_content is not None
    assert receipt.structured_content["held"] is True


async def test_mcp_reads_the_voice_register() -> None:
    async with MCPClient(create_server(FakeSpeechPort()), raise_exceptions=True) as client:
        result = await client.call_tool("list_speech_voice_assignments", {})

    assert result.structured_content is not None
    assignments = result.structured_content["assignments"]
    assert [item["source"] for item in assignments] == ["codex"]
    assert assignments[0]["pinned"] is False


async def test_mcp_assigns_and_releases_a_clients_voice() -> None:
    port = FakeSpeechPort()
    async with MCPClient(create_server(port), raise_exceptions=True) as client:
        assigned = await client.call_tool(
            "assign_speech_voice", {"source": "claude-code", "voice": "af_heart"}
        )
        released = await client.call_tool("assign_speech_voice", {"source": "claude-code"})

    assert assigned.structured_content is not None
    record = assigned.structured_content["assignment"]
    assert record["voice"] == "af_heart"
    # An assignment made through the port is the listener's, so it is pinned.
    assert record["pinned"] is True
    # Omitting the voice releases it rather than assigning something empty.
    assert released.structured_content is not None
    assert released.structured_content["assignment"] is None
    assert [request.voice for request in port.assign_calls] == ["af_heart", None]
