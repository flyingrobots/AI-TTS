# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The synthesis worker pool: parallel, opportunistic, failure-isolated.

Generation is slow and parallelizable, so it runs ahead of playback in N
workers (architecture.md §2, §4). One bad utterance must never stall the
queue: the failure mode to design against is the system quietly ceasing to
speak.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from aitts.adapters.diagnostic_logging import utterance_trace
from aitts.engine import StreamingEngine, SynthesisError, eligible_engine_names
from aitts.streaming import SpoolingPCMStream, StreamingRegistry

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping
    from pathlib import Path

    from aitts.adapters.clip_evidence import ClipEvidence
    from aitts.application.artifacts import AudioArtifactPort
    from aitts.engine import Engine
    from aitts.model import SynthesisWork
    from aitts.store import Store

log = logging.getLogger(__name__)


class SynthesisPool:
    """Drains the input queue into rendered, cached audio."""

    def __init__(  # noqa: PLR0913 - injected synthesis boundaries
        self,
        store: Store,
        engine: Engine,
        artifacts: AudioArtifactPort,
        *,
        workers: int = 2,
        evidence: ClipEvidence | None = None,
        streams: StreamingRegistry | None = None,
        engines: Mapping[str, Engine] | None = None,
        prepare_engine: Callable[[str], None] | None = None,
        held_engines: Callable[[], Collection[str]] | None = None,
    ) -> None:
        """Create a pool of ``workers`` synthesis workers over ``engine``.

        ``held_engines`` names backends whose queued work must not be claimed
        yet, so one model's preparation never holds another model's clips.
        """
        self._held_engines = held_engines
        self._streams = streams
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False
        self._evidence = evidence
        self._store = store
        self._engine = engine
        self._engines = dict(engines) if engines is not None else {engine.name: engine}
        self._prepare_engine = prepare_engine
        self._artifacts = artifacts
        self._workers = max(1, workers)
        self.active_jobs = 0
        self.enabled = asyncio.Event()
        self.enabled.set()
        self._wake = asyncio.Event()
        # Counts how many times a worker has found no work and parked. It is
        # the only observable moment at which the pool is provably idle, which
        # a test needs in order to prove that notify() is what woke it rather
        # than a worker that had not started looking yet.
        self.parks = 0

    def notify(self) -> None:
        """Tell the pool new work may be available."""
        self._wake.set()

    def register_engine(self, engine: Engine) -> None:
        """Add a validated runtime between jobs; accepted work retains its model name."""
        if self.active_jobs:
            message = "cannot publish a model while synthesis is active"
            raise RuntimeError(message)
        self._engines[engine.name] = engine

    async def run(self) -> None:
        """Run the workers until cancelled."""
        self._loop = asyncio.get_running_loop()
        self._artifacts.prepare()
        self._running = True
        try:
            async with asyncio.TaskGroup() as group:
                for _ in range(self._workers):
                    group.create_task(self._worker())
        finally:
            self._running = False
            if self._streams is not None:
                self._streams.close()

    async def _worker(self) -> None:
        while True:
            await self.enabled.wait()
            claimed = self._store.claim_for_synthesis(
                held_engines=self._held_engines() if self._held_engines is not None else (),
                unbound_engine=self._engine.name,
            )
            if claimed is None:
                self.parks += 1
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=0.5)
                continue
            self.active_jobs += 1
            try:
                await self._synthesize_one(claimed)
            finally:
                self.active_jobs -= 1

    async def _synthesize_one(self, work: SynthesisWork) -> None:
        try:
            out_path = self._artifacts.target(work.id)
        except Exception as exc:  # noqa: BLE001 - adapter failure is per-item
            self._record_failure(work, f"artifact target failed: {exc}")
            return
        try:
            duration_ms = await asyncio.to_thread(
                self._render,
                work,
                out_path,
            )
        except Exception as exc:  # noqa: BLE001 - any engine failure is Failed, not fatal
            self._finish(work, error=str(exc), out_path=out_path)
            self._finish_stream(work, error=str(exc))
            return
        published = self._finish(work, duration_ms=duration_ms, out_path=out_path)
        self._finish_stream(work, error=None if published else "stream publication failed")

    def _finish_stream(self, work: SynthesisWork, *, error: str | None) -> None:
        if self._streams is not None:
            self._store.discard_streaming_job(work.id)
            self._streams.finish(work.id, error=error)

    def _stream_ready(self, work: SynthesisWork) -> None:
        if self._running:
            self._store.start_streaming(work)

    def _render_stream(self, work: SynthesisWork, out_path: Path, engine: StreamingEngine) -> int:
        assert self._streams is not None  # noqa: S101 - streaming admission checked
        assert self._loop is not None  # noqa: S101 - worker started by run
        source = SpoolingPCMStream(out_path)
        self._streams.add(work.id, source)
        first = True
        for pcm in engine.stream_synthesize(work.text, work.voice, work.speed):
            if not pcm:
                continue
            source.append(pcm)
            if first:
                self._loop.call_soon_threadsafe(self._stream_ready, work)
                first = False
        if first:
            msg = "streaming engine produced no audio"
            raise ValueError(msg)
        return source.seal()

    def _render(self, work: SynthesisWork, out_path: Path) -> int:
        name = work.engine or self._engine.name
        if self._evidence is not None:
            self._evidence.prepare(work, name)
        try:
            if name not in eligible_engine_names(self._engines, work.sensitivity):
                msg = f"engine {name!r} is unavailable or disallowed for this clip's sensitivity"
                raise SynthesisError(msg)  # noqa: TRY301 - capture the rejection with this clip
            engine = self._engines[name]
            if self._prepare_engine is not None:
                self._prepare_engine(name)
            duration = (
                self._render_stream(work, out_path, engine)
                if self._streams is not None and isinstance(engine, StreamingEngine)
                else engine.synthesize(work.text, work.voice, work.speed, out_path)
            )
        except Exception as exc:
            if self._evidence is not None:
                self._evidence.record(work.id, "synthesis", "failed", error=str(exc))
            raise
        if self._evidence is not None:
            provenance = getattr(engine, "evidence", None)
            try:
                metadata = (
                    provenance(work.voice)
                    if callable(provenance)
                    else {"model_identity": "unavailable"}
                )
                self._evidence.generated(work.id, metadata)
            except Exception:  # noqa: BLE001 - diagnostics cannot fail synthesis
                self._evidence.record(work.id, "synthesis", "model_metadata_unavailable")
            self._evidence.audio_generated(work.id, out_path)
            self._evidence.record(work.id, "synthesis", "rendered", duration_ms=duration)
        return duration

    def _finish(  # noqa: C901 - publication and evidence stay in one lifecycle operation
        self,
        work: SynthesisWork,
        *,
        duration_ms: int | None = None,
        error: str | None = None,
        out_path: Path,
    ) -> bool:
        if not self._store.synthesis_work_is_active(work):
            # Cancelled underneath us: the engine could not abort, so the
            # result is discarded on completion (architecture §7).
            self._discard(out_path)
            return False
        failure = error
        if failure is None:
            try:
                usable = self._artifacts.is_usable(out_path)
            except Exception as exc:  # noqa: BLE001 - adapter failure is per-item
                failure = f"artifact validation failed: {exc}"
            else:
                if not usable:
                    failure = "synthesis produced no usable audio artifact"
        published_path: Path | None = None
        if failure is None:
            try:
                published_path = self._artifacts.publish(work.id, out_path)
            except Exception as exc:  # noqa: BLE001 - adapter failure is per-item
                failure = f"artifact publication failed: {exc}"
        if failure is not None:
            self._discard(out_path)
            self._record_failure(work, failure)
            return False
        if published_path is None:  # pragma: no cover - guarded by failure handling
            self._record_failure(work, "artifact publication returned no path")
            return False
        # Keep final publication and its durable owner record in one event-loop
        # turn. Cache purge also runs synchronously on that loop, so it can see
        # either an invisible candidate or a protected published artifact,
        # never an unowned final WAV between these two calls.
        if self._evidence is not None:
            self._evidence.record(work.id, "synthesis", "published", duration_ms=duration_ms)
        try:
            self._store.finish_synthesis(
                work,
                audio_path=str(published_path),
                duration_ms=duration_ms,
            )
        except Exception as exc:  # noqa: BLE001 - failed durable ownership cannot publish success
            self._discard(published_path)
            self._record_failure(work, f"artifact metadata failed: {exc}")
            return False

        return True

    def _discard(self, out_path: Path) -> None:
        try:
            discarded = self._artifacts.discard(out_path)
        except Exception:  # noqa: BLE001 - cleanup failure is isolated to one artifact
            log.warning("event=synthesis_artifact_discard_failed")
            return
        if not discarded:
            log.warning("event=synthesis_artifact_discard_failed")

    def _record_failure(self, work: SynthesisWork, error: str) -> None:
        if self._store.synthesis_work_is_active(work):
            self._store.fail_synthesis(work, error)
        log.warning("event=synthesis_failed trace=%s", utterance_trace(work.utterance_id))
