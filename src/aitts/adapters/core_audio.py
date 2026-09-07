# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""macOS default-output tracking, read from CoreAudio rather than PortAudio.

The identity read here deliberately bypasses PortAudio. PortAudio resolves its
device list when the library initializes and serves every later query from that
snapshot, so a daemon that started before a display was connected cannot see
the display at all — asking PortAudio "what is the default output?" returns the
very answer that is stale. CoreAudio answers from the OS every time, in tens of
microseconds, which is cheap enough to poll between audio blocks.

Refreshing is the other half, and it *is* PortAudio's: tearing the library down
and back up is what rebuilds the snapshot. It costs a few milliseconds and must
never happen while a stream is open.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import struct
import threading

log = logging.getLogger(__name__)

_SYSTEM_OBJECT = 1
_STATUS_OK = 0


def _fourcc(code: str) -> int:
    """Pack a four-character CoreAudio selector into its integer form."""
    return int(struct.unpack(">I", code.encode("ascii"))[0])


_SCOPE_GLOBAL = _fourcc("glob")
_SCOPE_INPUT = _fourcc("inpt")
_DEFAULT_OUTPUT_DEVICE = _fourcc("dOut")
_DEVICE_UID = _fourcc("uid ")
_DEVICES = _fourcc("dev#")
_DEVICE_IS_RUNNING_SOMEWHERE = _fourcc("gone")
_STREAM_CONFIGURATION = _fourcc("slay")

# kCFStringEncodingUTF8
_UTF8 = 0x08000100
_UID_BUFFER_BYTES = 512
# An AudioBufferList with no buffers is this many bytes; anything larger means
# the device really does present input streams.
_EMPTY_BUFFER_LIST_BYTES = 8


class _PropertyAddress(ctypes.Structure):
    """AudioObjectPropertyAddress: selector, scope, element."""

    _fields_ = (
        ("selector", ctypes.c_uint32),
        ("scope", ctypes.c_uint32),
        ("element", ctypes.c_uint32),
    )


class CoreAudioOutputDevice:
    """Report the live default output device and refresh PortAudio's snapshot."""

    def __init__(self) -> None:
        """Bind the system frameworks; a missing framework disables tracking."""
        self._lock = threading.Lock()
        self._core_audio = _load("CoreAudio")
        if self._core_audio is None:  # pragma: no cover - the framework ships with macOS
            log.warning("event=core_audio_unavailable")
        self._core_foundation = _load("CoreFoundation")
        if self._core_foundation is None:  # pragma: no cover - ships with macOS
            log.warning("event=core_foundation_unavailable")
        if self._core_foundation is not None:
            self._core_foundation.CFStringGetCString.argtypes = (
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_long,
                ctypes.c_uint32,
            )
            self._core_foundation.CFStringGetCString.restype = ctypes.c_bool
            self._core_foundation.CFRelease.argtypes = (ctypes.c_void_p,)

    def default_output_identity(self) -> str | None:
        """Return the device UID of the OS default output, or ``None``."""
        if self._core_audio is None:
            return None
        device = self._default_output_device()
        if device is None:
            return None
        uid = self._device_uid(device)
        # The numeric id still distinguishes devices when the UID is unreadable.
        return uid if uid is not None else f"device:{device}"

    def refresh(self) -> None:
        """Rebuild PortAudio's device snapshot so the next stream sees the truth."""
        with self._lock:
            try:
                import sounddevice as sd  # noqa: PLC0415 - keep audio deps off import
            except (ImportError, OSError):  # pragma: no cover - install-time problem
                return
            try:
                sd._terminate()  # noqa: SLF001 - the only way to drop the snapshot
                sd._initialize()  # noqa: SLF001
            except Exception:  # noqa: BLE001 - a refresh failure must not stop audio
                log.warning("event=audio_device_refresh_failed")

    def _default_output_device(self) -> int | None:
        assert self._core_audio is not None  # noqa: S101 - guarded by the caller
        address = _PropertyAddress(_DEFAULT_OUTPUT_DEVICE, _SCOPE_GLOBAL, 0)
        device = ctypes.c_uint32(0)
        size = ctypes.c_uint32(ctypes.sizeof(device))
        status = self._core_audio.AudioObjectGetPropertyData(
            ctypes.c_uint32(_SYSTEM_OBJECT),
            ctypes.byref(address),
            0,
            None,
            ctypes.byref(size),
            ctypes.byref(device),
        )
        if status != _STATUS_OK or device.value == 0:
            return None
        return int(device.value)

    def _device_uid(self, device: int) -> str | None:
        assert self._core_audio is not None  # noqa: S101 - guarded by the caller
        if self._core_foundation is None:  # pragma: no cover - CoreFoundation always present
            return None
        address = _PropertyAddress(_DEVICE_UID, _SCOPE_GLOBAL, 0)
        value = ctypes.c_void_p()
        size = ctypes.c_uint32(ctypes.sizeof(value))
        status = self._core_audio.AudioObjectGetPropertyData(
            ctypes.c_uint32(device),
            ctypes.byref(address),
            0,
            None,
            ctypes.byref(size),
            ctypes.byref(value),
        )
        if status != _STATUS_OK or value.value is None:
            return None
        try:
            buffer = ctypes.create_string_buffer(_UID_BUFFER_BYTES)
            if self._core_foundation.CFStringGetCString(value, buffer, _UID_BUFFER_BYTES, _UTF8):
                return buffer.value.decode("utf-8", errors="replace")
            return None
        finally:
            # AudioObjectGetPropertyData hands back a +1 CFString.
            self._core_foundation.CFRelease(value)


class CoreAudioInputActivity:
    """Report whether any input-capable device is currently capturing.

    The reading is per *device*, not per process, and stays true while any
    process holds the device open — which dictation software does long after a
    recording ends. Callers must treat it as an edge, never as a level; see
    :mod:`aitts.application.input_activity`.
    """

    def __init__(self) -> None:
        """Bind CoreAudio; a missing framework disables input reporting."""
        self._core_audio = _load("CoreAudio")
        if self._core_audio is None:  # pragma: no cover - the framework ships with macOS
            log.warning("event=core_audio_unavailable")

    def input_is_active(self) -> bool | None:
        """Return whether some input device is capturing, or ``None``."""
        if self._core_audio is None:
            return None
        devices = self._devices()
        if devices is None:
            return None
        return any(
            self._has_input_streams(device) and self._is_running_somewhere(device)
            for device in devices
        )

    def _devices(self) -> list[int] | None:
        assert self._core_audio is not None  # noqa: S101 - guarded by the caller
        address = _PropertyAddress(_DEVICES, _SCOPE_GLOBAL, 0)
        size = ctypes.c_uint32(0)
        status = self._core_audio.AudioObjectGetPropertyDataSize(
            ctypes.c_uint32(_SYSTEM_OBJECT), ctypes.byref(address), 0, None, ctypes.byref(size)
        )
        if status != _STATUS_OK or size.value == 0:
            return None
        count = size.value // ctypes.sizeof(ctypes.c_uint32)
        buffer = (ctypes.c_uint32 * count)()
        held = ctypes.c_uint32(size.value)
        status = self._core_audio.AudioObjectGetPropertyData(
            ctypes.c_uint32(_SYSTEM_OBJECT),
            ctypes.byref(address),
            0,
            None,
            ctypes.byref(held),
            buffer,
        )
        if status != _STATUS_OK:  # pragma: no cover - the size query just succeeded
            return None
        return [int(device) for device in buffer]

    def _has_input_streams(self, device: int) -> bool:
        assert self._core_audio is not None  # noqa: S101 - guarded by the caller
        address = _PropertyAddress(_STREAM_CONFIGURATION, _SCOPE_INPUT, 0)
        size = ctypes.c_uint32(0)
        status = self._core_audio.AudioObjectGetPropertyDataSize(
            ctypes.c_uint32(device), ctypes.byref(address), 0, None, ctypes.byref(size)
        )
        return status == _STATUS_OK and size.value > _EMPTY_BUFFER_LIST_BYTES

    def _is_running_somewhere(self, device: int) -> bool:
        assert self._core_audio is not None  # noqa: S101 - guarded by the caller
        address = _PropertyAddress(_DEVICE_IS_RUNNING_SOMEWHERE, _SCOPE_GLOBAL, 0)
        running = ctypes.c_uint32(0)
        size = ctypes.c_uint32(ctypes.sizeof(running))
        status = self._core_audio.AudioObjectGetPropertyData(
            ctypes.c_uint32(device),
            ctypes.byref(address),
            0,
            None,
            ctypes.byref(size),
            ctypes.byref(running),
        )
        return status == _STATUS_OK and running.value != 0


def _load(framework: str) -> ctypes.CDLL | None:
    """Load one system framework, or return ``None`` when it is unavailable.

    Reporting is left to the caller: diagnostics carry static event codes
    only, so the framework's name cannot travel as a log field.
    """
    path = ctypes.util.find_library(framework)
    if path is None:  # pragma: no cover - the frameworks ship with macOS
        return None
    try:
        return ctypes.CDLL(path)
    except OSError:  # pragma: no cover - the frameworks ship with macOS
        return None
