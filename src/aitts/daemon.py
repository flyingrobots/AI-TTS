# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The daemon: long-lived, model resident, and the owner of every queue.

Wires the store, the synthesis pool, the playback controller and the IPC
server together, and implements the operation set of architecture.md §5.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aitts.adapters.filesystem_cache import FileAudioCache
from aitts.application.cache import DEFAULT_CACHE_MAX_BYTES, CacheController
from aitts.engine import eligible_engine_names
from aitts.ipc import (
    BAD_REQUEST,
    ILLEGAL_STATE,
    INTERNAL,
    NOT_FOUND,
    ApiError,
    IPCServer,
)
from aitts.model import TERMINAL, Priority, Sensitivity, State, Utterance
from aitts.playback import PlaybackController
from aitts.store import Store, TransitionError
from aitts.synthesis import SynthesisPool

if TYPE_CHECKING:
    from aitts.engine import Engine
    from aitts.playback import AudioSink

_SPEED_MIN = 0.5
_SPEED_MAX = 2.0
_CANCELLABLE = (State.QUEUED, State.SYNTHESIZING, State.READY)
_PLAYBACK_RESTART_MIN_SECONDS = 0.05
_PLAYBACK_RESTART_MAX_SECONDS = 5.0

log = logging.getLogger(__name__)


def _serialize(utt: Utterance, *, history: bool = False) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": utt.id,
        "text": utt.text,
        "voice": utt.voice,
        "speed": utt.speed,
        "sensitivity": utt.sensitivity.value,
        "priority": utt.priority.value,
        "state": utt.state.value,
        "enqueued_at": utt.submitted_at,
        "source": utt.source,
        "duration_ms": utt.duration_ms,
        "played_ms": utt.played_ms,
        "error": utt.error,
        "replay_of": utt.replay_of,
    }
    if history:
        item["final_state"] = utt.state.value
        item["finished_at"] = utt.state_changed_at
        item["audio_cached"] = bool(utt.audio_path is not None and Path(utt.audio_path).exists())
    return item


class Daemon:
    """One process that outlives its clients and owns the audio device."""

    def __init__(
        self,
        *,
        home: Path,
        engine: Engine,
        sink: AudioSink,
        workers: int = 2,
        socket_path: Path | None = None,
    ) -> None:
        """Prepare a daemon rooted at ``home`` speaking through ``engine``."""
        home.mkdir(parents=True, exist_ok=True)
        self._home = home
        self._engines: dict[str, Engine] = {"local": engine}
        self._engine = engine
        self._sink = sink
        self._workers = workers
        self._store = Store(home / "state.db")
        self._cache_dir = home / "cache"
        self._cache = CacheController(self._store, FileAudioCache(self._cache_dir))
        self._server = IPCServer(socket_path or home / "ai-tts.sock", self)
        self._controller: PlaybackController | None = None
        self._pool: SynthesisPool | None = None
        self._tasks: list[asyncio.Task[None]] = []

    @property
    def socket_path(self) -> Path:
        """Where clients connect."""
        return self._server.socket_path

    @property
    def store(self) -> Store:
        """The daemon's store (exposed for tests and tooling)."""
        return self._store

    async def start(self) -> None:
        """Recover state, start the workers, and begin serving."""
        self._store.recover()
        self._enforce_cache_limit()
        held = any(u.state is State.PAUSED for u in self._store.playback_queue())
        self._controller = PlaybackController(self._store, self._sink, held=held)
        self._pool = SynthesisPool(
            self._store, self._engine, self._cache_dir, workers=self._workers
        )
        self._store.on_transition.append(self._on_transition)
        loop = asyncio.get_running_loop()
        self._tasks = [
            loop.create_task(self._pool.run(), name="aitts-synthesis"),
            loop.create_task(self._supervise_playback(), name="aitts-playback"),
            loop.create_task(asyncio.to_thread(self._engine.warmup), name="aitts-warmup"),
        ]
        await self._server.start()

    async def _supervise_playback(self) -> None:
        """Restart the critical playback loop if it exits unexpectedly."""
        delay = _PLAYBACK_RESTART_MIN_SECONDS
        while True:
            try:
                await self._require_controller().run()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("playback worker failed; restarting in %.2fs", delay)
            else:  # pragma: no cover - run() is intentionally perpetual
                log.error("playback worker exited; restarting in %.2fs", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, _PLAYBACK_RESTART_MAX_SECONDS)

    async def stop(self) -> None:
        """Stop serving, cancel the workers, and close the store."""
        await self._server.stop()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks = []
        self._store.close()

    # -- events ------------------------------------------------------------

    def _on_transition(self, utt: Utterance, from_state: State) -> None:
        self._server.broadcast(
            {
                "event": "state_changed",
                "id": utt.id,
                "from": from_state.value,
                "to": utt.state.value,
                "at": utt.state_changed_at,
            }
        )
        if self._controller is not None and utt.state is State.READY:
            self._controller.notify()
        if self._pool is not None and utt.state is State.QUEUED:
            self._pool.notify()
        if utt.state is State.PLAYING and utt.audio_path is not None:
            self._cache.note_access(Path(utt.audio_path))
        if utt.state in TERMINAL:
            self._enforce_cache_limit()

    def _cache_limit(self) -> int:
        raw = self._store.get_setting("cache_max_bytes", str(DEFAULT_CACHE_MAX_BYTES))
        try:
            parsed = int(raw)
        except ValueError:
            return DEFAULT_CACHE_MAX_BYTES
        return parsed if parsed >= 0 else DEFAULT_CACHE_MAX_BYTES

    def _enforce_cache_limit(self) -> None:
        try:
            report = self._cache.enforce(max_bytes=self._cache_limit())
        except OSError:
            log.warning("could not inspect audio cache", exc_info=True)
            return
        if not report.within_limit:
            log.warning(
                "audio cache remains above its limit: %d > %d bytes",
                report.after_bytes,
                report.max_bytes,
            )

    # -- dispatch ------------------------------------------------------------

    async def dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Route one request to its handler."""
        op = payload.get("op")
        handlers = {
            "submit": self._op_submit,
            "get": self._op_get,
            "list": self._op_list,
            "history": self._op_history,
            "pause": self._op_pause,
            "resume": self._op_resume,
            "skip": self._op_skip,
            "rewind": self._op_rewind,
            "requeue": self._op_requeue,
            "reorder": self._op_reorder,
            "cancel": self._op_cancel,
            "remove_history": self._op_remove_history,
            "clear": self._op_clear,
            "status": self._op_status,
            "snapshot": self._op_snapshot,
            "voices": self._op_voices,
            "settings": self._op_settings,
        }
        handler = handlers.get(op) if isinstance(op, str) else None
        if handler is None:
            msg = f"unknown op {op!r}"
            raise ApiError(BAD_REQUEST, msg)
        return await handler(payload)

    def _require_controller(self) -> PlaybackController:
        if self._controller is None:  # pragma: no cover - start() precedes serving
            msg = "daemon is not started"
            raise ApiError(INTERNAL, msg)
        return self._controller

    # -- ops ------------------------------------------------------------

    def _speech_admission(self) -> dict[str, object]:
        """Tell machine callers that a playback hold is not backpressure."""
        held = self._require_controller().held
        return {
            "accepting_speech": True,
            "playback_held": held,
            "submission_disposition": ("spooled_until_resume" if held else "queued_for_playback"),
            "submission_guidance": (
                "Speak freely: playback is paused, but speech is accepted and spooled until Resume."
                if held
                else "Speak freely: speech is accepted into the playback queue."
            ),
        }

    async def _op_submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            msg = "submit requires non-empty 'text'"
            raise ApiError(BAD_REQUEST, msg)
        try:
            sensitivity = Sensitivity(payload.get("sensitivity", "confidential"))
            priority = Priority(payload.get("priority", "normal"))
        except ValueError as exc:
            raise ApiError(BAD_REQUEST, str(exc)) from exc
        voice = payload.get("voice") or self._store.get_setting("voice", self._default_voice())
        if voice not in self._engine.list_voices():
            msg = f"unknown voice {voice!r}"
            raise ApiError(BAD_REQUEST, msg)
        speed = self._parse_speed(payload.get("speed")) or float(
            self._store.get_setting("speed", "1.0")
        )
        source = payload.get("source")
        utt = self._store.submit(
            text,
            voice=str(voice),
            speed=speed,
            sensitivity=sensitivity,
            priority=priority,
            source=source if isinstance(source, str) else None,
            at_head=priority is Priority.URGENT,
        )
        if self._pool is not None:
            self._pool.notify()
        return {
            "ok": True,
            "accepted": True,
            "id": utt.id,
            "state": utt.state.value,
            "sensitivity": utt.sensitivity.value,
            "eligible_engines": eligible_engine_names(self._engines, utt.sensitivity),
            **self._speech_admission(),
        }

    @staticmethod
    def _parse_speed(raw: object) -> float | None:
        if raw is None:
            return None
        if not isinstance(raw, (int, float)) or not _SPEED_MIN <= float(raw) <= _SPEED_MAX:
            msg = f"speed must be a number between {_SPEED_MIN} and {_SPEED_MAX}"
            raise ApiError(BAD_REQUEST, msg)
        return float(raw)

    def _default_voice(self) -> str:
        voices = self._engine.list_voices()
        return voices[0] if voices else ""

    async def _op_get(self, payload: dict[str, Any]) -> dict[str, Any]:
        utt = self._get_utterance(payload)
        return {"ok": True, "item": _serialize(utt, history=utt.is_terminal)}

    def _get_utterance(self, payload: dict[str, Any]) -> Utterance:
        utt_id = payload.get("id")
        if not isinstance(utt_id, str):
            msg = "an utterance 'id' is required"
            raise ApiError(BAD_REQUEST, msg)
        utt = self._store.get(utt_id)
        if utt is None:
            msg = f"no utterance {utt_id!r}"
            raise ApiError(NOT_FOUND, msg)
        return utt

    async def _op_list(self, payload: dict[str, Any]) -> dict[str, Any]:
        queue = payload.get("queue")
        if queue == "input":
            items = self._store.input_queue()
        elif queue == "playback":
            items = self._store.playback_queue()
        else:
            msg = "list requires 'queue': 'input' or 'playback'"
            raise ApiError(BAD_REQUEST, msg)
        return {"ok": True, "items": [_serialize(u) for u in items]}

    async def _op_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        limit = payload.get("limit", 100)
        if not isinstance(limit, int) or limit < 1:
            msg = "'limit' must be a positive integer"
            raise ApiError(BAD_REQUEST, msg)
        before = payload.get("before")
        items = self._store.history(limit=limit, before=before if isinstance(before, str) else None)
        return {"ok": True, "items": [_serialize(u, history=True) for u in items]}

    async def _op_pause(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        await self._require_controller().pause()
        return self._transport_reply()

    async def _op_resume(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        await self._require_controller().resume()
        return self._transport_reply()

    async def _op_skip(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        await self._require_controller().skip()
        return self._transport_reply()

    async def _op_rewind(self, payload: dict[str, Any]) -> dict[str, Any]:
        controller = self._require_controller()
        target_id = payload.get("to")
        if target_id is None:
            await controller.restart_current()
            return self._transport_reply()
        target = self._get_utterance({"id": target_id})
        if target.state in (State.QUEUED, State.SYNTHESIZING, State.READY):
            self._store.move_to_head(target.id)
            controller.notify()
            return self._transport_reply()
        if target.is_terminal:
            replay = self._replay(target, priority=target.priority, at_head=True)
            reply = self._transport_reply()
            reply["replay_id"] = replay.id
            return reply
        msg = "rewind target is currently playing; use 'rewind' without 'to' to restart it"
        raise ApiError(ILLEGAL_STATE, msg)

    def _replay(self, target: Utterance, *, priority: Priority, at_head: bool) -> Utterance:
        """Create a new hearing of a finished utterance.

        Replaying is a new utterance so history stays honest about each
        hearing. Cached audio is reused when it still exists; otherwise the
        text is re-synthesized.
        """
        replay = self._store.submit(
            target.text,
            voice=target.voice,
            speed=target.speed,
            sensitivity=target.sensitivity,
            priority=priority,
            source=target.source,
            replay_of=target.id,
            at_head=at_head,
        )
        cached_path = Path(target.audio_path) if target.audio_path is not None else None
        cached = cached_path is not None and self._cache.note_access(cached_path)
        if cached:
            self._store.transition(replay.id, State.SYNTHESIZING)
            self._store.transition(
                replay.id,
                State.READY,
                audio_path=str(cached_path),
                duration_ms=target.duration_ms,
            )
        elif self._pool is not None:
            self._pool.notify()
        return self._store.get(replay.id) or replay

    async def _op_requeue(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            priority = Priority(payload.get("priority", Priority.NORMAL.value))
        except ValueError as exc:
            raise ApiError(BAD_REQUEST, str(exc)) from exc
        target = self._get_utterance(payload)
        if not target.is_terminal:
            msg = "only a history item can be re-queued"
            raise ApiError(ILLEGAL_STATE, msg)
        replay = self._replay(
            target,
            priority=priority,
            at_head=priority is Priority.URGENT,
        )
        return {
            "ok": True,
            "id": replay.id,
            "state": replay.state.value,
            "priority": replay.priority.value,
        }

    async def _op_reorder(self, payload: dict[str, Any]) -> dict[str, Any]:
        utt_ids = payload.get("ids")
        if not isinstance(utt_ids, list) or not all(isinstance(item, str) for item in utt_ids):
            msg = "reorder requires an 'ids' array"
            raise ApiError(BAD_REQUEST, msg)
        try:
            self._store.reorder_pending(utt_ids)
        except ValueError as exc:
            raise ApiError(BAD_REQUEST, str(exc)) from exc
        self._server.broadcast({"event": "plan_reordered", "ids": utt_ids})
        self._require_controller().notify()
        return {"ok": True, "ids": utt_ids}

    async def _op_cancel(self, payload: dict[str, Any]) -> dict[str, Any]:
        utt = self._get_utterance(payload)
        if utt.state in (State.PLAYING, State.PAUSED):
            msg = "cancel is not legal for a playing utterance; that is 'skip'"
            raise ApiError(ILLEGAL_STATE, msg)
        if utt.state not in _CANCELLABLE:
            msg = f"cannot cancel an utterance in state {utt.state.value}"
            raise ApiError(ILLEGAL_STATE, msg)
        try:
            after = self._store.transition(utt.id, State.CANCELLED)
        except TransitionError as exc:  # pragma: no cover - guarded above
            raise ApiError(ILLEGAL_STATE, str(exc)) from exc
        return {"ok": True, "id": after.id, "state": after.state.value}

    async def _op_clear(self, payload: dict[str, Any]) -> dict[str, Any]:
        queue = payload.get("queue")
        if queue == "queue":
            cleared = self._store.clear_pending()
            return {"ok": True, "cleared": cleared}
        if queue == "history":
            cleared = self._store.clear_history()
            self._server.broadcast({"event": "history_changed", "cleared": cleared})
            return {"ok": True, "cleared": cleared}
        if queue not in ("input", "playback"):
            msg = "clear requires 'queue': 'queue', 'history', 'input', or 'playback'"
            raise ApiError(BAD_REQUEST, msg)
        cleared = self._store.clear_queue(queue)
        return {"ok": True, "cleared": cleared}

    async def _op_remove_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        target = self._get_utterance(payload)
        if not target.is_terminal:
            msg = "only a history item can be removed"
            raise ApiError(ILLEGAL_STATE, msg)
        removed = int(self._store.remove_history(target.id))
        self._server.broadcast({"event": "history_changed", "removed": target.id})
        return {"ok": True, "removed": removed, "id": target.id}

    async def _op_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        controller = self._require_controller()
        current = (
            self._store.get(controller.current_id) if controller.current_id is not None else None
        )
        counts = self._store.counts()
        if current is not None and current.state is State.PLAYING:
            playback_state = "playing"
        elif controller.held or (current is not None and current.state is State.PAUSED):
            playback_state = "paused"
        elif counts.get(State.SYNTHESIZING.value, 0) > 0:
            playback_state = "synthesizing"
        else:
            playback_state = "idle"
        current_item: dict[str, Any] | None = None
        if current is not None:
            current_item = _serialize(current)
            current_item["position_ms"] = controller.current_position_ms()
        return {
            "ok": True,
            "state": "accepting",
            **self._speech_admission(),
            "playback_state": playback_state,
            "current": current_item,
            "counts": counts,
            "engine": self._engine.name,
            "voice": self._store.get_setting("voice", self._default_voice()),
        }

    async def _op_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Everything the popover needs, in one request."""
        status = await self._op_status({})
        status.pop("ok", None)
        history = await self._op_history({"limit": payload.get("limit", 50), "op": "history"})
        settings = await self._op_settings({"op": "settings"})
        playback = self._store.playback_queue()
        pending = self._store.input_queue()
        plan = sorted(playback + pending, key=lambda u: u.order_key)
        return {
            "ok": True,
            "status": status,
            "playback": [_serialize(u) for u in playback],
            "input": [_serialize(u) for u in pending],
            "plan": [_serialize(u) for u in plan],
            "history": history["items"],
            "voices": self._engine.list_voices(),
            "settings": settings["settings"],
        }

    async def _op_voices(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        return {"ok": True, "voices": self._engine.list_voices()}

    async def _op_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        updates = payload.get("set")
        if updates is not None:
            if not isinstance(updates, dict):
                msg = "'set' must be an object of settings"
                raise ApiError(BAD_REQUEST, msg)
            self._apply_settings(updates)
        return {
            "ok": True,
            "settings": {
                "voice": self._store.get_setting("voice", self._default_voice()),
                "speed": float(self._store.get_setting("speed", "1.0")),
                "cache_max_bytes": self._cache_limit(),
            },
        }

    def _apply_settings(self, updates: dict[str, Any]) -> None:
        for key, value in updates.items():
            if key == "voice":
                if value not in self._engine.list_voices():
                    msg = f"unknown voice {value!r}"
                    raise ApiError(BAD_REQUEST, msg)
                self._store.set_setting("voice", str(value))
            elif key == "speed":
                speed = self._parse_speed(value)
                if speed is None:
                    msg = "'speed' must be a number"
                    raise ApiError(BAD_REQUEST, msg)
                self._store.set_setting("speed", str(speed))
            elif key == "cache_max_bytes":
                limit = self._parse_cache_limit(value)
                if limit is None:
                    msg = "'cache_max_bytes' must be a non-negative integer"
                    raise ApiError(BAD_REQUEST, msg)
                self._store.set_setting("cache_max_bytes", str(limit))
                self._enforce_cache_limit()
            else:
                msg = f"unknown setting {key!r}"
                raise ApiError(BAD_REQUEST, msg)

    @staticmethod
    def _parse_cache_limit(raw: object) -> int | None:
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            return None
        try:
            limit = int(raw)
        except ValueError:
            return None
        if isinstance(raw, str) and raw.strip() != str(limit):
            return None
        return limit if limit >= 0 else None

    def _transport_reply(self) -> dict[str, Any]:
        controller = self._require_controller()
        current = (
            self._store.get(controller.current_id) if controller.current_id is not None else None
        )
        return {
            "ok": True,
            "state": current.state.value if current is not None else None,
            "current": current.id if current is not None else None,
            "held": controller.held,
        }
