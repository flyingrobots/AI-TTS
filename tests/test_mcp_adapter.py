# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""MCP adapter contracts through the official in-memory MCP client."""

from __future__ import annotations

from typing import Any

import pytest
from mcp import Client as MCPClient

from aitts.adapters.mcp import create_server
from aitts.application.schemas import (
    CancelSpeech,
    CancelSpeechReceipt,
    ClearQueueReceipt,
    EnqueueSpeech,
    EnqueueSpeechReceipt,
    HistoryQuery,
    HistoryView,
    PlaybackControlReceipt,
    PlaybackState,
    QueueView,
    RequeueSpeech,
    RequeueSpeechReceipt,
    SpeechServiceError,
    SpeechStatus,
    SubmissionDisposition,
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
        self.held = held
        self.fail_status = fail_status
        self.enqueued: list[EnqueueSpeech] = []

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

    def cancel_speech(self, request: CancelSpeech) -> CancelSpeechReceipt:
        return CancelSpeechReceipt(id=request.id, state=State.CANCELLED)

    def requeue_speech(self, request: RequeueSpeech) -> RequeueSpeechReceipt:
        return RequeueSpeechReceipt(id=REPLAY_ID, state=State.QUEUED, priority=request.priority)

    def clear_queue(self) -> ClearQueueReceipt:
        return ClearQueueReceipt(cleared=0)


async def test_mcp_publishes_typed_tool_schemas() -> None:
    """Oracle: explicit MCP tool inventory and JSON Schema constraints approved for agents."""
    async with MCPClient(create_server(FakeSpeechPort()), raise_exceptions=True) as client:
        result = await client.list_tools()

    tools = {tool.name: tool for tool in result.tools}
    assert set(tools) == TOOL_NAMES
    assert len(tools) == 12
    assert all(tool.output_schema is not None for tool in tools.values())
    enqueue_schema = tools["enqueue_speech"].input_schema
    assert enqueue_schema["required"] == ["text"]
    assert enqueue_schema["properties"]["content_format"]["default"] == "plain_text"
    assert enqueue_schema["$defs"]["ContentFormat"]["enum"] == ["plain_text", "markdown"]
    assert enqueue_schema["properties"]["sensitivity"]["default"] == "confidential"
    assert enqueue_schema["$defs"]["Priority"]["enum"] == ["normal", "urgent"]


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


async def test_mcp_status_error_is_visible_to_the_model() -> None:
    """Oracle: MCP tool failures preserve the public error code for agent recovery."""
    async with MCPClient(create_server(FakeSpeechPort(fail_status=True))) as client:
        result = await client.call_tool("speech_status", {})

    assert result.is_error is True
    assert result.structured_content is None
    assert "unreachable: daemon unavailable" in result.content[0].text  # type: ignore[union-attr]
