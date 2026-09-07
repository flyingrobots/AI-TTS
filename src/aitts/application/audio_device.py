# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The audio output device as a port, so playback can follow the system default.

Architecture §4 gives the playback controller sole ownership of the audio
device. §10 item 3 deferred *which* device that is, assuming one. That
assumption fails the moment a listener connects a display with speakers: the
audio library's device enumeration is resolved once, at initialization, and a
long-lived daemon keeps playing to a device the listener has already left.

Two distinct capabilities settle it, and they are deliberately separate
because on macOS they come from different libraries:

* reading which device the OS considers default, *live* — cheap, and never
  served from the audio library's cache, because that cache is the defect;
* discarding that cache, so the next stream opens on the current default.
"""

from __future__ import annotations

from typing import Protocol


class AudioDevicePort(Protocol):
    """The system's default audio output, readable live and refreshable."""

    def default_output_identity(self) -> str | None:
        """Return a stable identity for the OS default output, read from the OS.

        The value is opaque and compared only for equality. ``None`` means the
        platform could not be asked, which callers must treat as "unchanged"
        rather than as a device change.
        """
        ...

    def refresh(self) -> None:
        """Discard any cached device enumeration.

        Called only while no stream is open: re-initializing the audio library
        invalidates every live stream.
        """
        ...


class NullAudioDevice:
    """A device port for platforms with no default-output tracking.

    Playback still works; it simply cannot follow a device change, which is
    the pre-existing behaviour on any platform without an implementation.
    """

    def __init__(self) -> None:
        """Create a port that reports nothing and caches nothing."""
        self.refreshes = 0

    def default_output_identity(self) -> str | None:
        """Report an unknown device, which never compares as changed."""
        return None

    def refresh(self) -> None:
        """Count the request; there is no cache to discard."""
        self.refreshes += 1


class FakeAudioDevice:
    """A device port for tests: settable identity, counted refreshes."""

    def __init__(self, identity: str | None = "fake-output") -> None:
        """Create a port that reports ``identity`` until a test changes it."""
        self.identity = identity
        self.refreshes = 0

    def default_output_identity(self) -> str | None:
        """Return the currently configured identity."""
        return self.identity

    def refresh(self) -> None:
        """Record that the cached enumeration would have been discarded."""
        self.refreshes += 1


def platform_audio_device() -> AudioDevicePort:
    """Return the best available device port for this platform.

    Dispatched on ``platform.system()`` rather than ``sys.platform`` so the
    non-macOS branch stays analysable on a macOS checkout.
    """
    import platform  # noqa: PLC0415 - resolved once, at sink construction

    if platform.system() == "Darwin":
        from aitts.adapters.core_audio import (  # noqa: PLC0415 - macOS-only adapter
            CoreAudioOutputDevice,
        )

        return CoreAudioOutputDevice()
    return NullAudioDevice()
