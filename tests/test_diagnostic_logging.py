# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Bounded, private daemon diagnostic-log contracts."""

from __future__ import annotations

import ast
import logging
import stat
from pathlib import Path
from typing import NoReturn

import pytest

from aitts.adapters.diagnostic_logging import diagnostic_log_handler

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("local diagnostics retention contract in docs/design/architecture.md"),
]


def _raise_private_payload(payload: str) -> NoReturn:
    raise RuntimeError(payload)


def _is_package_diagnostic_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute):
        return False
    receiver = node.func.value
    if isinstance(receiver, ast.Name):
        return receiver.id == "log"
    return (
        isinstance(receiver, ast.Call)
        and isinstance(receiver.func, ast.Attribute)
        and isinstance(receiver.func.value, ast.Name)
        and receiver.func.value.id == "logging"
        and receiver.func.attr == "getLogger"
    )


def test_diagnostic_log_rotates_within_private_owner_only_files(tmp_path: Path) -> None:
    log_directory = tmp_path / "diagnostics"
    log_directory.mkdir(mode=0o777)
    log_path = log_directory / "daemon.log"
    log_path.write_bytes(b"a" * 300)
    backup = Path(f"{log_path}.1")
    backup.write_bytes(b"b" * 300)
    log_directory.chmod(0o777)
    log_path.chmod(0o666)
    backup.chmod(0o666)

    handler = diagnostic_log_handler(log_path, max_bytes=256, backup_count=2)
    assert (log_path.stat().st_size, backup.stat().st_size) == (0, 0)
    logger = logging.getLogger("aitts.contract")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    try:
        for sequence in range(24):
            logger.info("event=contract_probe sequence=%02d", sequence)
    finally:
        handler.flush()
        handler.close()

    artifacts = sorted(log_directory.iterdir())
    assert [path.name for path in artifacts] == ["daemon.log", "daemon.log.1", "daemon.log.2"]
    assert stat.S_IMODE(log_directory.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in artifacts)
    assert all(path.stat().st_size <= 256 for path in artifacts)
    assert "event=contract_probe" in "".join(path.read_text(encoding="utf-8") for path in artifacts)


def test_diagnostic_log_refuses_a_symlink_as_its_active_file(tmp_path: Path) -> None:
    target = tmp_path / "outside.log"
    target.write_text("must remain untouched\n", encoding="utf-8")
    log_directory = tmp_path / "diagnostics"
    log_directory.mkdir()
    log_path = log_directory / "daemon.log"
    log_path.symlink_to(target)

    with pytest.raises(OSError, match="Too many levels of symbolic links"):
        diagnostic_log_handler(log_path, max_bytes=256, backup_count=2)

    assert target.read_text(encoding="utf-8") == "must remain untouched\n"


def test_default_policy_retains_one_two_mebibyte_log_and_two_backups(tmp_path: Path) -> None:
    handler = diagnostic_log_handler(tmp_path / "diagnostics" / "daemon.log")
    try:
        assert (handler.maxBytes, handler.backupCount) == (2 * 1024 * 1024, 2)
    finally:
        handler.close()


def test_diagnostic_log_omits_exception_payloads_and_bounds_one_record(tmp_path: Path) -> None:
    log_path = tmp_path / "diagnostics" / "daemon.log"
    handler = diagnostic_log_handler(log_path, max_bytes=512, backup_count=1)
    logger = logging.getLogger("aitts.exception-contract")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    private_payload = "speech-body-must-not-enter-diagnostics"
    try:
        _raise_private_payload(private_payload)
    except RuntimeError:
        logger.exception("event=contract_failure")
    logger.info("event=oversized_probe detail=%s", "x" * 2_000)
    handler.flush()
    handler.close()

    artifacts = sorted(log_path.parent.iterdir())
    rendered = "".join(path.read_text(encoding="utf-8") for path in artifacts)
    assert "event=contract_failure" in rendered
    assert private_payload not in rendered
    assert "Traceback" not in rendered
    assert all(path.stat().st_size <= 512 for path in artifacts)


def test_package_diagnostics_use_static_events_and_safe_dynamic_fields() -> None:
    source_root = Path(__file__).parents[1] / "src" / "aitts"
    allowed_dynamic_fields = {
        "__version__",
        "delay",
        "engine.name",
        "report.after_bytes",
        "report.max_bytes",
        # A short token derived from the utterance's random identifier. It is
        # what makes one clip followable across submit, synthesis and
        # playback, and it can carry no speech, source label or path.
        "utterance_trace(utt.id)",
        "utterance_trace(work.utterance_id)",
        "utterance_trace(utt_id)",
        "utterance_trace(self._current_id)",
    }
    violations: list[str] = []
    observed = 0
    for source_path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_package_diagnostic_call(node):
                continue
            observed += 1
            relative = source_path.relative_to(source_root)
            location = f"{relative}:{node.lineno}"
            if not node.args or not isinstance(node.args[0], ast.Constant):
                violations.append(f"{location}: diagnostic template must be a string literal")
                continue
            template = node.args[0].value
            if not isinstance(template, str) or not template.startswith("event="):
                violations.append(f"{location}: diagnostic template needs a stable event code")
            dynamic_fields = {ast.unparse(argument) for argument in node.args[1:]}
            unsafe_fields = sorted(dynamic_fields - allowed_dynamic_fields)
            if unsafe_fields:
                violations.append(f"{location}: unsafe dynamic fields {unsafe_fields}")
            unsafe_keywords = sorted(
                keyword.arg or "**kwargs"
                for keyword in node.keywords
                if keyword.arg in {"exc_info", "stack_info"} or keyword.arg is None
            )
            if unsafe_keywords:
                violations.append(f"{location}: unsafe diagnostic keywords {unsafe_keywords}")

    assert observed >= 10
    assert violations == []
