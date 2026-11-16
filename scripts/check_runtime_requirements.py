# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Compare consumed model-runtime manifests with offline frozen-lock exports."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

_EXPORTS = (("kokoro", "kokoro"), ("kokoro-mlx", "mlx"), ("chatterbox", "chatterbox"))
_MANIFESTS = Path("src/aitts/runtime_requirements")


def check(root: Path, uv: str) -> list[str]:
    """Return drifted paths without modifying the checkout or downloading packages.

    Keep each relative output path identical to the documented export command,
    including uv's generated header. Only the project metadata and frozen lock
    enter the temporary project; no model environment or weights are installed.
    """
    changed = []
    with TemporaryDirectory(prefix="aitts-runtime-exports-") as name:
        scratch = Path(name)
        for source in ("pyproject.toml", "uv.lock"):
            shutil.copyfile(root / source, scratch / source)
        (scratch / _MANIFESTS).mkdir(parents=True)
        env = {**os.environ, "UV_OFFLINE": "1", "UV_CACHE_DIR": str(scratch / "cache")}
        for model, extra in _EXPORTS:
            relative = _MANIFESTS / f"{model}.txt"
            command = [
                uv,
                "export",
                "--frozen",
                "--no-default-groups",
                "--extra",
                extra,
                "--no-emit-project",
                "--output-file",
                relative.as_posix(),
            ]
            subprocess.run(  # noqa: S603 - explicit local uv executable, no shell; offline export only.
                command,
                cwd=scratch,
                env=env,
                check=True,
                timeout=30,
                stdout=subprocess.DEVNULL,
            )
            if (
                not (root / relative).is_file()
                or (root / relative).read_bytes() != (scratch / relative).read_bytes()
            ):
                changed.append(relative.as_posix())
    return changed


def main() -> int:
    """Exit nonzero on export failure or drift in any guided-runtime manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", default="uv", help="uv executable; use the version pinned in CI")
    args = parser.parse_args()
    executable = shutil.which(args.uv)
    if executable is None:
        parser.error("uv executable was not found")
    changed = check(Path(__file__).resolve().parents[1], executable)
    if changed:
        sys.stderr.write("Runtime manifests differ from frozen lock exports:\n")
        sys.stderr.write("".join(f"  {path}\n" for path in changed))
        return 1
    sys.stdout.write("All three guided-runtime manifests match the frozen lock.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
