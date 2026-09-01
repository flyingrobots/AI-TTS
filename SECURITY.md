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
