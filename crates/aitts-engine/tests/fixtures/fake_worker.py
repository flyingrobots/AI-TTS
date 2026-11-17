# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0
"""Fake model worker: speaks protocol 2 with a scripted behavior read from ROOT/mode."""

import json
import os
import random
import subprocess
import sys
import time

# Argument shape of `python -m aitts.model_worker serve NAME ROOT FD`.
_, dash_m, module, op, name, root, fd = sys.argv
assert (dash_m, module, op) == ("-m", "aitts.model_worker", "serve"), sys.argv
mode = open(os.path.join(root, "mode")).read().split()
audio = os.fdopen(int(fd), "wb")
wire = sys.stdout


def say(payload):
    wire.write(json.dumps(payload) + "\n")
    wire.flush()


def frame(payload):
    audio.write(len(payload).to_bytes(4, "big") + payload)
    audio.flush()


if mode[0] == "exit_at_start":
    sys.exit(3)
say({"protocol": 1 if mode[0] == "old_protocol" else 2})
open(os.path.join(root, "started"), "a").write(name + "\n")
for line in sys.stdin:
    request = json.loads(line)
    if request["op"] == "warmup":
        say({"ok": True})
        continue
    text = request["text"].encode()
    pcm = text * 2  # Known stream: each text byte becomes one 16-bit sample.
    if mode[0] == "golden":
        frame(pcm[:4])
        frame(pcm[4:])
        frame(b"")
        say({"ok": True})
    elif mode[0] == "wrong_pipe":
        wire.buffer.write(len(pcm).to_bytes(4, "big") + pcm)
        wire.flush()
        frame(b"")
        say({"ok": True})
    elif mode[0] == "hang":
        child = subprocess.Popen(["sleep", "30"])
        open(os.path.join(root, "child.pid"), "w").write(str(child.pid))
        time.sleep(30)
    elif mode[0] == "random":
        rng = random.Random(int(mode[1]))
        exit_at = rng.randrange(len(pcm) + 4) if mode[2] == "exit" else None
        sent = 0
        while sent < len(pcm):
            size = 2 * rng.randrange(1, 5)  # PCM frames hold whole samples.
            if exit_at is not None and sent + size > exit_at:
                os._exit(4)
            frame(pcm[sent : sent + size])
            sent += size
        if exit_at is not None:
            os._exit(4)
        frame(b"")
        say({"ok": True})
