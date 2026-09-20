# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Every public method on the store is something a caller actually needs.

The store is the widest class in the project, and every service that holds one
can see all of it. A public method with no caller is worse than unused code:
it is a commitment nobody asked for, and it inflates the port surfaces that
each service is being narrowed down to (see the ISP work).

Two failures are caught here. A method with no caller anywhere in ``src`` is
dead. A method whose only caller is the store itself is an implementation
detail that was left public, which is the same problem wearing a different
hat.

Note the direction of the imprecision: the scan looks for ``.name(`` across
the source, so a method sharing a name with a dict or file method — ``get``,
``close`` — will read as used whether or not the store's own version is. That
weakens the test rather than breaking it: it can miss a dead method, never
invent one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("the store's public surface as its consumers actually use it"),
]

REPOSITORY = Path(__file__).resolve().parents[1]
STORE = REPOSITORY / "src" / "aitts" / "store.py"

# Public methods kept for callers outside this repository's own source. Empty
# on purpose: the store is internal, so anything here needs a stated reason.
KEPT_FOR_EXTERNAL_CALLERS: frozenset[str] = frozenset()


def public_methods() -> set[str]:
    """Every public method defined on ``Store``."""
    source = STORE.read_text(encoding="utf-8")
    body = source[source.index("class Store") :]
    return set(re.findall(r"^    def ([a-z][a-z_0-9]*)", body, re.MULTILINE))


def callers_outside_the_store() -> dict[str, set[str]]:
    """For each method name, which source files call it — excluding the store."""
    found: dict[str, set[str]] = {}
    names = public_methods()
    for path in sorted((REPOSITORY / "src").rglob("*.py")):
        if path == STORE:
            continue
        text = path.read_text(encoding="utf-8")
        for name in names:
            if re.search(rf"\.{re.escape(name)}\s*\(", text):
                found.setdefault(name, set()).add(str(path.relative_to(REPOSITORY)))
    return found


def test_no_public_store_method_is_without_a_caller() -> None:
    methods = public_methods()
    callers = callers_outside_the_store()

    assert methods, "Store should define public methods"
    orphans = sorted(methods - set(callers) - KEPT_FOR_EXTERNAL_CALLERS)

    # A method nobody calls is a promise nobody asked for, and it widens the
    # surface every consumer of the store can see.
    assert orphans == [], (
        f"public Store methods with no caller in src/: {orphans}. "
        "Delete them, or make them private if the store itself needs them."
    )


def test_a_method_only_the_store_uses_is_not_public() -> None:
    source = STORE.read_text(encoding="utf-8")
    methods = public_methods()
    callers = callers_outside_the_store()

    internal_only = sorted(
        name
        for name in methods - set(callers) - KEPT_FOR_EXTERNAL_CALLERS
        if re.search(rf"self\.{re.escape(name)}\s*\(", source)
    )

    # Distinct from the check above: these *are* used, but only from inside the
    # store, so publishing them commits to a contract for no one's benefit.
    assert internal_only == [], (
        f"Store methods used only internally but still public: {internal_only}. "
        "Prefix them with an underscore."
    )
