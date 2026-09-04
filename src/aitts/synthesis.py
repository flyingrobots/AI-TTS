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

from aitts.model import State

if TYPE_CHECKING:
    from pathlib import Path

    from aitts.application.artifacts import AudioArtifactPort
    from aitts.engine import Engine
    from aitts.store import Store

log = logging.getLogger(__name__)


class SynthesisPool:
    """Drains the input queue into rendered, cached audio."""

    def __init__(
        self,
        store: Store,
        engine: Engine,
        artifacts: AudioArtifactPort,
        *,
        workers: int = 2,
    ) -> None:
        """Create a pool of ``workers`` synthesis workers over ``engine``."""
        self._store = store
        self._engine = engine
        self._artifacts = artifacts
        self._workers = max(1, workers)
        self._wake = asyncio.Event()

    def notify(self) -> None:
        """Tell the pool new work may be available."""
        self._wake.set()

    async def run(self) -> None:
        """Run the workers until cancelled."""
        self._artifacts.prepare()
        async with asyncio.TaskGroup() as group:
            for _ in range(self._workers):
                group.create_task(self._worker())

    async def _worker(self) -> None:
        while True:
            claimed = self._store.claim_for_synthesis()
            if claimed is None:
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=0.5)
                continue
            await self._synthesize_one(claimed.id)

    async def _synthesize_one(self, utt_id: str) -> None:
        utt = self._store.get(utt_id)
        if utt is None:  # pragma: no cover - claimed rows exist
            return
        out_path = self._artifacts.target(utt.id)
        try:
            duration_ms = await asyncio.to_thread(
                self._engine.synthesize, utt.text, utt.voice, utt.speed, out_path
            )
        except Exception as exc:  # noqa: BLE001 - any engine failure is Failed, not fatal
            self._finish(utt_id, error=str(exc), out_path=out_path)
            return
        self._finish(utt_id, duration_ms=duration_ms, out_path=out_path)

    def _finish(
        self,
        utt_id: str,
        *,
        duration_ms: int | None = None,
        error: str | None = None,
        out_path: Path,
    ) -> None:
        current = self._store.get(utt_id)
        if current is None or current.state is not State.SYNTHESIZING:
            # Cancelled underneath us: the engine could not abort, so the
            # result is discarded on completion (architecture §7).
            self._discard(utt_id, out_path)
            return
        failure = error
        if failure is None and not self._artifacts.is_usable(out_path):
            failure = "synthesis produced no usable audio artifact"
        if failure is not None:
            self._discard(utt_id, out_path)
            self._store.transition(utt_id, State.FAILED, error=failure)
            log.warning("synthesis failed for %s: %s", utt_id, failure)
            return
        self._store.transition(
            utt_id, State.READY, audio_path=str(out_path), duration_ms=duration_ms
        )

    def _discard(self, utt_id: str, out_path: Path) -> None:
        if not self._artifacts.discard(out_path):
            log.warning("could not discard failed synthesis artifact for %s: %s", utt_id, out_path)
