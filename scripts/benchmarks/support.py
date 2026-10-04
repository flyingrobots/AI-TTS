# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Load playback support from the measured checkout, including historical layouts."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType


def helper_sources(root: Path) -> tuple[str, ...]:
    """Name all local support modules used by the selected checkout's layout."""
    if (root / "tests/support/playback.py").is_file():
        return ("tests/__init__.py", "tests/support/__init__.py", "tests/support/playback.py")
    return ("tests/__init__.py", "tests/conftest.py", "tests/test_playback.py")


def playback_helpers() -> ModuleType:
    """Resolve helpers beside the imported application, refusing mixed test packages."""
    import aitts  # noqa: PLC0415 - CLI selects the application before helper loading

    root = Path(aitts.__file__).resolve().parents[2]
    package_root = root / "tests"
    for name, module in tuple(sys.modules.items()):
        if name == "tests" or name.startswith("tests."):
            filename = getattr(module, "__file__", None)
            if filename is None or not Path(filename).resolve().is_relative_to(package_root):
                message = "benchmark test support was already loaded from another checkout"
                raise RuntimeError(message)
    if "tests" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "tests", package_root / "__init__.py", submodule_search_locations=[str(package_root)]
        )
        if spec is None or spec.loader is None:
            message = "selected source has no loadable test-support package"
            raise RuntimeError(message)
        package = importlib.util.module_from_spec(spec)
        sys.modules["tests"] = package
        spec.loader.exec_module(package)
    sources = helper_sources(root)
    name = (
        "tests.support.playback"
        if sources[-1].endswith("support/playback.py")
        else "tests.test_playback"
    )
    module = importlib.import_module(name)
    if module.__file__ is None or Path(module.__file__).resolve() != root / sources[-1]:
        message = "selected playback helper resolved outside its declared source"
        raise RuntimeError(message)
    return module
