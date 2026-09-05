# Security Policy

## Reporting a vulnerability

Report security issues privately through
[GitHub Security Advisories](https://github.com/flyingrobots/AI-TTS/security/advisories/new)
rather than opening a public issue.

Please include what you were doing, what happened, and how to reproduce it. You
will get an acknowledgement within a few days.

## Scope and threat model

AI-TTS runs locally on a single user's machine and speaks text that clients hand
it. The security properties that matter most here are:

- **The text is sensitive.** It is work product — names, identifiers, internal
  detail. Anything that logs, transmits, or persists it is in scope.
- **The history store and audio cache hold everything ever spoken.** They live on
  local disk, are never committed, and should be readable only by the owning
  user.
- **The IPC surface accepts text from local clients.** Anything that widens that
  beyond the local user — a network listener, loose socket permissions, a path
  traversal in a cache key — is in scope.
- **Any cloud engine path sends text to a third party.** A change that routes
  text off-machine without the user's explicit configuration is a vulnerability,
  not a feature.

Out of scope: the quality or behaviour of third-party TTS models themselves, and
anything requiring an attacker who already has the user's local account.

## Build and dependency evidence

GitHub Actions runs with a read-only token, immutable action commit pins,
non-persisted checkout credentials, and a fixed `uv` version. Project commands
consume `uv.lock` with `--frozen`.

The supply-chain job separately exports the hashed, all-extras runtime graph
for the minimum supported Python, audits every applicable package against the
PyPI advisory service, emits a CycloneDX 1.5 SBOM, and inventories installed
license metadata. A repository verifier refuses empty reports,
vulnerabilities, or dependencies missing from either the SBOM or license
inventory. The reports, lock digest, and exact tool versions are retained as a
short-lived CI artifact; they contain package metadata, not speech or user
state.

This automation is evidence, not a legal compatibility opinion. The current
lock still reports `phonemizer-fork` as GPLv3+, `num2words` as LGPL, and
`espeakng-loader` with unknown license metadata. AI-TTS therefore keeps its
source-only boundary and must not bundle or redistribute the Kokoro Python
environment until that distribution decision is reviewed and recorded.
