# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Outbound and transport adapters around application ports."""

from aitts.adapters.filesystem_cache import FileAudioCache
from aitts.adapters.unix_socket import UnixSocketSpeechAdapter

__all__ = ["FileAudioCache", "UnixSocketSpeechAdapter"]
