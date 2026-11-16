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


def check(root: Path, uv: str, *, write: bool = False) -> list[str]:
    """Return drifted paths, optionally replacing only the generated manifests.

    Keep each relative output path identical to the documented export command,
    including uv's generated header. Only the project metadata and frozen lock
    enter the temporary project; no model environment or weights are installed.
    The separately pinned English model supplements both Kokoro exports.
    Default check mode does not modify the checkout.
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
            expected = (scratch / relative).read_bytes()
            if model in {"kokoro", "kokoro-mlx"}:
                expected += b"\n" + (root / _MANIFESTS / "kokoro-supplement.txt").read_bytes()
            if not (root / relative).is_file() or (root / relative).read_bytes() != expected:
                changed.append(relative.as_posix())
                if write:
                    (root / relative).write_bytes(expected)
    return changed


def main() -> int:
    """Exit nonzero on export failure or drift in any guided-runtime manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", default="uv", help="uv executable; use the version pinned in CI")
    parser.add_argument(
        "--write", action="store_true", help="regenerate the three checked-in exports"
    )
    args = parser.parse_args()
    executable = shutil.which(args.uv)
    if executable is None:
        parser.error("uv executable was not found")
    executable = str(Path(executable).resolve())
    changed = check(Path(__file__).resolve().parents[1], executable, write=args.write)
    if changed and not args.write:
        sys.stderr.write("Runtime manifests differ from frozen lock exports:\n")
        sys.stderr.write("".join(f"  {path}\n" for path in changed))
        return 1
    sys.stdout.write("All three runtime manifests match the frozen lock and pinned supplement.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
