# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Calibrate the Store API gate against controlled source examples.

Retire cases when the corresponding gate is removed or stronger analysis
subsumes the failure they reproduce.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests import test_store_surface as surface

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "PR #24 review: Store API checks must report honest source and resource facts"
    ),
]


def test_repository_gate_is_selected_in_the_medium_tier() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_store_surface.py",
            "--collect-only",
            "-m",
            "medium",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def source_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = tmp_path / "src"
    source.mkdir()
    store = source / "store.py"
    store.write_text("class Store:\n    def send(self): pass\n", encoding="utf-8")
    monkeypatch.setattr(surface, "REPOSITORY", tmp_path)
    monkeypatch.setattr(surface, "STORE", store)
    return source


@pytest.mark.parametrize(
    "unrelated",
    [
        "\nclass Helper:\n    def unrelated(self): pass\n",
        "\ndef factory():\n    def unrelated(): pass\n",
    ],
)
def test_discovery_excludes_definitions_outside_store(source_tree: Path, unrelated: str) -> None:
    store = source_tree / "store.py"
    store.write_text(store.read_text(encoding="utf-8") + unrelated, encoding="utf-8")

    assert surface.public_methods() == {"send"}


@pytest.mark.parametrize("reference", ["register(store.send)", "callback = store.send\ncallback()"])
def test_bound_method_references_count_as_uses(source_tree: Path, reference: str) -> None:
    (source_tree / "client.py").write_text(reference, encoding="utf-8")

    surface.test_no_public_store_method_is_without_a_caller()


def test_empty_discovery_is_rejected(source_tree: Path) -> None:
    (source_tree / "store.py").write_text("class Store:\n    pass\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="Store should define public methods"):
        surface.test_no_public_store_method_is_without_a_caller()


def test_single_gate_identifies_internal_only_methods(source_tree: Path) -> None:
    (source_tree / "store.py").write_text(
        "class Store:\n    def send(self): pass\n    def _work(self): self.send()\n",
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match=r"internal-only:.*send"):
        surface.test_no_public_store_method_is_without_a_caller()


def test_async_methods_cannot_escape_the_gate(source_tree: Path) -> None:
    (source_tree / "store.py").write_text(
        "class Store:\n    def send(self): pass\n    async def fetch(self): pass\n",
        encoding="utf-8",
    )
    (source_tree / "client.py").write_text("store.send()", encoding="utf-8")

    with pytest.raises(AssertionError, match=r"unused:.*fetch"):
        surface.test_no_public_store_method_is_without_a_caller()
