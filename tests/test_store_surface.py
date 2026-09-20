# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Every public method on the store is something a caller actually needs.

The store is the widest class in the project, and every service that holds one
can see all of it. A public method with no caller is worse than unused code:
it is a commitment nobody asked for, and it inflates the port surfaces that
each service is being narrowed down to (see the ISP work).

One gate classifies two kinds of unused public API. A method with no caller anywhere in ``src`` is
dead. A method whose only caller is the store itself is an implementation
detail that was left public, which is the same problem wearing a different
hat.

Method-name references include saved bound methods and callback arguments.
This is not type resolution: another object's same-named method can hide an
unused Store method. Dynamic attribute lookup is outside the scan; justified
exceptions belong in KEPT_FOR_EXTERNAL_CALLERS.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("the store's public surface as its consumers actually use it"),
]

REPOSITORY = Path(__file__).resolve().parents[1]
STORE = REPOSITORY / "src" / "aitts" / "store.py"

# Public methods kept for external or dynamic callers the scan cannot see.
# Every exception requires a concrete call-site explanation.
KEPT_FOR_EXTERNAL_CALLERS: frozenset[str] = frozenset()


def public_methods() -> set[str]:
    """Every public method defined on ``Store``."""
    source = STORE.read_text(encoding="utf-8")
    module = ast.parse(source)
    store = next(
        node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "Store"
    )
    return {
        node.name
        for node in store.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }


def callers_outside_the_store() -> dict[str, set[str]]:
    """For each method name, which source files call it — excluding the store."""
    found: dict[str, set[str]] = {}
    names = public_methods()
    for path in sorted((REPOSITORY / "src").rglob("*.py")):
        if path == STORE:
            continue
        text = path.read_text(encoding="utf-8")
        for name in names:
            if re.search(rf"\.{re.escape(name)}\b", text):
                found.setdefault(name, set()).add(str(path.relative_to(REPOSITORY)))
    return found


def test_no_public_store_method_is_without_a_caller() -> None:
    methods = public_methods()
    callers = callers_outside_the_store()

    assert methods, "Store should define public methods"
    orphans = sorted(methods - set(callers) - KEPT_FOR_EXTERNAL_CALLERS)

    source = STORE.read_text(encoding="utf-8")
    internal_only = {
        name for name in orphans if re.search(rf"self\.{re.escape(name)}\s*\(", source)
    }
    unused = sorted(set(orphans) - internal_only)
    assert orphans == [], (
        f"public Store methods without an external caller; unused: {unused}; "
        f"internal-only: {sorted(internal_only)}. "
        "Delete unused methods or make internal helpers private."
    )
