# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Bounded, owner-only local diagnostic logging for the daemon."""

from __future__ import annotations

import logging
import os
from copy import copy
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, cast

from aitts.adapters.private_files import (
    PRIVATE_FILE_MODE,
    ensure_private_directory,
    secure_existing_file,
)

if TYPE_CHECKING:
    from io import TextIOWrapper

DEFAULT_DIAGNOSTIC_LOG_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_DIAGNOSTIC_LOG_BACKUP_COUNT = 2
DIAGNOSTIC_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_MINIMUM_MAX_BYTES = 256


class _BoundedDiagnosticFormatter(logging.Formatter):
    """Omit exception payloads and cap any one rendered diagnostic record."""

    def __init__(self, *, max_record_bytes: int) -> None:
        super().__init__(fmt=DIAGNOSTIC_LOG_FORMAT)
        self._max_record_bytes = max_record_bytes

    def format(self, record: logging.LogRecord) -> str:
        safe_record = copy(record)
        safe_record.exc_info = None
        safe_record.exc_text = None
        safe_record.stack_info = None
        rendered = super().format(safe_record)
        encoded = rendered.encode("utf-8")
        if len(encoded) <= self._max_record_bytes:
            return rendered
        suffix = b" [truncated]"
        prefix = encoded[: self._max_record_bytes - len(suffix)]
        return prefix.decode("utf-8", errors="ignore") + suffix.decode()


class _PrivateRotatingFileHandler(RotatingFileHandler):
    """Open every active log generation without following links or trusting umask."""

    def _open(self) -> TextIOWrapper:
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC | os.O_NOFOLLOW
        descriptor = os.open(self.baseFilename, flags, PRIVATE_FILE_MODE)
        try:
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
            return cast(
                "TextIOWrapper",
                os.fdopen(
                    descriptor,
                    self.mode,
                    encoding=self.encoding,
                    errors=self.errors,
                ),
            )
        except BaseException:
            os.close(descriptor)
            raise


def _bound_existing_generation(path: Path, *, max_bytes: int) -> None:
    if not secure_existing_file(path):
        return
    descriptor = os.open(path, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        if os.fstat(descriptor).st_size > max_bytes:
            os.ftruncate(descriptor, 0)
    finally:
        os.close(descriptor)


def diagnostic_log_handler(
    path: Path,
    *,
    max_bytes: int = DEFAULT_DIAGNOSTIC_LOG_MAX_BYTES,
    backup_count: int = DEFAULT_DIAGNOSTIC_LOG_BACKUP_COUNT,
) -> RotatingFileHandler:
    """Build one bounded handler after securing its directory and generations."""
    if not path.is_absolute():
        msg = f"diagnostic log path must be absolute: {path}"
        raise ValueError(msg)
    if max_bytes < _MINIMUM_MAX_BYTES:
        msg = f"diagnostic log max_bytes must be at least {_MINIMUM_MAX_BYTES}"
        raise ValueError(msg)
    if backup_count <= 0:
        msg = "diagnostic log backup_count must be positive"
        raise ValueError(msg)

    ensure_private_directory(path.parent)
    for generation in range(backup_count + 1):
        candidate = path if generation == 0 else Path(f"{path}.{generation}")
        _bound_existing_generation(candidate, max_bytes=max_bytes)

    handler = _PrivateRotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(_BoundedDiagnosticFormatter(max_record_bytes=max_bytes // 2))
    return handler


def configure_daemon_logging(path: Path) -> None:
    """Route AI-TTS diagnostics to one bounded private handler."""
    handler = diagnostic_log_handler(path)
    logger = logging.getLogger("aitts")
    for existing in tuple(logger.handlers):
        logger.removeHandler(existing)
        existing.close()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
