# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0
# ruff: noqa: INP001 - a standalone fixture script, not a package module
"""Fake model worker: speaks protocol 2 with a scripted behavior read from ROOT/mode."""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import BinaryIO


def say(payload: dict[str, object]) -> None:
    """Write one JSON control line."""
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def frame(audio: BinaryIO, payload: bytes) -> None:
    """Write one length-prefixed audio frame."""
    audio.write(len(payload).to_bytes(4, "big") + payload)
    audio.flush()


def stream(audio: BinaryIO, root: Path, mode: list[str], pcm: bytes) -> None:
    """Answer one stream request as `mode` scripts."""
    if mode[0] == "golden":
        frame(audio, pcm[:4])
        frame(audio, pcm[4:])
        frame(audio, b"")
        say({"ok": True})
    elif mode[0] == "wrong_pipe":
        sys.stdout.buffer.write(len(pcm).to_bytes(4, "big") + pcm)
        sys.stdout.flush()
        frame(audio, b"")
        say({"ok": True})
    elif mode[0] == "hang":
        child = subprocess.Popen(["/bin/sleep", "30"])
        (root / "child.pid").write_text(str(child.pid))
        time.sleep(30)
    elif mode[0] == "random":
        rng = random.Random(int(mode[1]))  # noqa: S311 - seeded test schedule, not security
        exit_at = rng.randrange(len(pcm) + 4) if mode[2] == "exit" else None
        sent = 0
        while sent < len(pcm):
            size = 2 * rng.randrange(1, 5)  # PCM frames hold whole samples.
            if exit_at is not None and sent + size > exit_at:
                os._exit(4)
            frame(audio, pcm[sent : sent + size])
            sent += size
        if exit_at is not None:
            os._exit(4)
        frame(audio, b"")
        say({"ok": True})


def main() -> None:
    """Serve requests in the argument shape of `python -m aitts.model_worker serve`."""
    _, dash_m, module, op, name, directory, fd = sys.argv
    if (dash_m, module, op) != ("-m", "aitts.model_worker", "serve"):
        raise SystemExit(2)
    root = Path(directory)
    mode = (root / "mode").read_text().split()
    if mode[0] == "exit_at_start":
        raise SystemExit(3)
    with os.fdopen(int(fd), "wb") as audio:
        say({"protocol": 1 if mode[0] == "old_protocol" else 2})
        with (root / "started").open("a") as started:
            started.write(name + "\n")
        for line in sys.stdin:
            request = json.loads(line)
            if request["op"] == "warmup":
                say({"ok": True})
            else:
                # Known stream: each text byte becomes one 16-bit sample.
                stream(audio, root, mode, request["text"].encode() * 2)


main()
