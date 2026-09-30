# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Source audit evidence is bound to reviewed artifacts and keeps findings."""

from __future__ import annotations

from typing import Any

import pytest
from scripts.audit_source_dependencies import SourcePin, merge_source_audit
from scripts.verify_supply_chain_evidence import (
    SupplyChainEvidenceError,
    verify_supply_chain_evidence,
)

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("immutable source identity and complete advisory evidence"),
]
PIN = SourcePin("native", "1.0", "owner/native", "a" * 40, "b" * 64)
LOCK = f"""[[package]]
name = "native"
version = "1.0"
source = {{ url = "{PIN.url}" }}
sdist = {{ hash = "sha256:{"b" * 64}" }}
"""
AUDIT = {"dependencies": [{"name": "numpy", "version": "2.0", "vulns": []}]}


def test_source_evidence_contains_identity_and_both_queries() -> None:
    queries = []

    def query(payload: dict[str, Any]) -> dict[str, Any]:
        queries.append(payload)
        return {}

    result = merge_source_audit(AUDIT, LOCK, query, (PIN,))
    assert queries == [
        {"commit": "a" * 40},
        {"package": {"ecosystem": "PyPI", "name": "native"}, "version": "1.0"},
    ]
    assert result["dependencies"][0] == AUDIT["dependencies"][0]
    source = result["dependencies"][1]
    assert (source["name"], source["version"], source["source_url"], source["source_sha256"]) == (
        "native",
        "1.0",
        PIN.url,
        "b" * 64,
    )
    assert source["audit_method"] == "osv_commit_and_package"
    assert source["responses"] == [{}, {}]
    assert source["vulns"] == []


@pytest.mark.parametrize(
    "lock",
    [
        LOCK.replace("1.0", "2.0"),
        LOCK.replace("a" * 40, "c" * 40),
        LOCK.replace("b" * 64, "c" * 64),
        LOCK + '\n[[package]]\nname="other"\nversion="1"\nsource={git="unexpected"}\n',
    ],
)
def test_changed_or_unlisted_source_fails_before_query(lock: str) -> None:
    def forbidden(payload: dict[str, Any]) -> dict[str, Any]:
        pytest.fail(f"queried invalid identity: {payload}")

    with pytest.raises(ValueError, match="source"):
        merge_source_audit(AUDIT, lock, forbidden, (PIN,))


@pytest.mark.parametrize("finding_query", [0, 1])
def test_either_source_query_finding_fails_existing_evidence_gate(finding_query: int) -> None:
    responses = iter(
        [{"vulns": [{"id": "OSV-REGRESSION"}]} if i == finding_query else {} for i in range(2)]
    )
    result = merge_source_audit(AUDIT, LOCK, lambda _: next(responses), (PIN,))
    with pytest.raises(SupplyChainEvidenceError, match="OSV-REGRESSION"):
        verify_supply_chain_evidence(result, {}, [], LOCK.encode())


@pytest.mark.parametrize("response", [{"error": "unavailable"}, {"vulns": None}])
def test_invalid_service_response_cannot_be_clean_evidence(response: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="OSV"):
        merge_source_audit(AUDIT, LOCK, lambda _: response, (PIN,))


def test_query_transport_failure_propagates() -> None:
    def fail(_: dict[str, Any]) -> dict[str, Any]:
        message = "service unavailable"
        raise OSError(message)

    with pytest.raises(OSError, match="service unavailable"):
        merge_source_audit(AUDIT, LOCK, fail, (PIN,))


@pytest.mark.parametrize(
    "audit",
    [{"dependencies": []}, {"dependencies": [{"name": "native", "version": "1.0", "vulns": []}]}],
)
def test_missing_pypi_evidence_or_overlapping_source_is_rejected(audit: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="PyPI"):
        merge_source_audit(audit, LOCK, lambda _: {}, (PIN,))


def test_source_packages_participate_in_sbom_and_license_checks() -> None:
    result = merge_source_audit(AUDIT, LOCK, lambda _: {}, (PIN,))
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "components": [{"name": "numpy", "version": "2.0"}, {"name": "native", "version": "1.0"}],
    }
    licenses = [
        {"Name": "numpy", "Version": "2.0", "License": "BSD"},
        {"Name": "native", "Version": "1.0", "License": "MIT"},
    ]
    evidence = verify_supply_chain_evidence(result, sbom, licenses, LOCK.encode())
    assert evidence.summary["dependency_count"] == 2
    assert evidence.licenses[0]["name"] == "native"
    with pytest.raises(SupplyChainEvidenceError, match="missing audited dependencies: native"):
        verify_supply_chain_evidence(result, sbom, licenses[:1], LOCK.encode())
