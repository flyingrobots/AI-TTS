# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Fixed socket scenarios and an explicit, type-sensitive volatility mask."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

SCENARIOS = (
    "submit",
    "status",
    "list",
    "history",
    "pause",
    "resume",
    "skip",
    "settings",
    "subscribe",
)
_ID = re.compile(r"utt_[0-9a-f]{32}\Z")
_TIMES = {"enqueued_at", "finished_at", "submitted_at", "state_changed_at", "at"}


class _Mask:
    def __init__(self, home: Path) -> None:
        self.home = home
        self.identifiers: dict[str, str] = {}

    def identifier(self, raw: str) -> str:
        return self.identifiers.setdefault(raw, f"<id:{len(self.identifiers) + 1}>")

    def audio_path(self, item: str) -> str:
        components = item[len(str(self.home)) + 1 :].split("/")
        for index, component in enumerate(components):
            stem, suffix = (
                (component[:-4], ".wav") if component.endswith(".wav") else (component, "")
            )
            if _ID.fullmatch(stem):
                components[index] = self.identifier(stem) + suffix
        return "<home>/" + "/".join(components)

    def scalar(self, item: Any, key: str) -> Any:
        if key in {"id", "current", "ids"} and isinstance(item, str) and _ID.fullmatch(item):
            return self.identifier(item)
        if key in _TIMES and type(item) in {float, int} and item >= 0:
            return "<time>"
        if key == "pid" and type(item) is int and item > 0:
            return "<pid>"
        if key == "audio_path" and isinstance(item, str) and item.startswith(f"{self.home}/"):
            return self.audio_path(item)
        return item

    def visit(self, item: Any, key: str = "") -> Any:
        if isinstance(item, dict):
            return {name: self.visit(child, name) for name, child in item.items()}
        if isinstance(item, list):
            return [self.visit(child, key) for child in item]
        return self.scalar(item, key)


def normalize(value: Any, home: Path) -> Any:
    """Replace declared volatile values; retain every key, type error and semantic field."""
    return _Mask(home).visit(value)


def assert_transcript(actual: Any, expected: Any, home: Path) -> None:
    """Compare canonical JSON so boolean/number changes cannot pass Python equality."""
    observed = json.dumps(normalize(actual, home), sort_keys=True, indent=2, allow_nan=False)
    baseline = json.dumps(expected, sort_keys=True, indent=2, allow_nan=False)
    assert observed == baseline


async def read_object(reader: asyncio.StreamReader) -> dict[str, Any]:
    line = await reader.readline()
    value = json.loads(line)
    if not isinstance(value, dict):
        message = "daemon reply must be a JSON object"
        raise TypeError(message)
    return value


class Transcript:
    """Retain all requests, replies and subscription events in scenario order."""

    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path
        self.entries: list[dict[str, Any]] = []

    async def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        reader, writer = await asyncio.open_unix_connection(str(self.socket_path))
        try:
            writer.write(json.dumps(payload).encode() + b"\n")
            await writer.drain()
            reply = await read_object(reader)
            self.entries.append({"request": payload, "reply": reply})
            return reply
        finally:
            writer.close()
            await writer.wait_closed()

    async def subscribed(self, scenario: str) -> None:
        reader, writer = await asyncio.open_unix_connection(str(self.socket_path))
        try:
            request = {"op": "subscribe"}
            writer.write(json.dumps(request).encode() + b"\n")
            await writer.drain()
            self.entries.append({"request": request, "reply": await read_object(reader)})
            if scenario == "subscribe":
                await self.request({"op": "settings", "set": {"captions_enabled": True}})
                self.entries.append({"event": await read_object(reader)})
                return
            if scenario == "list":
                await self.request({"op": "pause"})
            submitted = await self.request({"op": "submit", "text": "Contract text."})
            terminal = "Ready" if scenario == "list" else "Played"
            while True:
                event = await read_object(reader)
                self.entries.append({"event": event})
                if event.get("id") == submitted["id"] and event.get("to") == terminal:
                    break
            if scenario == "list":
                await self.request({"op": "list", "queue": "input"})
                await self.request({"op": "list", "queue": "playback"})
            else:
                await self.request({"op": "history"})
        finally:
            writer.close()
            await writer.wait_closed()


async def record_scenario(socket_path: Path, scenario: str) -> list[dict[str, Any]]:
    transcript = Transcript(socket_path)
    async with asyncio.timeout(3):
        if scenario in {"subscribe", "list", "history"}:
            await transcript.subscribed(scenario)
        elif scenario == "submit":
            await transcript.request({"op": "pause"})
            await transcript.request({"op": "submit", "text": "Contract text."})
            await transcript.request({"op": "submit", "text": "Client audio.", "playback": False})
        elif scenario == "resume":
            await transcript.request({"op": "pause"})
            await transcript.request({"op": "resume"})
        elif scenario == "settings":
            await transcript.request({"op": "settings"})
            await transcript.request({"op": "settings", "set": {"captions_enabled": True}})
            await transcript.request({"op": "settings"})
        elif scenario in {"status", "pause", "skip"}:
            await transcript.request({"op": scenario})
        else:
            message = f"unknown transcript scenario: {scenario}"
            raise ValueError(message)
    return transcript.entries
