# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Generated text without an ambient Unicode/codec cache."""

from hypothesis import strategies as st


def scalar_text(*, min_size: int = 0, max_size: int) -> st.SearchStrategy[str]:
    """Generate the full Unicode scalar domain, skipping only surrogate code points.

    Default ``st.text`` scans every code point and persists a codec map on a cold
    host. Mapping the two scalar intervals directly avoids that ambient I/O and
    startup cost without restricting Unicode to ASCII or reducing example counts.
    """
    scalar = st.integers(min_value=0, max_value=0x10F7FF).map(
        lambda value: chr(value if value < 0xD800 else value + 0x800)
    )
    return st.lists(scalar, min_size=min_size, max_size=max_size).map("".join)
