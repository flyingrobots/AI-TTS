# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Application port for the daemon process's final lifecycle boundary."""

from __future__ import annotations

from typing import Never, Protocol


class ProcessTerminationPort(Protocol):
    """End the daemon process after its durable resources are closed."""

    def terminate(self, status: int) -> Never:
        """Exit immediately without waiting for non-cooperative runtime finalizers."""
        ...
