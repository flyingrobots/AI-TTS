# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The Python daemon opens a database that the Rust ``aitts-store`` crate wrote."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from aitts.store import Store

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "the Python daemon's own reads of golden.db, written by the same operations in Python"
    ),
]

FIXTURES = Path(__file__).resolve().parents[1] / "crates/aitts-store/tests/fixtures"


def _read(fixture: str, tmp_path: Path) -> tuple[list[object], ...]:
    database = tmp_path / fixture
    shutil.copyfile(FIXTURES / fixture, database)
    store = Store(database)
    ids = [row["id"] for row in store._db.execute("SELECT id FROM utterances ORDER BY id")]
    result: tuple[list[object], ...] = (
        [store.get(utt_id) for utt_id in ids],
        [store.segments(utt_id) for utt_id in ids],
        list(store.input_queue()),
        list(store.playback_queue()),
        list(store.history()),
        [(key, store.get_setting(key, "")) for key in ("default_voice", "speed")],
        list(store.voice_assignments()),
    )
    store.close()
    return result


def test_python_reads_the_rust_written_database_as_its_own(tmp_path: Path) -> None:
    rust = _read("rust-written.db", tmp_path)
    python = _read("golden.db", tmp_path)

    assert rust == python
    assert len(rust[0]) == 5
