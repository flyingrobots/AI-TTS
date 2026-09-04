# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Operating-system adapter for bounded daemon process termination."""

from __future__ import annotations

import os
from typing import Never


class ImmediateProcessTerminator:
    """Exit after graceful application shutdown without joining engine threads."""

    def terminate(self, status: int) -> Never:
        """End this process immediately with ``status``."""
        os._exit(status)
