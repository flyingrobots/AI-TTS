# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Select concrete OS audio adapters outside application policy."""

from __future__ import annotations

from aitts.application.audio_device import AudioDevicePort, NullAudioDevice
from aitts.application.input_activity import InputActivityPort, NullInputActivity


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


def platform_input_activity() -> InputActivityPort:
    """Return the best available input-activity port for this platform."""
    import platform  # noqa: PLC0415 - resolved once, at daemon construction

    if platform.system() == "Darwin":
        from aitts.adapters.core_audio import (  # noqa: PLC0415 - macOS-only adapter
            CoreAudioInputActivity,
        )

        return CoreAudioInputActivity()
    return NullInputActivity()
