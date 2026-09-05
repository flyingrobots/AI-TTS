# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Unix-socket adapter mapping contracts, without opening a socket."""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aitts.adapters.unix_socket import UnixSocketSpeechAdapter
from aitts.application.schemas import (
    CaptionSettings,
    EnqueueSpeech,
    EnqueueSpeechReceipt,
    SetCaptionsEnabled,
    SpeechServiceError,
)
from aitts.client import DaemonError, DaemonUnreachableError
from aitts.model import ContentFormat, Priority, Sensitivity, State

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("daemon NDJSON protocol and public speech-schema contract"),
]

UTTERANCE_ID = "utt_0123456789abcdef0123456789abcdef"


class ScriptedClient:
    """One-response wire double whose interaction is itself the adapter contract."""

    def __init__(self, response: dict[str, Any] | Exception) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(payload)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def enqueue_response(sensitivity: Sensitivity = Sensitivity.CONFIDENTIAL) -> dict[str, Any]:
    """Return the daemon protocol's valid enqueue receipt."""
    return {
        "ok": True,
        "accepted": True,
        "id": UTTERANCE_ID,
        "state": State.QUEUED.value,
        "sensitivity": sensitivity.value,
        "eligible_engines": ["local"],
        "accepting_speech": True,
        "playback_held": False,
        "submission_disposition": "queued_for_playback",
        "submission_guidance": "Speak freely: speech is accepted into the playback queue.",
    }


@settings(max_examples=50, derandomize=True, database=None)
@given(
    text=st.text(min_size=1, max_size=100).filter(lambda value: bool(value.strip())),
    content_format=st.sampled_from(list(ContentFormat)),
    speed=st.none() | st.floats(min_value=0.5, max_value=2.0, allow_nan=False),
    sensitivity=st.sampled_from(list(Sensitivity)),
    priority=st.sampled_from(list(Priority)),
)
def test_enqueue_encodes_generated_commands_as_json_safe_daemon_requests(
    text: str,
    content_format: ContentFormat,
    speed: float | None,
    sensitivity: Sensitivity,
    priority: Priority,
) -> None:
    """Oracle: daemon submit operation fields and JSONL-safe JSON value grammar."""
    client = ScriptedClient(enqueue_response(sensitivity))
    adapter = UnixSocketSpeechAdapter(client)
    request = EnqueueSpeech(
        text=text,
        content_format=content_format,
        speed=speed,
        sensitivity=sensitivity,
        priority=priority,
        source="test-agent",
    )

    adapter.enqueue_speech(request)

    encoded = json.loads(json.dumps(client.requests[0]))
    assert encoded == {"op": "submit", **request.model_dump(mode="json", exclude_none=True)}


def test_enqueue_decodes_daemon_receipt_as_public_schema() -> None:
    """Oracle: public enqueue receipt schema and fail-closed sensitivity requirement."""
    adapter = UnixSocketSpeechAdapter(ScriptedClient(enqueue_response()))

    receipt = adapter.enqueue_speech(EnqueueSpeech(text="hello"))

    assert receipt == EnqueueSpeechReceipt.model_validate(
        {key: value for key, value in enqueue_response().items() if key != "ok"}
    )


def test_queue_uses_the_daemon_unified_playback_plan() -> None:
    """Oracle: approved single queue is the snapshot plan, not either legacy queue."""
    item = {
        "id": UTTERANCE_ID,
        "text": "hello",
        "voice": "bm_daniel",
        "speed": 1.0,
        "sensitivity": "confidential",
        "priority": "normal",
        "state": "Ready",
        "enqueued_at": 1.0,
        "source": "test-agent",
        "duration_ms": 100,
        "played_ms": None,
        "error": None,
        "replay_of": None,
    }
    client = ScriptedClient({"ok": True, "plan": [item], "input": [], "playback": []})

    view = UnixSocketSpeechAdapter(client).list_queue()

    assert [entry.id for entry in view.items] == [UTTERANCE_ID]


def test_caption_settings_map_to_the_daemon_settings_operation() -> None:
    """Oracle: caption preference uses one typed port over the existing settings wire."""
    read_client = ScriptedClient({"ok": True, "settings": {"captions_enabled": False}})
    write_client = ScriptedClient({"ok": True, "settings": {"captions_enabled": True}})

    before = UnixSocketSpeechAdapter(read_client).get_caption_settings()
    after = UnixSocketSpeechAdapter(write_client).set_captions_enabled(
        SetCaptionsEnabled(enabled=True)
    )

    assert before == CaptionSettings(enabled=False)
    assert after == CaptionSettings(enabled=True)
    assert read_client.requests == [{"op": "settings"}]
    assert write_client.requests == [{"op": "settings", "set": {"captions_enabled": True}}]


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("pause_playback", {"op": "pause"}),
        ("resume_playback", {"op": "resume"}),
        ("skip_current", {"op": "skip"}),
        ("restart_current", {"op": "rewind"}),
        ("clear_queue", {"op": "clear", "queue": "queue"}),
    ],
)
def test_controls_encode_their_declared_daemon_operation(
    method: str, expected: dict[str, object]
) -> None:
    """Oracle: daemon transport-control operation table."""
    response: dict[str, Any]
    if method == "clear_queue":
        response = {"ok": True, "cleared": 0}
    else:
        response = {"ok": True, "state": None, "current": None, "held": method == "pause_playback"}
    client = ScriptedClient(response)
    adapter = UnixSocketSpeechAdapter(client)

    getattr(adapter, method)()

    assert client.requests == [expected]


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (DaemonError("bad_request", "nope"), "bad_request"),
        (DaemonUnreachableError("gone"), "unreachable"),
    ],
)
def test_transport_failures_become_public_service_errors(failure: Exception, code: str) -> None:
    """Oracle: hexagonal port must not leak Unix-socket exception types."""
    adapter = UnixSocketSpeechAdapter(ScriptedClient(failure))

    with pytest.raises(SpeechServiceError) as error:
        adapter.speech_status()

    assert error.value.code == code


def test_invalid_daemon_response_fails_closed_at_decode_boundary() -> None:
    """Oracle: closed public response schema; malformed wire success is never trusted."""
    adapter = UnixSocketSpeechAdapter(ScriptedClient({"ok": True, "state": "accepting"}))

    with pytest.raises(SpeechServiceError) as error:
        adapter.speech_status()

    assert error.value.code == "invalid_response"
