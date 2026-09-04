# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Transport adapters around the public speech application port."""

from aitts.adapters.unix_socket import UnixSocketSpeechAdapter

__all__ = ["UnixSocketSpeechAdapter"]
