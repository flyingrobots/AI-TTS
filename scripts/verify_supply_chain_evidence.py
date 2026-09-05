# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Validate and normalize retained dependency-audit evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, cast

_UNKNOWN_LICENSES = {"", "n/a", "none", "unknown"}


class SupplyChainEvidenceError(ValueError):
    """The generated dependency evidence is empty or internally inconsistent."""


def _fail(message: str) -> NoReturn:
    raise SupplyChainEvidenceError(message)


@dataclass(frozen=True)
class VerifiedSupplyChainEvidence:
    """Normalized evidence safe to retain as a CI artifact."""

    summary: dict[str, object]
    licenses: tuple[dict[str, str], ...]


def verify_supply_chain_evidence(
    audit: object,
    sbom: object,
    raw_licenses: object,
    lock_bytes: bytes,
) -> VerifiedSupplyChainEvidence:
    """Verify non-vacuity and agreement across the three generated reports."""
    if not lock_bytes:
        _fail("uv.lock is empty")

    audited = _audited_packages(audit)
    sbom_component_count = _verify_sbom(sbom, audited)
    licenses, unknown_licenses = _normalize_licenses(raw_licenses, audited)
    summary: dict[str, object] = {
        "schema_version": 1,
        "lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
        "dependency_count": len(audited),
        "vulnerability_count": 0,
        "sbom_component_count": sbom_component_count,
        "license_record_count": len(licenses),
        "unknown_license_count": len(unknown_licenses),
        "unknown_licenses": unknown_licenses,
    }
    return VerifiedSupplyChainEvidence(summary=summary, licenses=licenses)


def _audited_packages(payload: object) -> dict[str, str]:
    root = _mapping(payload, "dependency audit")
    dependencies = _sequence(root.get("dependencies"), "dependency audit dependencies")
    if not dependencies:
        _fail("dependency audit contains no audited dependencies")

    audited: dict[str, str] = {}
    vulnerability_ids: list[str] = []
    for position, raw_dependency in enumerate(dependencies):
        dependency = _mapping(raw_dependency, f"dependency audit entry {position}")
        name = _canonical_name(_required_string(dependency.get("name"), "audit name"))
        version = _required_string(dependency.get("version"), f"audit version for {name}")
        if name in audited:
            _fail(f"dependency audit repeats {name}")
        audited[name] = version

        vulnerabilities = _sequence(
            dependency.get("vulns"),
            f"audit vulnerabilities for {name}",
        )
        for raw_vulnerability in vulnerabilities:
            vulnerability = _mapping(raw_vulnerability, f"vulnerability for {name}")
            identifier = vulnerability.get("id")
            vulnerability_ids.append(
                identifier
                if isinstance(identifier, str) and identifier
                else "unknown-vulnerability"
            )

    if vulnerability_ids:
        joined = ", ".join(sorted(vulnerability_ids))
        _fail(f"dependency audit reports vulnerabilities: {joined}")
    return audited


def _verify_sbom(payload: object, audited: dict[str, str]) -> int:
    root = _mapping(payload, "SBOM")
    if root.get("bomFormat") != "CycloneDX" or root.get("specVersion") != "1.5":
        _fail("SBOM is not CycloneDX 1.5")
    components = _sequence(root.get("components"), "SBOM components")
    if not components:
        _fail("SBOM contains no components")

    available: set[tuple[str, str]] = set()
    for position, raw_component in enumerate(components):
        component = _mapping(raw_component, f"SBOM component {position}")
        name = _canonical_name(_required_string(component.get("name"), "SBOM component name"))
        version = _required_string(component.get("version"), f"SBOM version for {name}")
        available.add((name, version))

    missing = sorted(
        f"{name}=={version}"
        for name, version in audited.items()
        if (name, version) not in available
    )
    if missing:
        _fail("SBOM is missing audited dependencies: " + ", ".join(missing))
    return len(components)


def _normalize_licenses(
    payload: object,
    audited: dict[str, str],
) -> tuple[tuple[dict[str, str], ...], list[str]]:
    raw_records = _sequence(payload, "license inventory")
    if not raw_records:
        _fail("license inventory contains no packages")

    available: dict[str, dict[str, object]] = {}
    for position, raw_record in enumerate(raw_records):
        license_record = _mapping(raw_record, f"license inventory entry {position}")
        name = _canonical_name(_required_string(license_record.get("Name"), "license package name"))
        if name in available:
            _fail(f"license inventory repeats {name}")
        available[name] = license_record

    missing: list[str] = []
    normalized: list[dict[str, str]] = []
    unknown: list[str] = []
    for name, version in sorted(audited.items()):
        matched_record = available.get(name)
        if matched_record is None or matched_record.get("Version") != version:
            missing.append(f"{name}=={version}")
            continue

        license_name = _license_value(matched_record.get("License"))
        if _is_unknown_license(license_name):
            unknown.append(name)
        normalized.append(
            {
                "name": name,
                "version": version,
                "license": license_name,
                "url": _optional_string(matched_record.get("URL")),
            }
        )

    if missing:
        _fail("license inventory is missing audited dependencies: " + ", ".join(missing))
    return tuple(normalized), unknown


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        _fail(f"{label} is not an object")
    if not all(isinstance(key, str) for key in value):
        _fail(f"{label} has a non-string key")
    return cast("dict[str, object]", value)


def _sequence(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        _fail(f"{label} is not an array")
    return cast("list[object]", value)


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{label} is not a non-empty string")
    return value


def _optional_string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _license_value(value: object) -> str:
    candidate = _optional_string(value).strip()
    return candidate or "UNKNOWN"


def _is_unknown_license(value: str) -> bool:
    return value.casefold() in _UNKNOWN_LICENSES


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _load_json(path: Path) -> object:
    try:
        return cast("object", json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as error:
        message = f"cannot read {path}: {error}"
        raise SupplyChainEvidenceError(message) from error


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    """Validate generated files and write the normalized retained evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--licenses", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()

    try:
        evidence = verify_supply_chain_evidence(
            _load_json(arguments.audit),
            _load_json(arguments.sbom),
            _load_json(arguments.licenses),
            arguments.lock.read_bytes(),
        )
        arguments.output_dir.mkdir(parents=True, exist_ok=True)
        _write_json(arguments.output_dir / "summary.json", evidence.summary)
        _write_json(arguments.output_dir / "licenses.json", list(evidence.licenses))
    except (OSError, SupplyChainEvidenceError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
