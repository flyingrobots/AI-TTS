# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Audio input activity as a port, so the listener's voice can take the floor.

The listener dictates to their agents and expects the reply spoken back. That
only works as a conversation if their own voice outranks the queue: speech
already playing has to stop when they start talking, and stay stopped.

What the platform can tell us is coarser than the question we want to ask. It
reports whether *some* process is capturing audio, not whether the listener is
speaking, and dictation software holds the device open for minutes after a
recording to make the next one start instantly. Treating that reading as a
level — hold while hot — would fight the listener: they resume, the still-hot
reading re-holds, they resume again. :class:`InputInterruptDetector` therefore
reduces the reading to its cold-to-hot *edge*, which is the moment the floor
actually changed hands.
"""

from __future__ import annotations

from typing import Protocol

DEFAULT_CONFIRMATIONS = 2


class InputActivityPort(Protocol):
    """Whether any audio input on this machine is currently capturing."""

    def input_is_active(self) -> bool | None:
        """Return capture state, or ``None`` when the platform cannot be asked.

        ``None`` is not "cold": reading it as cold would let the next hot
        reading fire an interrupt the listener never triggered.
        """
        ...


class NullInputActivity:
    """An activity port for platforms with no input-state reporting."""

    def input_is_active(self) -> bool | None:
        """Report an unknown state, which never becomes an edge."""
        return None


class FakeInputActivity:
    """An activity port for tests: a settable capture state."""

    def __init__(self, *, active: bool | None = False) -> None:
        """Create a port reporting ``active`` until a test changes it."""
        self.active = active

    def input_is_active(self) -> bool | None:
        """Return the currently configured state."""
        return self.active


class InputInterruptDetector:
    """Reduce a sticky "input is capturing" reading to one interrupt per spell."""

    def __init__(self, *, confirmations: int = DEFAULT_CONFIRMATIONS) -> None:
        """Require ``confirmations`` consecutive hot readings before firing."""
        if confirmations < 1:
            msg = "confirmations must be at least 1"
            raise ValueError(msg)
        self._confirmations = confirmations
        # None until the first readable observation: an input already capturing
        # when the daemon starts is somebody else's, not a change of floor.
        self._hot: bool | None = None
        self._streak = 0
        # Whether the most recent poll could be answered at all. An
        # unanswerable poll is not "quiet": reporting quiet would tell the
        # listener their voice takes precedence when nothing is watching.
        self._readable = False

    @property
    def reading_available(self) -> bool:
        """Whether the platform answered the most recent poll."""
        return self._readable

    @property
    def input_is_hot(self) -> bool:
        """Whether the last readable observation was a confirmed capture."""
        return self._hot is True

    def observe(self, active: bool | None, /) -> bool:  # noqa: FBT001 - one tri-state reading
        """Feed one reading; return True only on a genuine cold-to-hot edge."""
        self._readable = active is not None
        if active is None:
            return False
        if not active:
            self._hot = False
            self._streak = 0
            return False
        self._streak = min(self._streak + 1, self._confirmations)
        if self._streak < self._confirmations:
            return False
        was_cold = self._hot is False
        self._hot = True
        return was_cold


def platform_input_activity() -> InputActivityPort:
    """Return the best available input-activity port for this platform."""
    import platform  # noqa: PLC0415 - resolved once, at daemon construction

    if platform.system() == "Darwin":
        from aitts.adapters.core_audio import (  # noqa: PLC0415 - macOS-only adapter
            CoreAudioInputActivity,
        )

        return CoreAudioInputActivity()
    return NullInputActivity()
