# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Private JSONL worker: model dependencies live outside the daemon environment."""

from __future__ import annotations

import base64
import contextlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

from aitts.engine import Engine, StreamingEngine
from aitts.model_catalog import MODELS


def local_engine(name: str, root: Path) -> Engine:
    """Construct existing adapters with strictly local, preinstalled assets."""
    if name in {"kokoro", "kokoro-mlx"}:
        loader = importlib.util.find_spec("espeakng_loader")
        if loader is not None and loader.origin is not None:
            os.environ["ESPEAK_DATA_PATH"] = os.path.relpath(
                Path(loader.origin).parent / "espeak-ng-data", root
            )

    from aitts.engines.chatterbox import ChatterboxEngine  # noqa: PLC0415
    from aitts.engines.kokoro import KokoroAssets, KokoroEngine  # noqa: PLC0415
    from aitts.engines.kokoro_mlx import KokoroMlxEngine  # noqa: PLC0415

    def asset(*, repo_id: str, filename: str, local_files_only: bool) -> str:
        del repo_id, local_files_only
        path = root / "assets" / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        return str(path)

    if name == "chatterbox":
        return ChatterboxEngine(root / "assets")
    assets = KokoroAssets(repo_id=MODELS[name].repository, download=asset)
    return KokoroMlxEngine(assets=assets) if name == "kokoro-mlx" else KokoroEngine(assets=assets)


def prepare(name: str, root: Path) -> None:
    """Download a pinned allowlist, then validate actual offline inference before publication."""
    from huggingface_hub import snapshot_download  # noqa: PLC0415 - setup-only network boundary

    model = MODELS[name]
    snapshot_download(
        repo_id=model.repository,
        revision=model.revision,
        allow_patterns=list(model.files),
        local_dir=root / "assets",
    )
    # Weights include pickled torch files; never deserialize bytes that differ from the pin.
    model.verify_assets(root / "assets")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    local_engine(name, root).warmup()


def serve(name: str, root: Path) -> None:
    """Keep one model warm; only framed data is written to the private pipe."""
    wire = sys.stdout
    # Upstream prints must never corrupt the framing or expose speech in logs.
    with (
        Path(os.devnull).open("w") as quiet,
        contextlib.redirect_stdout(quiet),
        contextlib.redirect_stderr(quiet),
    ):
        engine = local_engine(name, root)
        engine.warmup()
        for line in sys.stdin:
            try:
                request = json.loads(line)
                op = request["op"]
                if op == "warmup":
                    engine.warmup()
                    _write(wire, {"ok": True})
                elif op == "stream" and isinstance(engine, StreamingEngine):
                    for block in engine.stream_synthesize(
                        request["text"], request["voice"], request["speed"]
                    ):
                        _write(wire, {"pcm": base64.b64encode(block).decode("ascii")})
                    _write(wire, {"ok": True})
                elif op == "evidence":
                    from aitts.adapters.clip_evidence import runtime_metadata  # noqa: PLC0415

                    evidence = getattr(engine, "evidence", None)
                    metadata = (
                        evidence(request["voice"])
                        if callable(evidence)
                        else {"model_identity": "unavailable"}
                    )
                    _write(
                        wire, {"ok": True, "metadata": {**metadata, "runtime": runtime_metadata()}}
                    )
                elif op == "synthesize":
                    duration = engine.synthesize(
                        request["text"], request["voice"], request["speed"], Path(request["path"])
                    )
                    _write(wire, {"ok": True, "duration_ms": duration})
                else:
                    _write(wire, {"ok": False})
            except Exception:  # noqa: BLE001 - private worker failure stays typed and content-free
                _write(wire, {"ok": False})


def _write(wire: Any, payload: dict[str, Any]) -> None:  # noqa: ANN401 - redirected text stream
    wire.write(json.dumps(payload) + "\n")
    wire.flush()


def main() -> None:
    """Run only a catalog model in its owned runtime."""
    operation, name, directory = sys.argv[1:]
    if name not in MODELS or operation not in {"prepare", "serve"}:
        raise SystemExit(2)
    root = Path(directory).resolve()
    # eSpeak has a fixed native path buffer; long macOS application-support paths overflow it.
    os.chdir(root)
    if operation == "prepare":
        prepare(name, root)
    else:
        serve(name, root)


if __name__ == "__main__":
    main()
