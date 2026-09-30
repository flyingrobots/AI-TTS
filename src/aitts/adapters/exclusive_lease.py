# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Process-lifetime leases for private daemon state and Unix socket ownership."""

from __future__ import annotations

import fcntl
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class ExclusiveFileLease:
    """Keep a stable lock file; unlinking it would let competing owners bypass it."""

    def __init__(self, path: Path) -> None:
        """Prepare a lease without taking ownership."""
        self._path = path
        self._descriptor: int | None = None

    @property
    def held(self) -> bool:
        """Whether this instance owns the lease."""
        return self._descriptor is not None

    def acquire(self) -> None:
        """Refuse competing owners rather than modifying their resources."""
        if self.held:
            message = "resource is already owned by this instance"
            raise RuntimeError(message)
        descriptor = os.open(self._path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            message = "resource is already owned by another daemon"
            raise RuntimeError(message) from exc
        except BaseException:
            os.close(descriptor)
            raise
        self._descriptor = descriptor

    def release(self) -> None:
        """Release ownership without removing the shared lock-file identity."""
        if self._descriptor is not None:
            os.close(self._descriptor)
            self._descriptor = None
