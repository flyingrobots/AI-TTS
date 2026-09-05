# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Owner-only filesystem state at the daemon's durable adapter boundary."""

from __future__ import annotations

import os
import shutil
import sqlite3
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from aitts.adapters.audio_artifacts import FileAudioArtifacts
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.playback import FakeSink
from aitts.store import Store

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "SECURITY.md and architecture section 9: persisted speech is readable only by its owner"
    ),
]


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@contextmanager
def _process_umask(mask: int) -> Iterator[None]:
    previous = os.umask(mask)
    try:
        yield
    finally:
        os.umask(previous)


def test_new_store_files_are_owner_only_under_permissive_umask(tmp_path: Path) -> None:
    home = tmp_path / "state"
    with _process_umask(0):
        store = Store(home / "state.db")
        try:
            store.submit("private text", voice="v", speed=1.0)
            file_modes = {
                path.name: _mode(path) for path in sorted(home.glob("state.db*")) if path.is_file()
            }
            directory_mode = _mode(home)
        finally:
            store.close()

    assert {
        "directory": directory_mode,
        "files": file_modes,
    } == {
        "directory": 0o700,
        "files": {
            "state.db": 0o600,
            "state.db-shm": 0o600,
            "state.db-wal": 0o600,
        },
    }


async def test_daemon_migrates_existing_state_and_cache_to_owner_only(tmp_path: Path) -> None:
    home = tmp_path / "state"
    cache = home / "cache"
    cache.mkdir(parents=True)
    database = home / "state.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE legacy (value TEXT)")
    connection.commit()
    connection.close()
    audio = cache / "legacy.wav"
    audio.write_bytes(b"private audio")
    home.chmod(0o750)
    cache.chmod(0o750)
    database.chmod(0o640)
    audio.chmod(0o644)

    socket_dir = Path(tempfile.mkdtemp(prefix="aitts-private-state-"))
    daemon = Daemon(
        home=home,
        engine=FakeEngine(voices=["v"]),
        sink=FakeSink(),
        workers=1,
        socket_path=socket_dir / "daemon.sock",
    )
    try:
        await daemon.start()
        observed = {
            "home": _mode(home),
            "cache": _mode(cache),
            "database_files": {
                path.name: _mode(path) for path in sorted(home.glob("state.db*")) if path.is_file()
            },
            "audio": _mode(audio),
            "socket": _mode(daemon.socket_path),
        }
    finally:
        await daemon.stop()
        shutil.rmtree(socket_dir)

    assert observed == {
        "home": 0o700,
        "cache": 0o700,
        "database_files": {
            "state.db": 0o600,
            "state.db-shm": 0o600,
            "state.db-wal": 0o600,
        },
        "audio": 0o600,
        "socket": 0o600,
    }


def test_synthesis_candidate_and_published_audio_are_owner_only(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    cache.chmod(0o777)
    artifacts = FileAudioArtifacts(cache)

    with _process_umask(0):
        artifacts.prepare()
        candidate = artifacts.target("private")
        candidate.write_bytes(b"private audio")
        candidate_mode = _mode(candidate)
        published = artifacts.publish("private", candidate)

    assert {
        "cache": _mode(cache),
        "candidate": candidate_mode,
        "published": _mode(published),
    } == {
        "cache": 0o700,
        "candidate": 0o600,
        "published": 0o600,
    }


def test_daemon_refuses_to_follow_a_symlinked_state_home(tmp_path: Path) -> None:
    target = tmp_path / "shared"
    target.mkdir()
    target.chmod(0o750)
    home = tmp_path / "state-link"
    home.symlink_to(target, target_is_directory=True)
    daemon: Daemon | None = None
    error: OSError | None = None

    try:
        daemon = Daemon(
            home=home,
            engine=FakeEngine(voices=["v"]),
            sink=FakeSink(),
            workers=1,
        )
    except OSError as exc:
        error = exc
    finally:
        if daemon is not None:
            daemon.store.close()

    assert {
        "refused": error is not None,
        "target_mode": _mode(target),
        "database_created_through_link": (target / "state.db").exists(),
    } == {
        "refused": True,
        "target_mode": 0o750,
        "database_created_through_link": False,
    }
