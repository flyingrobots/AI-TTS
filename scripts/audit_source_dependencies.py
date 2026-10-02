# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Attach explicit OSV source-revision evidence to the strict PyPI audit."""

from __future__ import annotations

import argparse
import http.client
import json
import tomllib
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

# A bound on followed pages, so a service that keeps returning tokens fails the job.
_MAX_OSV_PAGES = 100


@dataclass(frozen=True)
class SourcePin:
    """An upstream revision validated with the native adapter."""

    name: str
    version: str
    repository: str
    commit: str
    sha256: str

    @property
    def url(self) -> str:
        """Return the immutable source archive location."""
        return f"https://github.com/{self.repository}/archive/{self.commit}.tar.gz"


SOURCE_PINS = (
    SourcePin(
        "chatterbox-tts",
        "0.1.6",
        "resemble-ai/chatterbox",
        "cb240457c3e197c6fbc2e7d3b9765febe63f7e73",
        "6965eb13135b13c79f2205656cd38e7f080cc6a9c9d07c4d9e9554a33e14739e",
    ),
    SourcePin(
        "resemble-perth",
        "1.1.0",
        "resemble-ai/Perth",
        "ff1c8ac55a976971245cdd53c18d6131ca00d993",
        "00e89ff833f7efc1a0ae0ca3c5420ae108b9adbed9c0fb7b03750b854d30f149",
    ),
)


def merge_source_audit(
    pypi_audit: dict[str, Any],
    lock_text: str,
    query: Callable[[dict[str, Any]], object],
    pins: tuple[SourcePin, ...] = SOURCE_PINS,
) -> dict[str, Any]:
    """Require exact source pins and retain commit and package advisory results.

    OSV's empty response means no known findings, not proof of code security or
    database coverage. Source results are labeled separately from PyPI results.
    """
    packages = tomllib.loads(lock_text)["package"]
    sources = [
        p for p in packages if "registry" not in p["source"] and p["source"] != {"editable": "."}
    ]
    if len(sources) != len(pins) or {p["name"] for p in sources} != {p.name for p in pins}:
        message = "source dependency set differs from validated pins"
        raise ValueError(message)
    dependencies = pypi_audit.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        message = "PyPI audit must contain dependencies"
        raise ValueError(message)
    if any(d.get("name") in {p.name for p in pins} for d in dependencies):
        message = "source dependency appears in PyPI audit"
        raise ValueError(message)
    records = []
    for pin in pins:
        package = next(p for p in sources if p["name"] == pin.name)
        if (
            package["version"] != pin.version
            or package["source"] != {"url": pin.url}
            or package.get("sdist", {}).get("hash") != f"sha256:{pin.sha256}"
        ):
            message = f"source identity mismatch: {pin.name}"
            raise ValueError(message)
        requests: list[dict[str, Any]] = [
            {"commit": pin.commit},
            {"package": {"ecosystem": "PyPI", "name": pin.name}, "version": pin.version},
        ]
        queries: list[dict[str, Any]] = []
        responses: list[object] = []
        vulnerabilities: list[object] = []
        for request in requests:
            _query_all_pages(request, query, queries, responses, vulnerabilities)
        records.append(
            {
                "name": pin.name,
                "version": pin.version,
                "vulns": vulnerabilities,
                "audit_method": "osv_commit_and_package",
                "source_url": pin.url,
                "source_sha256": pin.sha256,
                "queries": queries,
                "responses": responses,
                "limitation": (
                    "No known findings does not establish source security or advisory coverage."
                ),
            }
        )
    return {**pypi_audit, "dependencies": [*dependencies, *records]}


def _query_all_pages(
    request: dict[str, Any],
    query: Callable[[dict[str, Any]], object],
    queries: list[dict[str, Any]],
    responses: list[object],
    vulnerabilities: list[object],
) -> None:
    """Follow OSV's ``next_page_token`` until the last page, keeping every page."""
    payload = request
    for _ in range(_MAX_OSV_PAGES):
        queries.append(payload)
        response = query(payload)
        responses.append(response)
        if not isinstance(response, dict) or set(response) - {"vulns", "next_page_token"}:
            message = "unexpected OSV response"
            raise ValueError(message)
        findings = response.get("vulns", [])
        if not isinstance(findings, list):
            message = "invalid OSV vulnerability list"
            raise ValueError(message)  # noqa: TRY004 - malformed service evidence
        vulnerabilities.extend(findings)
        token = response.get("next_page_token")
        if token is None:
            return
        if not isinstance(token, str) or not token:
            message = "invalid OSV page token"
            raise ValueError(message)
        payload = {**request, "page_token": token}
    message = f"OSV query did not finish within {_MAX_OSV_PAGES} pages"
    raise ValueError(message)


def query_osv(payload: dict[str, Any]) -> dict[str, Any]:
    """Query the fixed OSV endpoint; transport and decoding failures fail the job."""
    connection = http.client.HTTPSConnection("api.osv.dev", timeout=30)
    try:
        connection.request(
            "POST", "/v1/query", json.dumps(payload), {"Content-Type": "application/json"}
        )
        response = connection.getresponse()
        if response.status != HTTPStatus.OK:
            message = f"OSV returned HTTP {response.status}"
            raise ValueError(message)
        result: dict[str, Any] = json.loads(response.read())
        return result
    finally:
        connection.close()


def main() -> None:
    """Merge source evidence for downstream vulnerability/SBOM/license checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pypi-audit", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    merged = merge_source_audit(
        json.loads(args.pypi_audit.read_text()), args.lock.read_text(), query_osv
    )
    args.output.write_text(json.dumps(merged, indent=2) + "\n")


if __name__ == "__main__":
    main()
