# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Token times across the private model-worker pipe, old and new workers alike."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from aitts.engines import managed
from aitts.engines.managed import ManagedEngine, ManagedStreamingEngine
from aitts.timing import WordMark

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "worker protocol 1 stays compatible: marks only when the daemon asks and the "
        "engine can; a worker that predates them still speaks"
    ),
]

_TIMED_WORKER = """
from pathlib import Path
from aitts import worker_contract
from aitts.engine import FakeEngine
from aitts.timing import WordMark
class TimedModel(FakeEngine):
    def synthesize_timed(self, text, voice, speed, out_path):
        return self.synthesize(text, voice, speed, out_path), (WordMark(text, 5.0, 95.5),)
    def stream_synthesize(self, text, voice, speed):
        yield b"\\x01\\x00" * 240
    def stream_synthesize_timed(self, text, voice, speed):
        yield (WordMark(text, 0.0, 10.0),)
        yield b"\\x01\\x00" * 240
worker_contract.local_engine = lambda name, root: TimedModel(["voice"], duration_ms=100)
worker_contract.main()
"""

_UNTIMED_WORKER = """
from aitts import worker_contract
from aitts.engine import FakeEngine
class OldModel(FakeEngine):
    def stream_synthesize(self, text, voice, speed):
        yield b"\\x01\\x00" * 240
worker_contract.local_engine = lambda name, root: OldModel(["voice"], duration_ms=100)
worker_contract.main()
"""


def _runtime(tmp_path: Path, worker: str) -> Path:
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "venv").symlink_to(Path(sys.executable).parent.parent, target_is_directory=True)
    package = root / "adapter/aitts"
    shutil.copytree(
        Path(managed.__file__).parents[1], package, ignore=shutil.ignore_patterns("__pycache__")
    )
    (package / "model_worker.py").rename(package / "worker_contract.py")
    (package / "model_worker.py").write_text(worker)
    return root


def test_timed_worker_reports_marks_only_when_asked(tmp_path: Path) -> None:
    root = _runtime(tmp_path, _TIMED_WORKER)
    files = ManagedEngine("chatterbox", root)
    stream = ManagedStreamingEngine("kokoro", root)
    try:
        duration, marks = files.synthesize_timed("clip", "voice", 1.0, tmp_path / "a.wav")
        timed = list(stream.stream_synthesize_timed("live", "voice", 1.0))
        untimed = list(stream.stream_synthesize("live", "voice", 1.0))
        assert files.synthesize("clip", "voice", 1.0, tmp_path / "b.wav") == 100
    finally:
        files.close()
        stream.close()

    assert (duration, marks) == (100, (WordMark("clip", 5.0, 95.5),))
    assert timed == [(WordMark("live", 0.0, 10.0),), b"\x01\x00" * 240]
    assert untimed == [b"\x01\x00" * 240]


def test_worker_that_predates_marks_still_speaks_without_them(tmp_path: Path) -> None:
    root = _runtime(tmp_path, _UNTIMED_WORKER)
    files = ManagedEngine("chatterbox", root)
    stream = ManagedStreamingEngine("kokoro", root)
    try:
        result = files.synthesize_timed("clip", "voice", 1.0, tmp_path / "a.wav")
        items = list(stream.stream_synthesize_timed("live", "voice", 1.0))
    finally:
        files.close()
        stream.close()

    assert result == (100, ())
    assert items == [b"\x01\x00" * 240]
