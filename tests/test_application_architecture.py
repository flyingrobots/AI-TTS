# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Enforce inward static dependencies at the Python application boundary."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "application ports and policy depend inward, never on concrete adapters or composition; "
        "docs/design/architecture.md section 4"
    ),
]


def test_application_static_imports_stay_inside_the_core() -> None:
    """Harvest all static imports, including local and TYPE_CHECKING branches."""
    root = Path(__file__).parents[1] / "src" / "aitts" / "application"
    files = sorted(root.rglob("*.py"))
    violations: list[str] = []
    imports_seen = 0
    for path in files:
        package = "aitts.application"
        if path.parent != root:
            package += "." + ".".join(path.parent.relative_to(root).parts)
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    module = resolve_name("." * node.level + module, package)
                names = [f"{module}.{alias.name}" for alias in node.names]
            else:
                continue
            imports_seen += len(names)
            for name in names:
                if not (name == "aitts" or name.startswith("aitts.")):
                    continue
                if any(
                    name == allowed or name.startswith(allowed + ".")
                    for allowed in ("aitts.application", "aitts.model")
                ):
                    continue
                violations.append(f"{path.relative_to(root)}:{node.lineno}: {name}")

    assert files, "no application source witnesses found"
    assert imports_seen, "no application import witnesses found"
    assert not violations, "outward application dependencies:\n" + "\n".join(violations)
