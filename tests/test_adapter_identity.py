# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Content identity vectors and generated metadata/bytecode invariance."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from hypothesis import event, given
from hypothesis import strategies as st

from aitts.adapter_identity import adapter_sha256

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle(
        "aitts-adapter-v1 canonical framed content; bytecode and file metadata excluded"
    ),
]


def write_package(
    root: Path, files: dict[str, bytes], *, timestamp: int = 1, mode: int = 0o600
) -> None:
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (timestamp, timestamp))
        path.chmod(mode)


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"a.py": b"x\n"}, "865b276b5bab6654b3c838abe467bdc7d9fc220621a79e995e4c78b8596500e7"),
        (
            {"a.py": b"x\n", "nested/data.txt": b"\x00\xff"},
            "0eed398fa2efe70c52aeee0d90db9e9f55021a0b825bd30ec059f3ae0f7b73b7",
        ),
        (
            {"renamed.py": b"x\n"},
            "c821349717e7331b3883d37fc5acc18bfcfe9050cf63bd9f11c4843cc8a07b97",
        ),
    ],
)
def test_adapter_identity_matches_independent_framed_vectors(
    tmp_path: Path, files: dict[str, bytes], expected: str
) -> None:
    write_package(tmp_path, files)
    assert adapter_sha256(tmp_path) == expected


@given(
    st.dictionaries(
        st.sampled_from(["a.py", "nested/b.py", "data.txt"]), st.binary(max_size=64), min_size=1
    )
)
def test_adapter_identity_ignores_creation_order_and_bytecode(files: dict[str, bytes]) -> None:
    event(f"file count: {len(files)}")
    event(
        "empty content present" if any(not data for data in files.values()) else "nonempty content"
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        first, second = root / "first", root / "second"
        write_package(first, files)
        write_package(second, dict(reversed(tuple(files.items()))), timestamp=2, mode=0o644)
        write_package(second, {"__pycache__/a.pyc": b"cache", "nested/b.pyc": b"cache"})
        assert len(files) >= 1
        assert adapter_sha256(first) == adapter_sha256(second)
