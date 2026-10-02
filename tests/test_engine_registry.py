# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Durable per-clip backend routing and sensitivity enforcement."""

import asyncio
import contextlib
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from aitts.adapters.audio_artifacts import FileAudioArtifacts
from aitts.application.input_activity import NullInputActivity
from aitts.engine import FakeEngine
from aitts.model import Sensitivity, State, Utterance
from aitts.store import Store
from aitts.synthesis import SynthesisPool
from tests.conftest import wait_for

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "PROMPTS #4: each accepted clip retains its engine; private text stays local"
    ),
]


@pytest.fixture
def socket_path() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="tts-") as directory:
        yield Path(directory) / "d.sock"


def clip(store: Store, utterance_id: str) -> Utterance:
    result = store.get(utterance_id)
    assert result is not None
    return result


class NamedEngine(FakeEngine):
    def __init__(self, name: str, *, local: bool = True, voices: tuple[str, ...] = ("v",)) -> None:
        super().__init__(voices=list(voices))
        self.name = name
        self.is_local = local
        self.sources: list[str] = []

    def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> int:
        self.sources.append(text)
        return super().synthesize(text, voice, speed, out_path)


@pytest.mark.parametrize("segmented", [False, True])
async def test_durable_engine_routes_every_segment_after_reopen(
    tmp_path: Path, *, segmented: bool
) -> None:
    database = tmp_path / "state.db"
    store = Store(database)
    chosen = store.submit(
        "first second",
        voice="v",
        speed=1,
        engine="chosen",
        spoken_segments=("first", "second") if segmented else None,
    )
    store.close()
    store = Store(database)
    fallback, selected = NamedEngine("fallback"), NamedEngine("chosen")
    pool = SynthesisPool(
        store,
        fallback,
        FileAudioArtifacts(tmp_path / "cache"),
        engines={"fallback": fallback, "chosen": selected},
        workers=1,
    )
    task = asyncio.create_task(pool.run())
    try:
        await wait_for(lambda: clip(store, chosen.id).state is State.READY)
        assert selected.sources == (["first", "second"] if segmented else ["first second"])
        assert fallback.sources == []
        assert clip(store, chosen.id).engine == "chosen"
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        store.close()


@pytest.mark.parametrize("sensitivity", list(Sensitivity))
async def test_remote_backend_only_receives_explicitly_public_work(
    tmp_path: Path, sensitivity: Sensitivity
) -> None:
    store = Store(tmp_path / "state.db")
    engine = NamedEngine("remote", local=False)
    submitted = store.submit(
        "controlled source", voice="v", speed=1, engine="remote", sensitivity=sensitivity
    )
    pool = SynthesisPool(
        store, engine, FileAudioArtifacts(tmp_path / "cache"), engines={"remote": engine}
    )
    task = asyncio.create_task(pool.run())
    expected = State.READY if sensitivity is Sensitivity.PUBLIC else State.FAILED
    try:
        await wait_for(lambda: clip(store, submitted.id).state in (State.READY, State.FAILED))
        assert clip(store, submitted.id).state is expected
        assert engine.sources == (
            ["controlled source"] if sensitivity is Sensitivity.PUBLIC else []
        )
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        store.close()


async def test_live_default_switch_only_changes_later_admissions(
    tmp_path: Path, socket_path: Path
) -> None:
    import threading  # noqa: PLC0415

    from aitts.daemon import Daemon  # noqa: PLC0415
    from aitts.playback import FakeSink  # noqa: PLC0415

    release = threading.Event()

    class GatedEngine(NamedEngine):
        def warmup(self) -> None:
            if not release.wait(2):
                msg = "test did not release warmup"
                raise TimeoutError(msg)
            super().warmup()

    first, second = GatedEngine("first"), NamedEngine("second")
    daemon = Daemon(
        home=tmp_path,
        engine=first,
        engines={"second": second},
        sink=FakeSink(),
        socket_path=socket_path,
        input_activity=NullInputActivity(),
    )
    await daemon.start()
    try:
        await daemon.dispatch({"op": "pause"})
        before = await daemon.dispatch({"op": "submit", "text": "before switch"})
        change = await daemon.dispatch({"op": "settings", "set": {"engine": "second"}})
        after = await daemon.dispatch({"op": "submit", "text": "after switch"})
        override = await daemon.dispatch(
            {"op": "submit", "text": "explicit override", "engine": "first"}
        )
        assert change["settings"]["engine"] == "second"
        assert clip(daemon.store, before["id"]).engine == "first"
        assert clip(daemon.store, after["id"]).engine == "second"
        assert clip(daemon.store, override["id"]).engine == "first"
        catalog = await daemon.dispatch({"op": "engines"})
        assert {(row["name"], row["selected"]) for row in catalog["engines"]} == {
            ("first", False),
            ("second", True),
        }
        release.set()
        await wait_for(
            lambda: all(
                clip(daemon.store, receipt["id"]).state is State.READY
                for receipt in (before, after, override)
            )
        )
        assert sorted(first.sources) == ["before switch", "explicit override"]
        assert second.sources == ["after switch"]
    finally:
        release.set()
        await daemon.stop()


async def test_daemon_refuses_private_remote_submission_before_persisting(
    tmp_path: Path, socket_path: Path
) -> None:
    from aitts.daemon import Daemon  # noqa: PLC0415
    from aitts.ipc import ApiError  # noqa: PLC0415
    from aitts.playback import FakeSink  # noqa: PLC0415

    local, remote = NamedEngine("local"), NamedEngine("remote", local=False)
    daemon = Daemon(
        home=tmp_path,
        engine=local,
        engines={"remote": remote},
        sink=FakeSink(),
        socket_path=socket_path,
        input_activity=NullInputActivity(),
    )
    await daemon.start()
    try:
        for sensitivity in ("internal", "confidential"):
            with pytest.raises(ApiError, match="private speech requires a local engine"):
                await daemon.dispatch(
                    {
                        "op": "submit",
                        "text": "private source",
                        "engine": "remote",
                        "sensitivity": sensitivity,
                    }
                )
        assert daemon.store.counts() == {}
        assert remote.sources == []
    finally:
        await daemon.stop()


def test_each_backend_prepares_once_and_restart_only_reloads_its_target() -> None:
    from aitts.engines.registry import EngineRegistry  # noqa: PLC0415

    class CountedEngine(NamedEngine):
        loads = 0

        def warmup(self) -> None:
            self.loads += 1

    first, second = CountedEngine("first"), CountedEngine("second")
    registry = EngineRegistry({"first": first, "second": second})
    assert (registry.state("first"), registry.state("second")) == ("cold", "cold")
    for name in ("first", "second", "first", "second"):
        registry.prepare(name)
    assert (first.loads, second.loads) == (1, 1)
    assert (registry.state("first"), registry.state("second")) == ("ready", "ready")
    registry.restart("second")
    assert (first.loads, second.loads) == (1, 2)


def test_failed_backend_requires_explicit_retry_without_poisoning_other_engines() -> None:
    from aitts.engine import SynthesisError  # noqa: PLC0415
    from aitts.engines.registry import EngineRegistry  # noqa: PLC0415

    class UnavailableEngine(NamedEngine):
        broken = True
        attempts = 0

        def warmup(self) -> None:
            self.attempts += 1
            if self.broken:
                msg = "owned missing model"
                raise SynthesisError(msg)

    broken, healthy = UnavailableEngine("broken"), NamedEngine("healthy")
    registry = EngineRegistry({"broken": broken, "healthy": healthy})
    with pytest.raises(SynthesisError, match="owned missing model"):
        registry.prepare("broken")
    with pytest.raises(SynthesisError, match="restart the model"):
        registry.prepare("broken")
    registry.prepare("healthy")
    assert (registry.state("broken"), registry.state("healthy")) == ("failed", "ready")
    assert broken.attempts == 1
    broken.broken = False
    registry.restart("broken")
    assert (registry.state("broken"), broken.attempts) == ("ready", 2)


def test_startup_catalog_uses_owned_configuration_without_loading_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aitts.engines.selection import configured_engines  # noqa: PLC0415

    monkeypatch.delenv("AI_TTS_CHATTERBOX_MODEL_DIR", raising=False)
    monkeypatch.setenv("AI_TTS_OPENAI_URL", "http://localhost:9876")
    monkeypatch.setenv("AI_TTS_OPENAI_MODEL", "owned-model")
    monkeypatch.setenv("AI_TTS_OPENAI_VOICE", "owned-voice")
    selected, engines = configured_engines(
        tmp_path, override="openai-audio", probe_mlx=lambda: True
    )
    assert set(engines) == {"kokoro", "kokoro-mlx", "openai-audio"}
    assert selected is engines["openai-audio"]
    assert selected.list_voices() == ["owned-voice"]
    monkeypatch.setenv("AI_TTS_OPENAI_URL", "https://example.com")
    with pytest.raises(ValueError, match="loopback"):
        configured_engines(tmp_path, probe_mlx=lambda: False)


@pytest.mark.parametrize("saved", ["chatterbox", "openai-audio"])
def test_saved_default_missing_from_startup_environment_falls_back_to_kokoro(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, saved: str
) -> None:
    from aitts.engines.selection import configured_engines  # noqa: PLC0415

    monkeypatch.delenv("AI_TTS_CHATTERBOX_MODEL_DIR", raising=False)
    monkeypatch.delenv("AI_TTS_OPENAI_URL", raising=False)
    store = Store(tmp_path / "state.db")
    store.set_setting("engine", saved)
    store.close()
    # A launch environment without the adapter's variables must still start a daemon.
    selected, engines = configured_engines(tmp_path, probe_mlx=lambda: False)
    assert set(engines) == {"kokoro"}
    assert selected is engines["kokoro"]
    with pytest.raises(ValueError, match="not configured"):
        configured_engines(tmp_path, override=saved, probe_mlx=lambda: False)


def test_legacy_engine_binding_is_durable_and_never_overwrites_an_existing_choice(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "state.db")
    legacy = store.submit("legacy", voice="v", speed=1)
    selected = store.submit("selected", voice="v", speed=1, engine="selected")
    store.bind_legacy_engine("original")
    store.close()
    store = Store(tmp_path / "state.db")
    try:
        store.bind_legacy_engine("new-default")
        assert clip(store, legacy.id).engine == "original"
        assert clip(store, selected.id).engine == "selected"
    finally:
        store.close()


def test_database_without_engine_column_migrates_without_losing_queued_text(tmp_path: Path) -> None:
    import sqlite3  # noqa: PLC0415

    database = tmp_path / "state.db"
    with sqlite3.connect(database) as connection:
        connection.execute("""CREATE TABLE utterances (
            id TEXT PRIMARY KEY, text TEXT NOT NULL, voice TEXT NOT NULL, speed REAL NOT NULL,
            sensitivity TEXT NOT NULL, priority TEXT NOT NULL, state TEXT NOT NULL,
            order_key REAL NOT NULL, submitted_at REAL NOT NULL, state_changed_at REAL NOT NULL,
            source TEXT, error TEXT, duration_ms INTEGER, played_ms INTEGER,
            audio_path TEXT, replay_of TEXT)""")
        connection.execute("""INSERT INTO utterances
            (id, text, voice, speed, sensitivity, priority, state, order_key,
             submitted_at, state_changed_at)
            VALUES ('legacy', 'retained source', 'v', 1,
                    'confidential', 'normal', 'Queued', 1, 1, 1)
        """)
    store = Store(database)
    try:
        store.bind_legacy_engine("original")
        work = store.claim_for_synthesis()
        assert work is not None
        assert (work.text, work.engine, work.sensitivity) == (
            "retained source",
            "original",
            Sensitivity.CONFIDENTIAL,
        )
    finally:
        store.close()


def test_failed_legacy_binding_commit_rolls_back_before_retry(tmp_path: Path) -> None:
    import sqlite3  # noqa: PLC0415

    from tests.test_store import OneShotCommitFailure  # noqa: PLC0415

    connection = OneShotCommitFailure(str(tmp_path / "state.db"))
    store = Store(tmp_path / "state.db", connect=lambda _: connection)
    try:
        legacy = store.submit("legacy", voice="v", speed=1)
        connection.fail_next_commit = True
        with pytest.raises(sqlite3.OperationalError, match="seeded commit failure"):
            store.bind_legacy_engine("discarded")
        assert clip(store, legacy.id).engine is None
        store.bind_legacy_engine("accepted")
        assert clip(store, legacy.id).engine == "accepted"
    finally:
        store.close()


async def test_model_and_voice_update_validates_the_target_before_changing_either(
    tmp_path: Path,
    socket_path: Path,
) -> None:
    from aitts.daemon import Daemon  # noqa: PLC0415
    from aitts.ipc import ApiError  # noqa: PLC0415
    from aitts.playback import FakeSink  # noqa: PLC0415

    first, second = NamedEngine("first"), FakeEngine(voices=["other-voice"])
    second.name = "second"
    daemon = Daemon(
        home=tmp_path,
        engine=first,
        engines={"second": second},
        sink=FakeSink(),
        socket_path=socket_path,
        input_activity=NullInputActivity(),
    )
    await daemon.start()
    try:
        with pytest.raises(ApiError, match="unknown voice"):
            await daemon.dispatch({"op": "settings", "set": {"engine": "second", "voice": "v"}})
        unchanged = await daemon.dispatch({"op": "settings"})
        assert (unchanged["settings"]["engine"], unchanged["settings"]["voice"]) == ("first", "v")
        changed = await daemon.dispatch(
            {
                "op": "settings",
                "set": {"voice": "other-voice", "engine": "second"},
            }
        )
        assert (changed["settings"]["engine"], changed["settings"]["voice"]) == (
            "second",
            "other-voice",
        )
        receipt = await daemon.dispatch({"op": "submit", "text": "new voice"})
        assert clip(daemon.store, receipt["id"]).voice == "other-voice"
    finally:
        await daemon.stop()


async def test_external_server_is_not_claimed_hot_or_locally_restarted(
    tmp_path: Path,
    socket_path: Path,
) -> None:
    from aitts.daemon import Daemon  # noqa: PLC0415
    from aitts.engines.openai_compatible import OpenAIAudioEngine  # noqa: PLC0415
    from aitts.ipc import ApiError  # noqa: PLC0415
    from aitts.playback import FakeSink  # noqa: PLC0415
    from tests.test_engine_openai_compatible import local_server, wav_bytes  # noqa: PLC0415

    with local_server(wav_bytes()) as (url, requests):
        engine = OpenAIAudioEngine(url, "model", "voice")
        daemon = Daemon(
            home=tmp_path,
            engine=engine,
            sink=FakeSink(),
            socket_path=socket_path,
            input_activity=NullInputActivity(),
        )
        await daemon.start()
        try:
            await daemon._warmup_finished.wait()
            snapshot = await daemon.dispatch({"op": "snapshot"})
            assert snapshot["runtime"]["model_state"] == "server managed"
            with pytest.raises(ApiError, match="owning server"):
                await daemon.dispatch({"op": "restart_model"})
            assert requests == []
        finally:
            await daemon.stop()


def test_saved_voice_from_another_backend_reports_a_speakable_default(tmp_path: Path) -> None:
    from aitts.settings import SettingsService  # noqa: PLC0415
    from tests.test_settings_service import FakeEnvironment  # noqa: PLC0415

    store = Store(tmp_path / "state.db")
    try:
        store.set_setting("voice", "old-backend-voice")
        settings = SettingsService(store, FakeEnvironment(voices=("new-backend-voice",)))
        assert settings.speaking_voice() == "new-backend-voice"
        assert settings.values()["voice"] == "new-backend-voice"
    finally:
        store.close()


async def test_live_switch_away_and_back_keeps_the_saved_voice(
    tmp_path: Path, socket_path: Path
) -> None:
    from aitts.daemon import Daemon  # noqa: PLC0415
    from aitts.playback import FakeSink  # noqa: PLC0415

    original = NamedEngine("original", voices=("v", "kept"))
    other = NamedEngine("other", voices=("o",))
    daemon = Daemon(
        home=tmp_path,
        engine=original,
        engines={"other": other},
        sink=FakeSink(),
        socket_path=socket_path,
        input_activity=NullInputActivity(),
    )
    await daemon.start()
    try:
        await daemon.dispatch({"op": "settings", "set": {"voice": "kept"}})
        away = await daemon.dispatch({"op": "settings", "set": {"engine": "other"}})
        assert away["settings"]["voice"] == "o"
        back = await daemon.dispatch({"op": "settings", "set": {"engine": "original"}})
        assert back["settings"]["voice"] == "kept"
    finally:
        await daemon.stop()


async def test_model_preparation_failure_is_captured_in_the_clips_own_log(tmp_path: Path) -> None:
    import json  # noqa: PLC0415

    from aitts.adapters.clip_evidence import ClipEvidence  # noqa: PLC0415
    from aitts.engine import SynthesisError  # noqa: PLC0415

    def fail_preparation(name: str) -> None:
        raise SynthesisError(name + " model assets unavailable")

    store = Store(tmp_path / "state.db")
    engine = NamedEngine("owned")
    submitted = store.submit("owned source", voice="v", speed=1, engine="owned")
    cache = tmp_path / "cache"
    pool = SynthesisPool(
        store,
        engine,
        FileAudioArtifacts(cache),
        evidence=ClipEvidence(cache),
        prepare_engine=fail_preparation,
    )
    task = asyncio.create_task(pool.run())
    try:
        await wait_for(lambda: clip(store, submitted.id).state is State.FAILED)
        logfile = cache / submitted.id / "synthesis.jsonl"
        events = (
            [json.loads(line) for line in logfile.read_text().splitlines()]
            if logfile.exists()
            else []
        )
        assert any(
            event.get("event") == "failed"
            and event.get("error") == "owned model assets unavailable"
            for event in events
        )
        assert (cache / submitted.id / "source.txt").read_text() == "owned source"
        assert engine.sources == []
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        store.close()


async def test_startup_warmup_holds_only_its_own_engines_clips(
    tmp_path: Path, socket_path: Path
) -> None:
    import threading  # noqa: PLC0415

    from aitts.daemon import Daemon  # noqa: PLC0415
    from aitts.playback import FakeSink  # noqa: PLC0415

    started, release = threading.Event(), threading.Event()

    class WedgedWarmupEngine(NamedEngine):
        def warmup(self) -> None:
            started.set()
            if not release.wait(5):
                msg = "test did not release warmup"
                raise TimeoutError(msg)
            super().warmup()

    startup, other = WedgedWarmupEngine("startup"), NamedEngine("other")
    daemon = Daemon(
        home=tmp_path,
        engine=startup,
        engines={"other": other},
        sink=FakeSink(),
        socket_path=socket_path,
        input_activity=NullInputActivity(),
    )
    await daemon.start()
    try:
        assert await asyncio.to_thread(started.wait, 1)
        await daemon.dispatch({"op": "pause"})
        held = await daemon.dispatch({"op": "submit", "text": "startup source"})
        routed = await daemon.dispatch({"op": "submit", "text": "other source", "engine": "other"})
        # The other backend prepares on its own while the startup model is still loading.
        await wait_for(lambda: clip(daemon.store, routed["id"]).state is State.READY)
        assert other.sources == ["other source"]
        assert clip(daemon.store, held["id"]).state is State.QUEUED
        assert startup.sources == []
        release.set()
        await wait_for(lambda: clip(daemon.store, held["id"]).state is State.READY)
        assert startup.sources == ["startup source"]
    finally:
        release.set()
        await daemon.stop()


async def test_fixed_speed_engine_speaks_default_submissions_despite_a_saved_speed(
    tmp_path: Path, socket_path: Path
) -> None:
    from aitts.daemon import Daemon  # noqa: PLC0415
    from aitts.ipc import ApiError  # noqa: PLC0415
    from aitts.playback import FakeSink  # noqa: PLC0415

    class FixedSpeedEngine(NamedEngine):
        supported_speeds = (1.0,)

    fixed = FixedSpeedEngine("fixed")
    daemon = Daemon(
        home=tmp_path,
        engine=NamedEngine("variable"),
        engines={"fixed": fixed},
        sink=FakeSink(),
        socket_path=socket_path,
        input_activity=NullInputActivity(),
    )
    await daemon.start()
    try:
        await daemon.dispatch({"op": "pause"})
        await daemon.dispatch({"op": "settings", "set": {"speed": 1.25}})
        await daemon.dispatch({"op": "settings", "set": {"engine": "fixed"}})
        # The composer sends no speed: the saved default must not make every clip fail.
        receipt = await daemon.dispatch({"op": "submit", "text": "default speed"})
        assert clip(daemon.store, receipt["id"]).engine == "fixed"
        assert clip(daemon.store, receipt["id"]).speed == 1.0
        with pytest.raises(ApiError, match="generation speed 1"):
            await daemon.dispatch({"op": "submit", "text": "explicit", "speed": 1.25})
        settings = await daemon.dispatch({"op": "settings"})
        assert settings["settings"]["speed"] == 1.25
    finally:
        await daemon.stop()
