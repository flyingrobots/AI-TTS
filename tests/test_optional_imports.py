# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Every optional third-party import is known to the type checker.

CI type-checks with development dependencies only. A developer works in an
``--all-extras`` environment, so a module that arrives through an extra —
or transitively through one, as ``huggingface_hub`` does through ``kokoro`` —
resolves locally and is missing in CI. The failure surfaces nowhere until a
push, and it says nothing about the code that caused it.

This pins the two lists against each other: anything imported inside a
function body, from a package that is not a declared runtime dependency, must
appear in the mypy override list. The first time this mattered it cost a red
CI run on a first public push.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("the mypy configuration in pyproject.toml"),
]

REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY / "src"

# Modules in the standard library or this project, which need no override.
_LOCAL_PREFIXES = ("aitts", "tests")


def project() -> dict[str, object]:
    """The parsed packaging and tool configuration."""
    with (REPOSITORY / "pyproject.toml").open("rb") as stream:
        loaded = tomllib.load(stream)
    assert isinstance(loaded, dict)
    return loaded


def declared_overrides() -> set[str]:
    """Modules mypy is told may lack type information."""
    config = project()
    tool = config.get("tool")
    assert isinstance(tool, dict)
    mypy = tool.get("mypy")
    assert isinstance(mypy, dict)
    found: set[str] = set()
    for override in mypy.get("overrides", []):
        assert isinstance(override, dict)
        if not override.get("ignore_missing_imports"):
            continue
        modules = override.get("module")
        entries = modules if isinstance(modules, list) else [modules]
        found.update(str(entry).removesuffix(".*") for entry in entries)
    return found


def lazily_imported_packages() -> dict[str, str]:
    """Top-level packages imported inside a function body, to where."""
    found: dict[str, str] = {}
    for path in sorted(SOURCE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                names: list[str] = []
                if isinstance(inner, ast.Import):
                    names = [alias.name for alias in inner.names]
                elif isinstance(inner, ast.ImportFrom) and inner.level == 0:
                    names = [inner.module or ""]
                for name in names:
                    top = name.split(".")[0]
                    if top and not top.startswith(_LOCAL_PREFIXES):
                        found.setdefault(top, f"{path.relative_to(REPOSITORY)}")
    return found


def test_every_lazy_third_party_import_is_known_to_mypy() -> None:
    overrides = declared_overrides()
    imports = lazily_imported_packages()

    assert imports, "the source should import something lazily"
    # A module mypy can resolve from the standard library needs no override;
    # anything else must be declared, or CI's dev-only checkout cannot see it.
    unknown = {
        module: where
        for module, where in imports.items()
        if module not in overrides and not _resolvable_without_extras(module)
    }

    assert unknown == {}, (
        "these are imported lazily but absent from tool.mypy.overrides, so "
        f"mypy fails wherever the extras are not installed: {unknown}"
    )


def test_the_override_list_names_nothing_the_source_stopped_importing() -> None:
    overrides = declared_overrides()
    imports = set(lazily_imported_packages())
    eagerly = _eagerly_imported_packages()

    stale = sorted(overrides - imports - eagerly)

    # An override for a module nobody imports is a licence for a future import
    # to skip review, which is how the list stopped being complete before.
    assert stale == [], f"tool.mypy.overrides names unimported modules: {stale}"


def _eagerly_imported_packages() -> set[str]:
    """Top-level packages imported at module scope across the source."""
    found: set[str] = set()
    for path in sorted(SOURCE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return {name for name in found if not name.startswith(_LOCAL_PREFIXES)}


def _resolvable_without_extras(module: str) -> bool:
    """Whether mypy can type this module with development dependencies only."""
    import sys  # noqa: PLC0415 - only needed for this check

    if module in sys.stdlib_module_names:
        return True
    # Declared runtime dependencies are installed in every environment, so
    # mypy resolves them (or their stubs) without help.
    config = project()
    project_table = config.get("project")
    assert isinstance(project_table, dict)
    declared = {_requirement_name(entry) for entry in project_table.get("dependencies", []) or []}
    return module.replace("_", "-") in declared


def _requirement_name(requirement: object) -> str:
    """The bare distribution name from a PEP 508 requirement string."""
    text = str(requirement)
    for separator in (">=", "<=", "==", "!=", "~=", ">", "<", "[", ";", " "):
        text = text.split(separator, 1)[0]
    return text.strip().lower()
