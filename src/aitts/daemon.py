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

from aitts.adapters.audio_artifacts import FileAudioArtifacts
from aitts.adapters.diagnostic_logging import utterance_trace
from aitts.adapters.filesystem_cache import FileAudioCache
from aitts.adapters.playback_schedule import ImmediatePlaybackSchedule
from aitts.adapters.private_files import secure_private_state
from aitts.application.cache import DEFAULT_CACHE_MAX_BYTES, CacheController
from aitts.application.input_activity import (
    InputInterruptDetector,
    platform_input_activity,
)
from aitts.application.metrics import MetricsRecorder
from aitts.application.voice_assignment import decide_speaking_voice
from aitts.engine import eligible_engine_names, engine_preparation
from aitts.ipc import (
    BAD_REQUEST,
    ILLEGAL_STATE,
    INTERNAL,
    NOT_FOUND,
    ApiError,
    IPCServer,
)
from aitts.model import (
    TERMINAL,
    ContentFormat,
    Priority,
    Sensitivity,
    State,
    SynthesisWork,
    Utterance,
    UtteranceSegment,
    VoiceAssignment,
)
from aitts.playback import PLAYBACK_RATES, PlaybackController
from aitts.segmentation import prepare_speech_segments
from aitts.store import Store, TransitionError
from aitts.synthesis import SynthesisPool

if TYPE_CHECKING:
    from collections.abc import Callable

    from aitts.application.input_activity import InputActivityPort
    from aitts.engine import Engine
    from aitts.playback import AudioSink

_SPEED_MIN = 0.5
_SPEED_MAX = 2.0
_CANCELLABLE = (State.QUEUED, State.SYNTHESIZING, State.READY)
# The listener's voice should take the floor within a syllable or two, and
# each poll costs well under a millisecond.
_INPUT_POLL_SECONDS = 0.15
# The lifecycle points worth correlating: an utterance becoming playable,
# taking the device, finishing, and failing. Enough to follow one clip through
# a log without narrating every intermediate step.
_TRACED_STATES = (State.READY, State.PLAYING, State.PLAYED, State.FAILED)
_INPUT_INTERRUPT_RESUME_POLICIES = ("manual", "when_idle")
_PLAYBACK_RESTART_MIN_SECONDS = 0.05
_PLAYBACK_RESTART_MAX_SECONDS = 5.0

log = logging.getLogger(__name__)


def _serialize_assignment(assignment: VoiceAssignment) -> dict[str, Any]:
    return {
        "source": assignment.source,
        "voice": assignment.voice,
        "pinned": assignment.pinned,
        "assigned_at": assignment.assigned_at,
    }


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

    def __init__(  # noqa: PLR0913 - every collaborator is injected by name
        self,
        *,
        home: Path,
        engine: Engine,
        sink: AudioSink,
        workers: int = 2,
        socket_path: Path | None = None,
        input_activity: InputActivityPort | None = None,
        input_poll_seconds: float = _INPUT_POLL_SECONDS,
    ) -> None:
        """Prepare a daemon rooted at ``home`` speaking through ``engine``."""
        secure_private_state(home)
        self._home = home
        self._input_activity = (
            input_activity if input_activity is not None else platform_input_activity()
        )
        self._input_poll_seconds = input_poll_seconds
        self._input_detector = InputInterruptDetector()
        self._metrics = MetricsRecorder()
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
        self._controller = PlaybackController(
            self._store,
            self._sink,
            ImmediatePlaybackSchedule(),
            held=held,
        )
        self._pool = SynthesisPool(
            self._store,
            self._engine,
            FileAudioArtifacts(self._cache_dir),
            workers=self._workers,
        )
        self._store.on_transition.append(self._on_transition)
        self._store.on_segment_transition.append(self._on_segment_transition)
        loop = asyncio.get_running_loop()
        self._tasks = [
            loop.create_task(self._pool.run(), name="aitts-synthesis"),
            loop.create_task(self._supervise_playback(), name="aitts-playback"),
            loop.create_task(asyncio.to_thread(self._engine.warmup), name="aitts-warmup"),
            loop.create_task(self._watch_input_activity(), name="aitts-input"),
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
            except Exception:  # noqa: BLE001 - supervisor must restart any worker failure
                log.warning("event=playback_worker_failed retry_seconds=%.2f", delay)
            else:  # pragma: no cover - run() is intentionally perpetual
                log.error("event=playback_worker_exited retry_seconds=%.2f", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, _PLAYBACK_RESTART_MAX_SECONDS)

    async def _watch_input_activity(self) -> None:
        """Give the listener the floor the moment they start speaking.

        The reading is coarse and sticky, so only its cold-to-hot edge counts
        as the floor changing hands (see
        :mod:`aitts.application.input_activity`). A hold that came from an
        interrupt can also release itself once the input goes quiet, when the
        listener has asked for that.
        """
        while True:
            try:
                reading = self._input_activity.input_is_active()
                if self._input_detector.observe(reading) and self._input_interrupt_enabled():
                    await self._interrupt_for_listener()
                elif reading is False:
                    # Deliberately not gated on the setting. An armed resume
                    # can only exist because the listener asked for one while
                    # the feature was on, and it is their request rather than
                    # the feature acting; dropping it on a later toggle would
                    # leave playback held with nothing to explain it.
                    await self._resume_if_armed()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a poll failure must not stop the daemon
                log.warning("event=input_activity_poll_failed")
            await asyncio.sleep(self._input_poll_seconds)

    async def _interrupt_for_listener(self) -> None:
        controller = self._require_controller()
        if not await controller.interrupt():
            return
        if self._input_interrupt_resume() == "when_idle":
            controller.arm_resume_when_input_idle()
        log.info("event=playback_interrupted_by_listener")
        self._server.broadcast(
            {
                "event": "playback_interrupted",
                "reason": "listener_speaking",
                "resume_armed": controller.resume_when_input_idle_armed,
            }
        )

    async def _resume_if_armed(self) -> None:
        controller = self._require_controller()
        if controller.resume_when_input_idle_armed:
            await controller.resume()
            log.info("event=playback_resumed_after_listener")
            self._server.broadcast({"event": "playback_resumed", "reason": "input_idle"})

    def _input_interrupt_enabled(self) -> bool:
        return self._store.get_setting("input_interrupt_enabled", "true") == "true"

    def _input_interrupt_resume(self) -> str:
        return self._store.get_setting("input_interrupt_resume", "manual")

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
        self._metrics.observe(utt)
        if utt.state in _TRACED_STATES:
            log.info("event=utterance_state trace=%s", utterance_trace(utt.id))
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

    def _on_segment_transition(self, segment: UtteranceSegment, from_state: State) -> None:
        self._server.broadcast(
            {
                "event": "segment_state_changed",
                "id": segment.utterance_id,
                "segment_index": segment.index,
                "from": from_state.value,
                "to": segment.state.value,
            }
        )
        if self._controller is not None and segment.state in (State.READY, State.PLAYING):
            self._controller.notify()
        if self._pool is not None and segment.state is State.QUEUED:
            self._pool.notify()
        if segment.state is State.PLAYING and segment.audio_path is not None:
            self._cache.note_access(Path(segment.audio_path))
        if segment.state in TERMINAL:
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
            log.warning("event=cache_inspection_failed")
            return
        if not report.within_limit:
            log.warning(
                "event=cache_limit_unmet after_bytes=%d max_bytes=%d",
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
            "resume_when_input_idle": self._op_resume_when_input_idle,
            "skip": self._op_skip,
            "rewind": self._op_rewind,
            "next_segment": self._op_next_segment,
            "previous_segment": self._op_previous_segment,
            "requeue": self._op_requeue,
            "reorder": self._op_reorder,
            "cancel": self._op_cancel,
            "remove_history": self._op_remove_history,
            "clear": self._op_clear,
            "purge_cache": self._op_purge_cache,
            "status": self._op_status,
            "metrics": self._op_metrics,
            "snapshot": self._op_snapshot,
            "voices": self._op_voices,
            "voice_assignments": self._op_voice_assignments,
            "assign_voice": self._op_assign_voice,
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

    def _serialize_utterance(
        self,
        utt: Utterance,
        *,
        history: bool = False,
    ) -> dict[str, Any]:
        item = _serialize(utt, history=history)
        segments = self._store.segments(utt.id)
        item["composite"] = bool(segments)
        item["segment_count"] = len(segments) if segments else 1
        item["completed_segments"] = sum(
            segment.state in (State.PLAYED, State.SKIPPED) for segment in segments
        )
        if history and segments:
            item["audio_cached"] = all(
                segment.audio_path is not None and Path(segment.audio_path).exists()
                for segment in segments
            )
        return item

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
        source = payload.get("source")
        voice = self._resolve_voice(
            source=source if isinstance(source, str) else None,
            requested=payload.get("voice") or None,
        )
        if voice not in self._engine.list_voices():
            msg = f"unknown voice {voice!r}"
            raise ApiError(BAD_REQUEST, msg)
        speed = self._parse_speed(payload.get("speed")) or float(
            self._store.get_setting("speed", "1.0")
        )
        content_format: ContentFormat | None
        if "content_format" not in payload:
            content_format = None
        else:
            try:
                content_format = ContentFormat(payload["content_format"])
            except ValueError as exc:
                msg = "content_format must be 'plain_text' or 'markdown'"
                raise ApiError(BAD_REQUEST, msg) from exc
        spoken_segments = prepare_speech_segments(text, content_format=content_format)
        if not spoken_segments:
            msg = "submit text contains no speakable content"
            raise ApiError(BAD_REQUEST, msg)
        composite = spoken_segments != (text,)
        utt = self._store.submit(
            text,
            voice=str(voice),
            speed=speed,
            sensitivity=sensitivity,
            priority=priority,
            source=source if isinstance(source, str) else None,
            at_head=priority is Priority.URGENT,
            spoken_segments=spoken_segments if composite else None,
        )
        if self._pool is not None:
            self._pool.notify()
        return {
            "ok": True,
            "accepted": True,
            "id": utt.id,
            "state": utt.state.value,
            # The register can overrule the requested voice, so the receipt
            # says which voice will actually speak.
            "voice": utt.voice,
            "sensitivity": utt.sensitivity.value,
            "segment_count": len(spoken_segments),
            "composite": composite,
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

    def _resolve_voice(self, *, source: str | None, requested: str | None) -> str:
        """Pick the voice this submission speaks in, and register a new claim.

        The listener's assignment outranks the caller's request; otherwise a
        client keeps whatever voice it already holds, and a client the daemon
        has not heard from claims one nobody else has.
        """
        catalog = self._engine.list_voices()
        # Validate the request before the register can record it. Claiming
        # first and validating afterwards let a misspelled voice be written as
        # a durable claim, and a held voice outranks later requests, so that
        # source could never speak again.
        if requested is not None and requested not in catalog:
            msg = f"unknown voice {requested!r}"
            raise ApiError(BAD_REQUEST, msg)
        assignment = self._store.voice_assignment(source) if source is not None else None
        assignment = self._reconcile_assignment(assignment, catalog)
        decision = decide_speaking_voice(
            source=source,
            requested=requested,
            default_voice=self._store.get_setting("voice", self._default_voice()),
            catalog=catalog,
            pinned=assignment.voice if assignment is not None and assignment.pinned else None,
            claimed=assignment.voice if assignment is not None else None,
            taken=self._store.claimed_voices(),
        )
        if decision.claim and source is not None:
            claimed = self._store.claim_voice(source, decision.voice)
            log.info("event=voice_claimed")
            self._server.broadcast(
                {"event": "voice_assigned", "assignment": _serialize_assignment(claimed)}
            )
            return claimed.voice
        return decision.voice

    def _reconcile_assignment(
        self, assignment: VoiceAssignment | None, catalog: list[str]
    ) -> VoiceAssignment | None:
        """Drop a held voice this engine no longer offers.

        A catalog can shrink between runs — a voice withdrawn upstream, or a
        different engine configured. An automatic claim is released so the
        client claims something speakable; a pin is the listener's own choice,
        so it is reported for repair rather than silently substituted.
        """
        if assignment is None or assignment.voice in catalog:
            return assignment
        if assignment.pinned:
            msg = (
                f"voice {assignment.voice!r} assigned to {assignment.source!r} is not "
                f"offered by the {self._engine.name} engine; reassign it with assign_voice"
            )
            raise ApiError(ILLEGAL_STATE, msg)
        self._store.release_voice(assignment.source)
        log.info("event=voice_claim_released_unavailable")
        self._server.broadcast({"event": "voice_released", "source": assignment.source})
        return None

    async def _op_voice_assignments(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        return {
            "ok": True,
            "assignments": [
                _serialize_assignment(item) for item in self._store.voice_assignments()
            ],
        }

    async def _op_assign_voice(self, payload: dict[str, Any]) -> dict[str, Any]:
        source = payload.get("source")
        if not isinstance(source, str) or not source.strip():
            msg = "assign_voice requires a non-empty 'source'"
            raise ApiError(BAD_REQUEST, msg)
        voice = payload.get("voice")
        release = payload.get("release", False)
        if type(release) is not bool:
            msg = "'release' must be a boolean"
            raise ApiError(BAD_REQUEST, msg)
        # Releasing is stated, never implied. Reading an omitted voice as
        # "forget this one" meant a caller that left the field out destroyed
        # an assignment while believing it was reading one.
        if release and voice is not None:
            msg = "assign_voice takes either 'voice' or 'release', not both"
            raise ApiError(BAD_REQUEST, msg)
        if release:
            if not self._store.release_voice(source):
                msg = f"no voice is assigned to {source!r}"
                raise ApiError(NOT_FOUND, msg)
            self._server.broadcast({"event": "voice_released", "source": source})
            return {"ok": True, "assignment": None}
        if voice is None:
            msg = "assign_voice requires a 'voice', or 'release': true to forget one"
            raise ApiError(BAD_REQUEST, msg)
        if voice not in self._engine.list_voices():
            msg = f"unknown voice {voice!r}"
            raise ApiError(BAD_REQUEST, msg)
        assignment = self._store.pin_voice(source, str(voice))
        self._server.broadcast(
            {"event": "voice_assigned", "assignment": _serialize_assignment(assignment)}
        )
        return {"ok": True, "assignment": _serialize_assignment(assignment)}

    async def _op_get(self, payload: dict[str, Any]) -> dict[str, Any]:
        utt = self._get_utterance(payload)
        return {"ok": True, "item": self._serialize_utterance(utt, history=utt.is_terminal)}

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
        return {"ok": True, "items": [self._serialize_utterance(u) for u in items]}

    async def _op_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        limit = payload.get("limit", 100)
        if not isinstance(limit, int) or limit < 1:
            msg = "'limit' must be a positive integer"
            raise ApiError(BAD_REQUEST, msg)
        before = payload.get("before")
        items = self._store.history(limit=limit, before=before if isinstance(before, str) else None)
        return {
            "ok": True,
            "items": [self._serialize_utterance(u, history=True) for u in items],
        }

    async def _op_pause(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        await self._require_controller().pause()
        return self._transport_reply()

    async def _op_resume(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        await self._require_controller().resume()
        return self._transport_reply()

    async def _op_resume_when_input_idle(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        controller = self._require_controller()
        if not controller.held:
            msg = "playback is not held; there is nothing to resume"
            raise ApiError(ILLEGAL_STATE, msg)
        controller.arm_resume_when_input_idle()
        return self._transport_reply()

    async def _op_skip(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        await self._require_controller().skip()
        return self._transport_reply()

    async def _op_next_segment(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        return await self._step_segment(forwards=True)

    async def _op_previous_segment(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        return await self._step_segment(forwards=False)

    async def _step_segment(self, *, forwards: bool) -> dict[str, Any]:
        """Move one chunk within the current document, or say why it cannot."""
        controller = self._require_controller()
        moved = await controller.next_segment() if forwards else await controller.previous_segment()
        if not moved:
            msg = (
                "no further chunk in the current document; chunk steps need an unheld, chunked clip"
            )
            raise ApiError(ILLEGAL_STATE, msg)
        reply = self._transport_reply()
        segment = controller.current_segment
        if segment is not None:
            reply["segment_index"] = segment.index
            reply["segment_number"] = segment.index + 1
        return reply

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
        source_segments = self._store.segments(target.id)
        replay = self._store.submit(
            target.text,
            voice=target.voice,
            speed=target.speed,
            sensitivity=target.sensitivity,
            priority=priority,
            source=target.source,
            replay_of=target.id,
            at_head=at_head,
            spoken_segments=tuple(segment.text for segment in source_segments) or None,
        )
        if source_segments:
            cached_segments: list[tuple[UtteranceSegment, Path]] = []
            for segment in source_segments:
                if segment.audio_path is None:
                    break
                path = Path(segment.audio_path)
                if not self._cache.note_access(path):
                    break
                cached_segments.append((segment, path))
            if len(cached_segments) == len(source_segments):
                self._restore_cached_segments(replay, cached_segments)
            elif self._pool is not None:
                self._pool.notify()
            return self._store.get(replay.id) or replay

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

    def _restore_cached_segments(
        self,
        replay: Utterance,
        cached_segments: list[tuple[UtteranceSegment, Path]],
    ) -> None:
        """Publish a complete cached child plan under one fresh parent."""
        self._store.transition(replay.id, State.SYNTHESIZING)
        for source, path in cached_segments:
            child = self._store.transition_segment(replay.id, source.index, State.SYNTHESIZING)
            self._store.finish_synthesis(
                SynthesisWork(
                    id=child.artifact_id,
                    utterance_id=replay.id,
                    segment_index=child.index,
                    text=child.text,
                    voice=replay.voice,
                    speed=replay.speed,
                ),
                audio_path=str(path),
                duration_ms=source.duration_ms,
            )

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
        segments = self._store.segments(replay.id)
        return {
            "ok": True,
            "id": replay.id,
            "state": replay.state.value,
            "priority": replay.priority.value,
            "composite": bool(segments),
            "segment_count": len(segments) if segments else 1,
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

    async def _op_purge_cache(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        try:
            report = self._cache.purge()
        except OSError as exc:
            log.warning("event=cache_purge_inspection_failed")
            msg = "could not inspect audio cache"
            raise ApiError(INTERNAL, msg) from exc
        receipt = {
            "removed_files": len(report.removed_entries),
            "removed_bytes": report.removed_bytes,
            "protected_files": len(report.protected_entries),
            "protected_bytes": report.protected_bytes,
            "failed_files": len(report.failed_entries),
            "failed_bytes": report.failed_bytes,
        }
        self._server.broadcast({"event": "cache_changed", **receipt})
        return {"ok": True, **receipt}

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
            current_item = self._serialize_utterance(current)
            current_item["position_ms"] = controller.current_position_ms()
            segment = controller.current_segment
            segments = self._store.segments(current.id)
            if segment is not None:
                current_item["active_segment"] = {
                    "index": segment.index,
                    "number": segment.index + 1,
                    "count": len(segments),
                    "text": segment.text,
                    "state": segment.state.value,
                    "duration_ms": segment.duration_ms,
                    "position_ms": controller.current_segment_position_ms(),
                }
            elif not segments and current.state in (State.PLAYING, State.PAUSED):
                current_item["active_segment"] = {
                    "index": 0,
                    "number": 1,
                    "count": 1,
                    "text": current.text,
                    "state": current.state.value,
                    "duration_ms": current.duration_ms,
                    "position_ms": controller.current_position_ms(),
                }
        return {
            "ok": True,
            "state": "accepting",
            **self._speech_admission(),
            "playback_state": playback_state,
            "input_active": (
                self._input_detector.input_is_hot
                if self._input_detector.reading_available
                else None
            ),
            "interruption": self._interruption_view(),
            "current": current_item,
            "counts": counts,
            "engine": self._engine.name,
            "engine_preparing": engine_preparation(self._engine),
            "voice": self._store.get_setting("voice", self._default_voice()),
        }

    def _interruption_view(self) -> dict[str, Any] | None:
        """Describe a hold the listener's own voice caused, for the UI to explain."""
        controller = self._require_controller()
        if controller.interrupted_at is None:
            return None
        return {
            "reason": "listener_speaking",
            "at": controller.interrupted_at,
            "resume_armed": controller.resume_when_input_idle_armed,
        }

    def _cached_bytes(self) -> int:
        """Total size of cached audio, so it can be read against its cap."""
        return sum(entry.size_bytes for entry in FileAudioCache(self._cache_dir).inventory())

    async def _op_metrics(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Report what the daemon can say about its own responsiveness."""
        del payload
        return {
            "ok": True,
            "counts": self._store.counts(),
            "queue_depth": {
                "input": len(self._store.input_queue()),
                "playback": len(self._store.playback_queue()),
            },
            "cache": {
                "bytes": self._cached_bytes(),
                "max_bytes": self._cache_limit(),
            },
            **self._metrics.snapshot(),
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
            "playback": [self._serialize_utterance(u) for u in playback],
            "input": [self._serialize_utterance(u) for u in pending],
            "plan": [self._serialize_utterance(u) for u in plan],
            "history": history["items"],
            "voices": self._engine.list_voices(),
            "voice_assignments": [
                _serialize_assignment(item) for item in self._store.voice_assignments()
            ],
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
        settings = self._settings_values()
        if updates:
            self._server.broadcast(
                {
                    "event": "settings_changed",
                    "settings": {key: settings[key] for key in updates},
                }
            )
        return {"ok": True, "settings": settings}

    def _settings_values(self) -> dict[str, object]:
        return {
            "voice": self._store.get_setting("voice", self._default_voice()),
            "speed": float(self._store.get_setting("speed", "1.0")),
            "playback_rate": self._require_controller().playback_rate,
            "cache_max_bytes": self._cache_limit(),
            "captions_enabled": self._captions_enabled(),
            "captions_enabled_configured": self._store.has_setting("captions_enabled"),
            "input_interrupt_enabled": self._input_interrupt_enabled(),
            "input_interrupt_resume": self._input_interrupt_resume(),
        }

    def _captions_enabled(self) -> bool:
        return self._store.get_setting("captions_enabled", "false") == "true"

    def _apply_settings(self, updates: dict[str, Any]) -> None:
        handlers: dict[str, Callable[[object], None]] = {
            "voice": self._apply_voice_setting,
            "speed": self._apply_speed_setting,
            "cache_max_bytes": self._apply_cache_limit_setting,
            "playback_rate": self._apply_playback_rate_setting,
            "captions_enabled": self._apply_captions_enabled_setting,
            "input_interrupt_enabled": self._apply_input_interrupt_enabled_setting,
            "input_interrupt_resume": self._apply_input_interrupt_resume_setting,
        }
        for key, value in updates.items():
            handler = handlers.get(key)
            if handler is None:
                msg = f"unknown setting {key!r}"
                raise ApiError(BAD_REQUEST, msg)
            handler(value)

    def _apply_voice_setting(self, value: object) -> None:
        if value not in self._engine.list_voices():
            msg = f"unknown voice {value!r}"
            raise ApiError(BAD_REQUEST, msg)
        self._store.set_setting("voice", str(value))

    def _apply_speed_setting(self, value: object) -> None:
        speed = self._parse_speed(value)
        if speed is None:
            msg = "'speed' must be a number"
            raise ApiError(BAD_REQUEST, msg)
        self._store.set_setting("speed", str(speed))

    def _apply_cache_limit_setting(self, value: object) -> None:
        limit = self._parse_cache_limit(value)
        if limit is None:
            msg = "'cache_max_bytes' must be a non-negative integer"
            raise ApiError(BAD_REQUEST, msg)
        self._store.set_setting("cache_max_bytes", str(limit))
        self._enforce_cache_limit()

    def _apply_playback_rate_setting(self, value: object) -> None:
        rate = self._parse_playback_rate(value)
        if rate is None:
            choices = ", ".join(f"{choice:g}" for choice in PLAYBACK_RATES)
            msg = f"'playback_rate' must be one of: {choices}"
            raise ApiError(BAD_REQUEST, msg)
        self._require_controller().set_playback_rate(rate)

    def _apply_captions_enabled_setting(self, value: object) -> None:
        if type(value) is not bool:
            msg = "'captions_enabled' must be a boolean"
            raise ApiError(BAD_REQUEST, msg)
        self._store.set_setting("captions_enabled", "true" if value else "false")

    def _apply_input_interrupt_enabled_setting(self, value: object) -> None:
        if type(value) is not bool:
            msg = "'input_interrupt_enabled' must be a boolean"
            raise ApiError(BAD_REQUEST, msg)
        self._store.set_setting("input_interrupt_enabled", "true" if value else "false")

    def _apply_input_interrupt_resume_setting(self, value: object) -> None:
        if value not in _INPUT_INTERRUPT_RESUME_POLICIES:
            choices = ", ".join(_INPUT_INTERRUPT_RESUME_POLICIES)
            msg = f"'input_interrupt_resume' must be one of: {choices}"
            raise ApiError(BAD_REQUEST, msg)
        self._store.set_setting("input_interrupt_resume", str(value))

    @staticmethod
    def _parse_playback_rate(raw: object) -> float | None:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        rate = float(raw)
        return rate if rate in PLAYBACK_RATES else None

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
