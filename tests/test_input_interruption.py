# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Speaking into the microphone takes the floor from playback (architecture §7).

The platform's "an input is capturing" reading is deliberately coarse: it stays
true for minutes after the listener stops talking, because dictation software
holds the device open for instant start. A level-triggered hold would therefore
fight the listener — resume, re-hold, resume. Only the cold-to-hot *edge*
interrupts, so one talking spell interrupts once and Resume sticks.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aitts.application.input_activity import FakeInputActivity, InputInterruptDetector
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.ipc import ApiError
from aitts.model import State
from aitts.playback import FakeSink, PlaybackController
from aitts.store import Store
from tests.conftest import wait_for
from tests.test_playback import DeterministicPlaybackSchedule, make_ready

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "listener-owned transport in architecture section 7: the listener's own voice "
        "takes precedence over queued speech"
    ),
]


# -- the edge detector ----------------------------------------------------


def observe_all(detector: InputInterruptDetector, readings: list[bool | None]) -> list[bool]:
    """Feed every reading in order and collect which ones fired."""
    return [detector.observe(reading) for reading in readings]


def test_a_talking_spell_interrupts_exactly_once() -> None:
    detector = InputInterruptDetector(confirmations=2)

    # Cold, then a long hot spell: one interrupt at the start of the spell.
    fired = observe_all(detector, [False, True, True, True, True, True, True])

    assert fired == [False, False, True, False, False, False, False]


def test_input_already_capturing_at_startup_does_not_interrupt() -> None:
    detector = InputInterruptDetector(confirmations=2)

    # Something held the device before the daemon started (a screen recorder,
    # dictation software idling). That is not the listener taking the floor.
    fired = observe_all(detector, [True, True, True, True])

    assert fired == [False, False, False, False]


def test_a_momentary_blip_does_not_interrupt() -> None:
    detector = InputInterruptDetector(confirmations=2)

    fired = observe_all(detector, [False, True, False, True, False])

    assert not any(fired)


def test_a_later_spell_interrupts_again_once_the_input_is_released() -> None:
    detector = InputInterruptDetector(confirmations=2)

    fired = observe_all(
        detector,
        [False, True, True, True, False, False, True, True],
    )

    assert fired == [False, False, True, False, False, False, False, True]


def test_unreadable_input_state_changes_nothing() -> None:
    detector = InputInterruptDetector(confirmations=2)

    # None means the platform could not be asked; it must not be read as cold,
    # which would let the next hot reading fire a spurious interrupt.
    fired = observe_all(detector, [False, True, True, None, None, True, True])

    assert fired == [False, False, True, False, False, False, False]


def test_the_detector_reads_from_the_activity_port() -> None:
    activity = FakeInputActivity(active=False)
    detector = InputInterruptDetector(confirmations=1)

    assert detector.observe(activity.input_is_active()) is False
    activity.active = True
    assert detector.observe(activity.input_is_active()) is True
    assert detector.observe(activity.input_is_active()) is False


# -- what an interrupt does to playback -----------------------------------


def is_held(ctl: PlaybackController) -> bool:
    # Read through a call so mypy does not narrow the attribute across mutations.
    return ctl.held


def sink_active(ctl: PlaybackController) -> bool:
    # Read through a call so mypy does not narrow the attribute across mutations.
    return ctl._sink_active


def is_armed(ctl: PlaybackController) -> bool:
    # Read through a call so mypy does not narrow the attribute across mutations.
    return ctl.resume_when_input_idle_armed


async def controller(store: Store, sink: FakeSink) -> tuple[PlaybackController, asyncio.Task[None]]:
    """Start a controller draining the plan through ``sink``."""
    schedule = DeterministicPlaybackSchedule()
    ctl = PlaybackController(store, sink, schedule)
    task = asyncio.get_running_loop().create_task(ctl.run())
    return ctl, task


async def test_interrupt_pauses_the_current_clip_and_records_why(
    store: Store, sink: FakeSink
) -> None:
    utt = make_ready(store, "a long explanation")
    ctl, task = await controller(store, sink)
    try:
        await wait_for(lambda: store.get(utt.id) is not None and ctl.current_id == utt.id)
        sink.advance_to(400)

        interrupted = await ctl.interrupt()

        assert interrupted is True
        assert sink.paused is True
        assert ctl.held is True
        assert ctl.interrupted_at is not None
        held = store.get(utt.id)
        assert held is not None
        assert held.state is State.PAUSED
        assert held.played_ms == 400
    finally:
        task.cancel()


async def test_an_interrupt_holds_the_queue_so_nothing_new_starts(
    store: Store, sink: FakeSink
) -> None:
    first = make_ready(store, "first")
    ctl, task = await controller(store, sink)
    try:
        await wait_for(lambda: ctl.current_id == first.id)
        await ctl.interrupt()
        make_ready(store, "second")
        ctl.notify()
        await asyncio.sleep(0.05)

        # Speech submitted while the listener has the floor spools, silently.
        assert len(sink.started) == 1
    finally:
        task.cancel()


async def test_resume_after_an_interrupt_clears_it_and_does_not_re_hold(
    store: Store, sink: FakeSink
) -> None:
    utt = make_ready(store, "an explanation")
    ctl, task = await controller(store, sink)
    try:
        await wait_for(lambda: ctl.current_id == utt.id)
        await ctl.interrupt()

        await ctl.resume()

        assert is_held(ctl) is False
        assert ctl.interrupted_at is None
        assert is_armed(ctl) is False
        resumed = store.get(utt.id)
        assert resumed is not None
        assert resumed.state is State.PLAYING
    finally:
        task.cancel()


async def test_interrupting_while_already_held_keeps_the_listener_in_charge(
    store: Store, sink: FakeSink
) -> None:
    utt = make_ready(store, "an explanation")
    ctl, task = await controller(store, sink)
    try:
        await wait_for(lambda: ctl.current_id == utt.id)
        await ctl.pause()

        # A hold the listener set by hand is not something an interrupt reports
        # having taken away, and resuming must not be armed behind their back.
        interrupted = await ctl.interrupt()

        assert interrupted is False
        assert ctl.interrupted_at is None
        assert is_held(ctl) is True
    finally:
        task.cancel()


async def test_arming_resume_when_idle_survives_until_the_input_is_released(
    store: Store, sink: FakeSink
) -> None:
    utt = make_ready(store, "an explanation")
    ctl, task = await controller(store, sink)
    try:
        await wait_for(lambda: ctl.current_id == utt.id)
        await ctl.interrupt()

        ctl.arm_resume_when_input_idle()
        assert is_armed(ctl) is True
        assert is_held(ctl) is True

        await ctl.resume()
        assert is_armed(ctl) is False
        assert is_held(ctl) is False
    finally:
        task.cancel()


async def test_skipping_an_interrupted_clip_clears_the_interruption(
    store: Store, sink: FakeSink
) -> None:
    utt = make_ready(store, "an explanation")
    ctl, task = await controller(store, sink)
    try:
        await wait_for(lambda: ctl.current_id == utt.id)
        await ctl.interrupt()

        await ctl.skip()

        assert ctl.interrupted_at is None
        skipped = store.get(utt.id)
        assert skipped is not None
        assert skipped.state is State.SKIPPED
    finally:
        task.cancel()


# -- daemon wiring --------------------------------------------------------


async def make_daemon(
    home: Path, activity: FakeInputActivity, sink: FakeSink
) -> tuple[Daemon, Callable[[], None]]:
    """Start a daemon that watches ``activity`` for the listener's voice."""
    sock_dir = Path(tempfile.mkdtemp(prefix="aitts-input-"))
    daemon = Daemon(
        home=home,
        engine=FakeEngine(voices=["bm_daniel"]),
        sink=sink,
        workers=1,
        socket_path=sock_dir / "d.sock",
        input_activity=activity,
        input_poll_seconds=0.01,
    )
    await daemon.start()
    return daemon, lambda: shutil.rmtree(sock_dir, ignore_errors=True)


async def submit_and_play(daemon: Daemon, text: str) -> str:
    """Submit one clip and wait until it holds the device."""
    reply = await daemon.dispatch({"op": "submit", "text": text})
    utt_id = str(reply["id"])
    await wait_for(lambda: daemon._require_controller().current_id == utt_id)
    return utt_id


async def test_the_daemon_interrupts_playback_when_the_listener_starts_speaking(
    tmp_path: Path, sink: FakeSink
) -> None:
    activity = FakeInputActivity(active=False)
    daemon, cleanup = await make_daemon(tmp_path, activity, sink)
    try:
        await submit_and_play(daemon, "a long explanation")

        activity.active = True

        await wait_for(lambda: daemon._require_controller().interrupted_at is not None)
        status = await daemon.dispatch({"op": "status"})
        assert status["playback_state"] == "paused"
        assert status["interruption"] is not None
        assert status["interruption"]["reason"] == "listener_speaking"
        assert status["input_active"] is True
    finally:
        await daemon.stop()
        cleanup()


async def test_input_that_stays_hot_does_not_re_hold_after_the_listener_resumes(
    tmp_path: Path, sink: FakeSink
) -> None:
    activity = FakeInputActivity(active=False)
    daemon, cleanup = await make_daemon(tmp_path, activity, sink)
    try:
        await submit_and_play(daemon, "a long explanation")
        activity.active = True
        await wait_for(lambda: daemon._require_controller().interrupted_at is not None)

        # Dictation software keeps the device open for minutes. Resume must
        # stick anyway, or the listener can never hear the answer.
        await daemon.dispatch({"op": "resume"})
        await asyncio.sleep(0.1)

        controller = daemon._require_controller()
        assert controller.held is False
        assert controller.interrupted_at is None
    finally:
        await daemon.stop()
        cleanup()


async def test_resume_when_input_idle_waits_for_the_listener_to_finish(
    tmp_path: Path, sink: FakeSink
) -> None:
    activity = FakeInputActivity(active=False)
    daemon, cleanup = await make_daemon(tmp_path, activity, sink)
    try:
        await submit_and_play(daemon, "a long explanation")
        activity.active = True
        await wait_for(lambda: daemon._require_controller().interrupted_at is not None)

        await daemon.dispatch({"op": "resume_when_input_idle"})
        await asyncio.sleep(0.05)
        assert daemon._require_controller().held is True

        activity.active = False

        await wait_for(lambda: daemon._require_controller().held is False)
    finally:
        await daemon.stop()
        cleanup()


async def test_the_interrupt_can_be_turned_off_in_settings(tmp_path: Path, sink: FakeSink) -> None:
    activity = FakeInputActivity(active=False)
    daemon, cleanup = await make_daemon(tmp_path, activity, sink)
    try:
        await daemon.dispatch({"op": "settings", "set": {"input_interrupt_enabled": False}})
        await submit_and_play(daemon, "a long explanation")

        activity.active = True
        await asyncio.sleep(0.1)

        controller = daemon._require_controller()
        assert controller.interrupted_at is None
        assert controller.held is False
    finally:
        await daemon.stop()
        cleanup()


async def test_the_default_resume_policy_is_configurable(tmp_path: Path, sink: FakeSink) -> None:
    activity = FakeInputActivity(active=False)
    daemon, cleanup = await make_daemon(tmp_path, activity, sink)
    try:
        await daemon.dispatch({"op": "settings", "set": {"input_interrupt_resume": "when_idle"}})
        await submit_and_play(daemon, "a long explanation")

        activity.active = True
        await wait_for(lambda: daemon._require_controller().interrupted_at is not None)
        # Configured to resume by itself: no button press should be needed.
        activity.active = False

        await wait_for(lambda: daemon._require_controller().held is False)
    finally:
        await daemon.stop()
        cleanup()


async def test_settings_reject_an_unknown_resume_policy(tmp_path: Path, sink: FakeSink) -> None:
    activity = FakeInputActivity(active=False)
    daemon, cleanup = await make_daemon(tmp_path, activity, sink)
    try:
        with pytest.raises(ApiError):
            await daemon.dispatch({"op": "settings", "set": {"input_interrupt_resume": "whenever"}})
    finally:
        await daemon.stop()
        cleanup()


async def test_an_interrupted_hold_still_explains_itself_after_a_restart(
    store: Store, sink: FakeSink
) -> None:
    utt = make_ready(store, "an explanation")
    ctl, task = await controller(store, sink)
    try:
        await wait_for(lambda: ctl.current_id == utt.id)
        await ctl.interrupt()
        interrupted_at = ctl.interrupted_at
    finally:
        task.cancel()

    # The hold outlives the daemon, so the reason for it has to as well —
    # otherwise the listener comes back to silence with no explanation.
    restored = PlaybackController(store, FakeSink(), DeterministicPlaybackSchedule())

    assert is_held(restored) is True
    assert restored.interrupted_at == interrupted_at
    assert is_armed(restored) is False


async def test_a_hold_the_listener_set_by_hand_explains_nothing_after_a_restart(
    store: Store, sink: FakeSink
) -> None:
    utt = make_ready(store, "an explanation")
    ctl, task = await controller(store, sink)
    try:
        await wait_for(lambda: ctl.current_id == utt.id)
        await ctl.pause()
    finally:
        task.cancel()

    restored = PlaybackController(store, FakeSink(), DeterministicPlaybackSchedule())

    assert is_held(restored) is True
    assert restored.interrupted_at is None


async def test_resuming_forgets_the_interruption_permanently(store: Store, sink: FakeSink) -> None:
    utt = make_ready(store, "an explanation")
    ctl, task = await controller(store, sink)
    try:
        await wait_for(lambda: ctl.current_id == utt.id)
        await ctl.interrupt()
        await ctl.resume()
    finally:
        task.cancel()

    restored = PlaybackController(store, FakeSink(), DeterministicPlaybackSchedule())

    assert restored.interrupted_at is None


# -- a hold taken during a transport step must still be honoured -----------


class GatedSink(FakeSink):
    """A sink whose stop can be held open, to interleave at the release await."""

    def __init__(self) -> None:
        super().__init__()
        self.stopping = asyncio.Event()
        self.release = asyncio.Event()

    async def wait(self) -> bool:
        if self.stopping.is_set():
            await self.release.wait()
        return await super().wait()

    def stop(self) -> None:
        self.stopping.set()
        super().stop()


async def test_an_interrupt_during_a_chunk_step_keeps_playback_held(
    store: Store,
) -> None:
    from tests.test_playback import make_composite_ready  # noqa: PLC0415

    segments = ("one", "two", "three")
    sink = GatedSink()
    make_composite_ready(store, " ".join(segments), segments)
    ctl = PlaybackController(store, sink, DeterministicPlaybackSchedule())
    task = asyncio.get_running_loop().create_task(ctl.run())
    try:
        await wait_for(lambda: ctl.current_segment is not None)

        # Step to the next chunk; the step blocks inside its sink release.
        step = asyncio.get_running_loop().create_task(ctl.next_segment())
        await wait_for(sink.stopping.is_set)

        # The listener starts speaking while the step is mid-flight.
        await ctl.interrupt()
        sink.release.set()
        await step

        # The step must not restart audio through the hold it did not see when
        # it started. Releasing the device is not reversible, so the hold has
        # to be re-checked at the moment audio would begin.
        await asyncio.sleep(0.1)
        assert is_held(ctl) is True
        assert sink.paused is True or not sink_active(ctl)
    finally:
        task.cancel()


async def test_two_chunk_steps_at_once_do_not_wedge_the_document(
    store: Store,
) -> None:
    from tests.test_playback import make_composite_ready  # noqa: PLC0415

    segments = ("one", "two", "three")
    sink = FakeSink()
    parent = make_composite_ready(store, " ".join(segments), segments)
    ctl = PlaybackController(store, sink, DeterministicPlaybackSchedule())
    task = asyncio.get_running_loop().create_task(ctl.run())
    try:
        await wait_for(lambda: ctl.current_segment is not None)

        # Two clients press next at the same time. Both captured chunk 0, so
        # the loser must not settle a chunk the winner already moved past, and
        # must not stop the sink the winner just started.
        first, second = await asyncio.gather(ctl.next_segment(), ctl.next_segment())

        assert [first, second].count(True) >= 1
        await wait_for(lambda: sink_active(ctl))
        held = store.get(parent.id)
        assert held is not None
        assert held.state is State.PLAYING
        assert ctl.current_segment is not None
        assert sink.overlaps == 0
    finally:
        task.cancel()


# -- an explicit Pause supersedes a pending automatic resume ---------------


async def test_a_manual_pause_revokes_an_armed_automatic_resume(
    store: Store, sink: FakeSink
) -> None:
    utt = make_ready(store, "an explanation")
    ctl, task = await controller(store, sink)
    try:
        await wait_for(lambda: ctl.current_id == utt.id)
        await ctl.interrupt()
        ctl.arm_resume_when_input_idle()

        # The listener then decides they want silence regardless, and says so.
        await ctl.pause()

        # Their explicit request is the newer one and must win. Leaving the arm
        # in place meant the next idle input reading released the hold they had
        # just asked for.
        assert is_armed(ctl) is False
        assert is_held(ctl) is True
        assert ctl.interrupted_at is None
    finally:
        task.cancel()


async def test_a_manual_pause_stops_describing_the_hold_as_the_listener_speaking(
    store: Store, sink: FakeSink
) -> None:
    utt = make_ready(store, "an explanation")
    ctl, task = await controller(store, sink)
    try:
        await wait_for(lambda: ctl.current_id == utt.id)
        await ctl.interrupt()
        await ctl.pause()
    finally:
        task.cancel()

    # The reason is durable, so a stale one outlives the daemon and explains
    # the hold wrongly on the next start.
    restored = PlaybackController(store, FakeSink(), DeterministicPlaybackSchedule())
    assert restored.interrupted_at is None


# -- an unavailable reading must not look like a quiet one ----------------


def available(detector: InputInterruptDetector) -> bool:
    # Read through a call so mypy does not narrow the property across polls.
    return detector.reading_available


def test_the_detector_reports_whether_the_reading_is_available() -> None:
    detector = InputInterruptDetector(confirmations=2)
    quiet, unreadable, hot = False, None, True

    # Before anything has been observed the platform has not been asked.
    assert available(detector) is False

    detector.observe(quiet)
    assert available(detector) is True

    detector.observe(unreadable)
    # An unreadable poll means the question cannot be answered right now, and
    # saying "not active" would claim the listener is silent on no evidence.
    assert available(detector) is False

    detector.observe(hot)
    assert available(detector) is True


async def test_status_says_unknown_rather_than_quiet_when_input_cannot_be_read(
    tmp_path: Path, sink: FakeSink
) -> None:
    activity = FakeInputActivity(active=None)
    daemon, cleanup = await make_daemon(tmp_path, activity, sink)
    try:
        await wait_for(lambda: daemon._input_detector.reading_available is False)

        status = await daemon.dispatch({"op": "status"})

        # This is the failure that matters: with the toggle on and the reading
        # broken, the listener believes their microphone takes precedence over
        # playback and it does not. Reporting False here is indistinguishable
        # from a working, quiet microphone.
        assert status["input_active"] is None
    finally:
        await daemon.stop()
        cleanup()


async def test_status_reports_a_readable_quiet_input_as_quiet(
    tmp_path: Path, sink: FakeSink
) -> None:
    activity = FakeInputActivity(active=False)
    daemon, cleanup = await make_daemon(tmp_path, activity, sink)
    try:
        await wait_for(lambda: daemon._input_detector.reading_available is True)

        status = await daemon.dispatch({"op": "status"})

        assert status["input_active"] is False
    finally:
        await daemon.stop()
        cleanup()
