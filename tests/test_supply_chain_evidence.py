# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Dependency evidence fails closed when a generator goes empty or drifts."""

from __future__ import annotations

import hashlib

import pytest
from scripts.verify_supply_chain_evidence import (
    SupplyChainEvidenceError,
    verify_supply_chain_evidence,
)

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("cross-checked vulnerability, SBOM, license, and lock evidence"),
]

AUDIT: dict[str, object] = {
    "dependencies": [
        {"name": "alpha_pkg", "version": "1.2.3", "vulns": []},
        {"name": "beta", "version": "4.5.6", "vulns": []},
    ],
    "fixes": [],
}
SBOM: dict[str, object] = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.5",
    "components": [
        {"name": "alpha-pkg", "version": "1.2.3"},
        {"name": "beta", "version": "4.5.6"},
        {"name": "other-platform-only", "version": "9.0"},
    ],
}
LICENSES: list[dict[str, object]] = [
    {
        "Name": "alpha-pkg",
        "Version": "1.2.3",
        "License": "MIT",
        "URL": "https://example.test/alpha",
    },
    {
        "Name": "beta",
        "Version": "4.5.6",
        "License": "UNKNOWN",
        "URL": "https://example.test/beta",
    },
    {
        "Name": "audit-tool",
        "Version": "7.0",
        "License": "Apache-2.0",
        "URL": "https://example.test/tool",
    },
]
LOCK_BYTES = b"controlled uv lock\n"


def test_consistent_nonempty_evidence_is_normalized_and_unknowns_are_disclosed() -> None:
    evidence = verify_supply_chain_evidence(AUDIT, SBOM, LICENSES, LOCK_BYTES)

    assert evidence.summary == {
        "schema_version": 1,
        "lock_sha256": hashlib.sha256(LOCK_BYTES).hexdigest(),
        "dependency_count": 2,
        "vulnerability_count": 0,
        "sbom_component_count": 3,
        "license_record_count": 2,
        "unknown_license_count": 1,
        "unknown_licenses": ["beta"],
    }
    assert [record["name"] for record in evidence.licenses] == ["alpha-pkg", "beta"]
    assert evidence.licenses[0]["license"] == "MIT"
    assert evidence.licenses[1]["license"] == "UNKNOWN"


def test_empty_dependency_audit_is_rejected() -> None:
    audit: dict[str, object] = {"dependencies": [], "fixes": []}

    with pytest.raises(SupplyChainEvidenceError, match="no audited dependencies"):
        verify_supply_chain_evidence(audit, SBOM, LICENSES, LOCK_BYTES)


def test_reported_vulnerability_is_rejected_even_if_the_tool_exit_were_ignored() -> None:
    audit: dict[str, object] = {
        "dependencies": [
            {
                "name": "alpha_pkg",
                "version": "1.2.3",
                "vulns": [{"id": "PYSEC-CONTROLLED"}],
            },
            {"name": "beta", "version": "4.5.6", "vulns": []},
        ],
        "fixes": [],
    }

    with pytest.raises(SupplyChainEvidenceError, match="PYSEC-CONTROLLED"):
        verify_supply_chain_evidence(audit, SBOM, LICENSES, LOCK_BYTES)


def test_audited_dependency_missing_from_sbom_is_rejected() -> None:
    sbom: dict[str, object] = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "components": [
            {"name": "beta", "version": "4.5.6"},
            {"name": "other-platform-only", "version": "9.0"},
        ],
    }

    with pytest.raises(SupplyChainEvidenceError, match=r"SBOM.*alpha-pkg"):
        verify_supply_chain_evidence(AUDIT, sbom, LICENSES, LOCK_BYTES)


def test_audited_dependency_missing_from_license_inventory_is_rejected() -> None:
    licenses = LICENSES[1:]

    with pytest.raises(SupplyChainEvidenceError, match=r"license inventory.*alpha-pkg"):
        verify_supply_chain_evidence(AUDIT, SBOM, licenses, LOCK_BYTES)
