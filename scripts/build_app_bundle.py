# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Build the Swift menu executable into a standalone macOS app bundle."""

from __future__ import annotations

import argparse
import plistlib
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

BUNDLE_IDENTIFIER = "com.flyingrobots.ai-tts.menubar"
EXECUTABLE_NAME = "AITTSMenuBar"


def assemble_app_bundle(*, binary: Path, output: Path, version: str) -> Path:
    """Copy ``binary`` and canonical metadata into a new ``.app`` bundle."""
    if not binary.is_file():
        msg = f"menu executable does not exist: {binary}"
        raise FileNotFoundError(msg)
    if output.suffix != ".app":
        msg = f"app bundle output must end in .app: {output}"
        raise ValueError(msg)
    if output.exists():
        msg = f"refusing to replace existing app bundle: {output}"
        raise FileExistsError(msg)
    if not version:
        msg = "version must not be empty"
        raise ValueError(msg)

    contents = output / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir()
    installed_binary = macos / EXECUTABLE_NAME
    shutil.copy2(binary, installed_binary)
    installed_binary.chmod(installed_binary.stat().st_mode | stat.S_IXUSR)

    info: dict[str, Any] = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": "AI-TTS",
        "CFBundleExecutable": EXECUTABLE_NAME,
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "AI-TTS",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSMinimumSystemVersion": "14.0",
        "LSMultipleInstancesProhibited": True,
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
    }
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream, sort_keys=True)
    return output


def project_version(repository: Path) -> str:
    """Read the release version from the Python package's canonical metadata."""
    with (repository / "pyproject.toml").open("rb") as stream:
        document = tomllib.load(stream)
    project = document.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("version"), str):
        msg = "pyproject.toml has no string project.version"
        raise TypeError(msg)
    return str(project["version"])


def build_app_bundle(
    *, repository: Path, output: Path, configuration: str = "release", sign: bool = True
) -> Path:
    """Build Swift, assemble the bundle, and optionally apply an ad-hoc signature."""
    swift = shutil.which("swift")
    if swift is None:
        msg = "swift is required to build the menu-bar app"
        raise RuntimeError(msg)
    swift_project = repository / "clients" / "menubar"
    subprocess.run(  # noqa: S603
        [swift, "build", "-c", configuration],
        cwd=swift_project,
        check=True,
    )
    bin_path = subprocess.run(  # noqa: S603
        [swift, "build", "-c", configuration, "--show-bin-path"],
        cwd=swift_project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    bundle = assemble_app_bundle(
        binary=Path(bin_path) / EXECUTABLE_NAME,
        output=output,
        version=project_version(repository),
    )
    if sign:
        codesign = shutil.which("codesign")
        if codesign is None:
            msg = "codesign is required unless --unsigned is passed"
            raise RuntimeError(msg)
        subprocess.run(  # noqa: S603
            [codesign, "--force", "--sign", "-", str(bundle)],
            check=True,
        )
    return bundle


def main(argv: list[str] | None = None) -> int:
    """Build one standalone app bundle from the repository's Swift target."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--configuration", choices=("debug", "release"), default="release")
    parser.add_argument("--unsigned", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    repository = Path(__file__).resolve().parents[1]
    output = args.output.expanduser().resolve()
    if output.exists():
        if not args.force:
            parser.error(f"output already exists: {output}; pass --force to replace it")
        shutil.rmtree(output)
    build_app_bundle(
        repository=repository,
        output=output,
        configuration=args.configuration,
        sign=not args.unsigned,
    )
    sys.stdout.write(f"{output}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - executable wrapper
    raise SystemExit(main())
