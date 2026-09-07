# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Build the Swift menu executable into a standalone macOS app bundle."""

from __future__ import annotations

import argparse
import json
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

BUNDLE_IDENTIFIER = "com.flyingrobots.ai-tts.menubar"
EXECUTABLE_NAME = "AITTSMenuBar"
MACOS_DEPLOYMENT_TARGET = "14.0"
APP_INTENT_ACTION_TITLES = {
    "Pause",
    "Read File",
    "Read Text",
    "Resume",
    "Set Playback Speed",
    "Skip",
}
APP_SHORTCUT_IDENTIFIERS = {
    "PauseSpeechIntent",
    "ReadFileIntent",
    "ReadTextIntent",
    "ResumeSpeechIntent",
    "SetPlaybackSpeedIntent",
    "SkipSpeechIntent",
}
MULTIPLICATION_SIGN = "\N{MULTIPLICATION SIGN}"
APP_INTENT_PLAYBACK_RATES = [
    f"0.5{MULTIPLICATION_SIGN}",
    f"0.75{MULTIPLICATION_SIGN}",
    f"1{MULTIPLICATION_SIGN}",
    f"1.5{MULTIPLICATION_SIGN}",
    f"2{MULTIPLICATION_SIGN}",
    f"3{MULTIPLICATION_SIGN}",
]
NATIVE_SERVICES: list[dict[str, Any]] = [
    {
        "NSMenuItem": {"default": "Read Selection with AI-TTS"},
        "NSMessage": "readSelection",
        "NSPortName": "AI-TTS",
        "NSRequiredContext": {},
        "NSRestricted": False,
        "NSSendTypes": ["public.utf8-plain-text"],
    },
    {
        "NSMenuItem": {"default": "Read File with AI-TTS"},
        "NSMessage": "readFile",
        "NSPortName": "AI-TTS",
        "NSRequiredContext": {},
        "NSRestricted": False,
        "NSSendFileTypes": [
            "public.plain-text",
            "net.daringfireball.markdown",
            "com.adobe.pdf",
        ],
    },
]


def _records(document: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = document.get(key)
    records: list[Any]
    if isinstance(value, dict):
        records = list(value.values())
    elif isinstance(value, list):
        records = value
    else:
        records = []
    if not all(isinstance(record, dict) for record in records):
        records = []
    if not records:
        msg = f"App Intents metadata field {key!r} must contain objects"
        raise ValueError(msg)
    return records


def _string_at(document: dict[str, Any], *keys: str) -> str | None:
    value: Any = document
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value if isinstance(value, str) else None


def validate_app_intents_metadata(metadata: Path) -> None:
    """Refuse generated metadata that does not expose the designed contract."""
    actions_data = metadata / "extract.actionsdata"
    version = metadata / "version.json"
    if not actions_data.is_file() or not version.is_file():
        msg = f"incomplete App Intents metadata directory: {metadata}"
        raise ValueError(msg)

    with actions_data.open(encoding="utf-8") as stream:
        document = json.load(stream)
    if not isinstance(document, dict):
        msg = "App Intents metadata root must be an object"
        raise TypeError(msg)

    actions = _records(document, "actions")
    action_titles = {_string_at(action, "title", "key") for action in actions}
    if len(actions) != len(APP_INTENT_ACTION_TITLES) or action_titles != APP_INTENT_ACTION_TITLES:
        msg = f"unexpected App Intents actions: {sorted(str(title) for title in action_titles)}"
        raise ValueError(msg)
    if any(action.get("openAppWhenRun") is not False for action in actions):
        msg = "every AI-TTS App Intent must run in the background"
        raise ValueError(msg)

    shortcuts = _records(document, "autoShortcuts")
    shortcut_identifiers = {_string_at(shortcut, "actionIdentifier") for shortcut in shortcuts}
    if (
        len(shortcuts) != len(APP_SHORTCUT_IDENTIFIERS)
        or shortcut_identifiers != APP_SHORTCUT_IDENTIFIERS
    ):
        values = sorted(str(value) for value in shortcut_identifiers)
        msg = f"unexpected App Intents shortcuts: {values}"
        raise ValueError(msg)

    enum_cases = [
        [
            _string_at(case, "displayRepresentation", "title", "key")
            for case in _records(enum, "cases")
        ]
        for enum in _records(document, "enums")
    ]
    if APP_INTENT_PLAYBACK_RATES not in enum_cases:
        msg = f"unexpected App Intents playback rates: {enum_cases}"
        raise ValueError(msg)


def _checked_output(arguments: list[str]) -> str:
    """Run one trusted build tool and return trimmed standard output."""
    return subprocess.run(  # noqa: S603
        arguments,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def find_app_intents_catalog(toolchain: Path) -> Path | None:
    """Locate the App Intents constant-value catalog inside ``toolchain``.

    The catalog is a short list of the Swift protocols whose conformances the
    compiler must gather constant values for. Apple has moved it between
    releases, so the documented location is tried first and the toolchain is
    then searched — a relocation should not be indistinguishable from a
    toolchain that cannot do the job at all.
    """
    documented = toolchain / "usr" / "share" / "swift" / "SwiftConstantValues" / "AppIntents.json"
    if documented.is_file():
        return documented
    for candidate in sorted(toolchain.rglob("SwiftConstantValues/AppIntents.json")):
        if candidate.is_file():
            return candidate
    return None


def _app_intents_tooling(toolchain: Path, *, processor: Path, allow_missing: bool) -> Path | None:
    """Return the protocol catalog, or ``None`` when absence is permitted.

    Raises when the toolchain cannot extract App Intents metadata and the
    caller has not explicitly allowed a bundle without it.
    """
    catalog = find_app_intents_catalog(toolchain)
    missing = [
        name
        for name, present in (
            ("usr/bin/appintentsmetadataprocessor", processor.is_file()),
            ("SwiftConstantValues/AppIntents.json", catalog is not None),
        )
        if not present
    ]
    if not missing:
        return catalog
    if allow_missing:
        sys.stderr.write(
            f"warning: skipping App Intents metadata — {', '.join(missing)} missing under "
            f"{toolchain}. THE RESULTING BUNDLE HAS NO SHORTCUTS INTEGRATION and must not be "
            "released. Build with a toolchain that ships the catalog.\n"
        )
        return None
    # "cannot extract App Intents metadata" is true of every cause and points
    # at none of them. The cause in practice is an Xcode older than the one
    # this was developed against — a CI runner's default, most likely — so name
    # the toolchain, name what is absent, and name the command that changes it.
    msg = (
        "the active Xcode toolchain cannot extract App Intents metadata: "
        f"{', '.join(missing)} missing under {toolchain}. "
        "Select a newer Xcode with `sudo xcode-select -s /Applications/Xcode_<version>.app` "
        "and check `xcodebuild -version`."
    )
    raise RuntimeError(msg)


def generate_app_intents_metadata(
    *,
    repository: Path,
    binary: Path,
    module_search_path: Path,
    resources: Path,
    allow_missing_catalog: bool = False,
) -> Path | None:
    """Extract compile-time App Intents metadata into an assembled bundle.

    Returns the metadata bundle, or ``None`` when the toolchain cannot supply
    the protocol catalog *and* the caller has explicitly allowed that. The
    default is to refuse: a bundle without this metadata has no Shortcuts
    integration, and shipping one silently is worse than a failed build.
    """
    xcrun = shutil.which("xcrun")
    xcodebuild = shutil.which("xcodebuild")
    if xcrun is None or xcodebuild is None:
        msg = "Xcode command-line tools are required to package App Intents"
        raise RuntimeError(msg)

    swiftc = Path(_checked_output([xcrun, "--find", "swiftc"]))
    toolchain = swiftc.parents[2]
    processor = toolchain / "usr" / "bin" / "appintentsmetadataprocessor"
    found_catalog = _app_intents_tooling(
        toolchain, processor=processor, allow_missing=allow_missing_catalog
    )
    if found_catalog is None:
        return None
    sdk = Path(_checked_output([xcrun, "--sdk", "macosx", "--show-sdk-path"]))
    target_info = json.loads(_checked_output([str(swiftc), "-print-target-info"]))
    target = target_info.get("target")
    architecture = target.get("arch") if isinstance(target, dict) else None
    if not isinstance(architecture, str) or not architecture:
        msg = "swiftc did not report a target architecture"
        raise RuntimeError(msg)

    xcode_version = _checked_output([xcodebuild, "-version"])
    build_version = next(
        (
            line.removeprefix("Build version ")
            for line in xcode_version.splitlines()
            if line.startswith("Build version ")
        ),
        None,
    )
    if build_version is None:
        msg = "xcodebuild did not report a build version"
        raise RuntimeError(msg)

    app_intents_source = (
        repository / "clients" / "menubar" / "Sources" / "AITTSMenuBar" / "AppIntents.swift"
    )
    source_files = sorted(app_intents_source.parent.glob("*.swift"))
    protocol_catalog = found_catalog
    assert protocol_catalog is not None  # noqa: S101 - guarded by the check above
    with protocol_catalog.open(encoding="utf-8") as stream:
        catalog = json.load(stream)
    protocols = catalog.get("constValueProtocols") if isinstance(catalog, dict) else None
    if not isinstance(protocols, list) or not all(isinstance(value, str) for value in protocols):
        msg = f"malformed App Intents protocol catalog: {protocol_catalog}"
        raise RuntimeError(msg)

    with tempfile.TemporaryDirectory(prefix="ai-tts-app-intents-") as temporary:
        work = Path(temporary)
        protocols_path = work / "protocols.json"
        const_values = work / "AppIntents.swiftconstvalues"
        object_file = work / "AppIntents.o"
        sources_list = work / "sources.list"
        const_values_list = work / "constvalues.list"
        protocols_path.write_text(json.dumps(protocols) + "\n", encoding="utf-8")
        sources_list.write_text(
            "".join(f"{source.resolve()}\n" for source in source_files), encoding="utf-8"
        )
        const_values_list.write_text(f"{const_values}\n", encoding="utf-8")

        subprocess.run(  # noqa: S603
            [
                str(swiftc),
                "-c",
                "-parse-as-library",
                str(app_intents_source),
                "-module-name",
                "AITTSMenuBar",
                "-target",
                f"{architecture}-apple-macosx{MACOS_DEPLOYMENT_TARGET}",
                "-sdk",
                str(sdk),
                "-I",
                str(module_search_path),
                "-Xfrontend",
                "-const-gather-protocols-file",
                "-Xfrontend",
                str(protocols_path),
                "-emit-const-values",
                "-emit-const-values-path",
                str(const_values),
                "-o",
                str(object_file),
            ],
            cwd=repository,
            check=True,
        )
        subprocess.run(  # noqa: S603
            [
                str(processor),
                "--output",
                str(resources),
                "--toolchain-dir",
                str(toolchain),
                "--module-name",
                "AITTSMenuBar",
                "--sdk-root",
                str(sdk),
                "--xcode-version",
                build_version,
                "--platform-family",
                "macOS",
                "--deployment-target",
                MACOS_DEPLOYMENT_TARGET,
                "--target-triple",
                f"{architecture}-apple-macos{MACOS_DEPLOYMENT_TARGET}",
                "--source-file-list",
                str(sources_list),
                "--swift-const-vals-list",
                str(const_values_list),
                "--binary-file",
                str(binary),
                "--bundle-identifier",
                BUNDLE_IDENTIFIER,
                "--compile-time-extraction",
                "--deployment-aware-processing",
                "--no-app-shortcuts-localization",
                "--force",
            ],
            check=True,
        )

    metadata = resources / "Metadata.appintents"
    validate_app_intents_metadata(metadata)
    return metadata


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
        "LSMinimumSystemVersion": MACOS_DEPLOYMENT_TARGET,
        "LSMultipleInstancesProhibited": True,
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "NSServices": NATIVE_SERVICES,
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
    *,
    repository: Path,
    output: Path,
    configuration: str = "release",
    sign: bool = True,
    allow_missing_app_intents: bool = False,
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
    generate_app_intents_metadata(
        repository=repository,
        binary=bundle / "Contents" / "MacOS" / EXECUTABLE_NAME,
        module_search_path=Path(bin_path) / "Modules",
        resources=bundle / "Contents" / "Resources",
        allow_missing_catalog=allow_missing_app_intents,
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
    parser.add_argument(
        "--allow-missing-app-intents",
        action="store_true",
        help=(
            "assemble the bundle even when the toolchain cannot supply the App Intents "
            "protocol catalog. The result has NO Shortcuts integration and must never be "
            "released; this exists so CI can verify the rest of the bundle on a runner "
            "whose newest Xcode does not ship the catalog."
        ),
    )
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
        allow_missing_app_intents=args.allow_missing_app_intents,
    )
    sys.stdout.write(f"{output}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - executable wrapper
    raise SystemExit(main())
