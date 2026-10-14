# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Read Zed task context without passing document text through a shell."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from aitts.adapters.jsonl import MAX_JSONL_LINE_BYTES, encode_json_object
from aitts.client import Client, DaemonError, DaemonUnreachableError
from aitts.paths import default_socket

_MAX_TEXT_BYTES = 512 * 1024


def _input(mode: str) -> tuple[str, str]:
    if mode == "selection":
        text = os.environ.get("ZED_SELECTED_TEXT", "")
        content_format = "plain_text"
    else:
        filename = os.environ.get("ZED_FILE")
        if not filename:
            msg = "Save this document to a file before reading it, or use Read Selection."
            raise ValueError(msg)
        path = Path(filename)
        if not path.is_file():
            msg = "The active document must be an existing regular file."
            raise ValueError(msg)
        with path.open("rb") as stream:
            raw = stream.read(_MAX_TEXT_BYTES + 1)
        if len(raw) > _MAX_TEXT_BYTES:
            msg = "The document exceeds the 512 KiB text limit. Select a smaller passage."
            raise ValueError(msg)
        text = raw.decode("utf-8-sig")
        content_format = "markdown" if path.suffix.lower() in {".md", ".markdown"} else "plain_text"
    if not text.strip():
        msg = "No text to read. Select some text or open a nonempty document."
        raise ValueError(msg)
    if "\x00" in text:
        msg = "Binary documents are not supported. Open a UTF-8 text document."
        raise ValueError(msg)
    if len(text.encode("utf-8")) > _MAX_TEXT_BYTES:
        msg = "The selection exceeds the 512 KiB text limit. Select a smaller passage."
        raise ValueError(msg)
    return text, content_format


def _payload(mode: str) -> dict[str, Any]:
    text, content_format = _input(mode)
    payload = {
        "op": "submit",
        "origin": "CLI",
        "text": text,
        "content_format": content_format,
        "source": f"zed:{mode}",
        "sensitivity": "confidential",
        "priority": "normal",
    }
    if len(encode_json_object(payload)) > MAX_JSONL_LINE_BYTES:
        msg = "The encoded document exceeds the daemon request limit. Select a smaller passage."
        raise ValueError(msg)
    return payload


def main(argv: list[str] | None = None) -> int:
    """Submit the active file or selection supplied by Zed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["file", "selection"])
    args = parser.parse_args(argv)
    try:
        response = Client(default_socket()).request(_payload(args.mode))
    except DaemonUnreachableError:
        sys.stderr.write("AI-TTS daemon is unavailable. Start AI-TTS, then run this task again.\n")
        return 2
    except DaemonError as exc:
        sys.stderr.write(f"AI-TTS refused the document: {exc}\n")
        return 1
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"Cannot read document: {exc}\n")
        return 1
    sys.stdout.write(json.dumps({"queued": True, "id": response["id"]}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
