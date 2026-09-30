# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Bound HTTP chunk metadata in the optional model-download dependency graph."""

import http.client
import io

import pytest
from urllib3.exceptions import ProtocolError
from urllib3.response import HTTPResponse

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle(
        "GHSA-vxq7-64xx-v4gw: streamed chunk-size lines above 65536 bytes are rejected"
    ),
]


@pytest.mark.parametrize("line_bytes", [65536, 65537])
def test_streaming_bounds_chunk_size_metadata(line_bytes: int) -> None:
    # Retire when urllib3 leaves the frozen graph or equivalent calibrated
    # dependency conformance covers this bound. No socket, thread, or network.
    wire = (
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
        + b"0" * (line_bytes - 2)
        + b"\r\n\r\n"
    )

    class MemorySocket:
        def makefile(self, mode: str) -> io.BytesIO:
            del mode
            return io.BytesIO(wire)

    # The standard-library parser needs only makefile from this owned double.
    raw = http.client.HTTPResponse(MemorySocket(), method="GET")  # type: ignore[arg-type]
    raw.begin()
    response = HTTPResponse(
        body=raw,
        headers=dict(raw.getheaders()),
        original_response=raw,
        preload_content=False,
        request_method="GET",
    )
    try:
        if line_bytes > 65536:
            with pytest.raises(ProtocolError, match="chunk size line exceeded"):
                list(response.stream())
        else:
            assert list(response.stream()) == []
    finally:
        response.close()
