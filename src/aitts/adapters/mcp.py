# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""JSONL-over-stdio MCP adapter for the public speech application port."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field, StringConstraints

from aitts import __version__
from aitts.adapters.unix_socket import UnixSocketSpeechAdapter
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
    SpeechServiceError,
    SpeechStatus,
    UtteranceId,
    VoiceCatalog,
)
from aitts.model import ContentFormat, Priority, Sensitivity
from aitts.paths import default_socket

if TYPE_CHECKING:
    from collections.abc import Callable

    from aitts.application.ports import SpeechServicePort

_READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
_IDEMPOTENT_WRITE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
_DESTRUCTIVE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=False,
)


def _invoke[ResultT](call: Callable[[], ResultT]) -> ResultT:
    """Translate stable application failures into model-visible MCP tool failures."""
    try:
        return call()
    except SpeechServiceError as exc:
        message = f"{exc.code}: {exc}"
        raise ToolError(message) from exc


def create_server(speech: SpeechServicePort) -> MCPServer:
    """Build an MCP server around a speech port, without choosing its transport."""
    server = MCPServer(
        name="ai-tts",
        title="AI-TTS",
        description="Queue local speech and control serialized playback.",
        version=__version__,
        instructions=(
            "Always enqueue requested speech, including while playback is held. "
            "A held player still accepts and synthesizes speech; it spools audio until Resume."
        ),
    )

    _register_submission_tools(server, speech)
    _register_query_tools(server, speech)
    _register_caption_tools(server, speech)
    _register_playback_tools(server, speech)
    _register_queue_tools(server, speech)
    return server


def _register_submission_tools(server: MCPServer, speech: SpeechServicePort) -> None:
    @server.tool(annotations=_WRITE)
    def enqueue_speech(  # noqa: PLR0913, PLR0917 - flat arguments are the public tool UX
        text: Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1),
            Field(description="Text to synthesize and speak."),
        ],
        content_format: Annotated[
            ContentFormat,
            Field(description="Interpret text literally or project Markdown syntax for speech."),
        ] = ContentFormat.PLAIN_TEXT,
        voice: Annotated[
            str | None,
            Field(description="Voice id; omit for the user's default."),
        ] = None,
        speed: Annotated[
            float | None,
            Field(ge=0.5, le=2.0, description="Playback speed; omit for the user's default."),
        ] = None,
        sensitivity: Sensitivity = Sensitivity.CONFIDENTIAL,
        priority: Priority = Priority.NORMAL,
        source: Annotated[
            str | None,
            Field(description="Calling agent identity recorded with the clip."),
        ] = "mcp",
    ) -> EnqueueSpeechReceipt:
        """Queue speech even when playback is globally paused; held speech is safely spooled."""
        request = EnqueueSpeech(
            text=text,
            content_format=content_format,
            voice=voice,
            speed=speed,
            sensitivity=sensitivity,
            priority=priority,
            source=source,
        )
        return _invoke(lambda: speech.enqueue_speech(request))

    @server.tool(annotations=_WRITE)
    def requeue_speech(
        utterance_id: Annotated[
            UtteranceId,
            Field(description="Terminal history utterance id."),
        ],
        priority: Priority = Priority.NORMAL,
    ) -> RequeueSpeechReceipt:
        """Create a new hearing of a history clip, optionally urgent at the head of the queue."""
        request = RequeueSpeech(id=utterance_id, priority=priority)
        return _invoke(lambda: speech.requeue_speech(request))


def _register_query_tools(server: MCPServer, speech: SpeechServicePort) -> None:

    @server.tool(annotations=_READ_ONLY)
    def speech_status() -> SpeechStatus:
        """Report admission and playback hold separately; held never means refusing speech."""
        return _invoke(speech.speech_status)

    @server.tool(annotations=_READ_ONLY)
    def list_speech_queue() -> QueueView:
        """List every pending clip in exact playback order."""
        return _invoke(speech.list_queue)

    @server.tool(annotations=_READ_ONLY)
    def list_speech_history(
        limit: Annotated[int, Field(ge=1, description="Maximum terminal clips to return.")] = 20,
        before: Annotated[
            UtteranceId | None,
            Field(description="Return clips older than this utterance id."),
        ] = None,
    ) -> HistoryView:
        """List terminal clips from most recent to least recent."""
        query = HistoryQuery(limit=limit, before=before)
        return _invoke(lambda: speech.list_history(query))

    @server.tool(annotations=_READ_ONLY)
    def list_speech_voices() -> VoiceCatalog:
        """List voice ids accepted by enqueue_speech."""
        return _invoke(speech.list_voices)


def _register_caption_tools(server: MCPServer, speech: SpeechServicePort) -> None:
    @server.tool(annotations=_READ_ONLY)
    def get_caption_settings() -> CaptionSettings:
        """Report whether the user's on-screen captions are enabled."""
        return _invoke(speech.get_caption_settings)

    @server.tool(annotations=_IDEMPOTENT_WRITE)
    def set_captions_enabled(
        enabled: bool,  # noqa: FBT001 - boolean is the public toggle schema
    ) -> CaptionSettings:
        """Enable or disable the user's on-screen captions without changing playback."""
        return _invoke(lambda: speech.set_captions_enabled(SetCaptionsEnabled(enabled=enabled)))


def _register_playback_tools(server: MCPServer, speech: SpeechServicePort) -> None:

    @server.tool(annotations=_IDEMPOTENT_WRITE)
    def pause_speech_playback() -> PlaybackControlReceipt:
        """Hold all playback globally while continuing to accept and synthesize incoming speech."""
        return _invoke(speech.pause_playback)

    @server.tool(annotations=_IDEMPOTENT_WRITE)
    def resume_speech_playback() -> PlaybackControlReceipt:
        """Release the global hold and continue through the queued playback plan."""
        return _invoke(speech.resume_playback)

    @server.tool(annotations=_WRITE)
    def skip_current_speech() -> PlaybackControlReceipt:
        """Mark the current clip skipped and advance without releasing a global hold."""
        return _invoke(speech.skip_current)

    @server.tool(annotations=_WRITE)
    def restart_current_speech() -> PlaybackControlReceipt:
        """Restart the current clip from the beginning without releasing a global hold."""
        return _invoke(speech.restart_current)


def _register_queue_tools(server: MCPServer, speech: SpeechServicePort) -> None:

    @server.tool(annotations=_WRITE)
    def cancel_queued_speech(
        utterance_id: Annotated[
            UtteranceId,
            Field(description="Pending utterance id to cancel."),
        ],
    ) -> CancelSpeechReceipt:
        """Cancel one queued, synthesizing, or ready clip that has not started playing."""
        request = CancelSpeech(id=utterance_id)
        return _invoke(lambda: speech.cancel_speech(request))

    @server.tool(annotations=_DESTRUCTIVE)
    def clear_speech_queue() -> ClearQueueReceipt:
        """Cancel every pending clip without interrupting the clip currently playing."""
        return _invoke(speech.clear_queue)


def main() -> None:
    """Run the MCP adapter exclusively as newline-delimited JSON over stdio."""
    speech = UnixSocketSpeechAdapter.connect(default_socket())
    create_server(speech).run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover - console entry point
    main()
