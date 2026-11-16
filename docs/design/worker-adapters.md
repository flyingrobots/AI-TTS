# Worker adapter identity and recovery

An AI-TTS upgrade changes the daemon package but does not replace worker code
already copied into a guided model installation. The model catalog reports
that difference. Refreshing it is an explicit action that reuses the installed
environment and model weights.

This reference is for client and runtime maintainers. The user procedure is in
the [Speech models instructions](../../README.md#multiple-local-engines).

## Catalog and manifest fields

Every model row in `engines.models` and `snapshot.models` includes
`adapter_status`. It is separate from model readiness and selection:

| Value | Meaning |
| --- | --- |
| `null` | No usable private managed runtime is available. An in-process engine can still be installed and ready. |
| `"unknown"` | A usable private runtime has no valid stored adapter identity. Legacy runtimes remain usable. |
| `"stale"` | Its stored identity differs from the daemon package identity. |
| `"current"` | Its stored identity matches the daemon package identity. |

Reading the catalog never schedules setup or changes an installation. The
Swift client accepts an absent field from older daemons as no status; it does
not invent an `unknown` identity. Rust protocol parity belongs to
[#125](https://github.com/flyingrobots/AI-TTS/issues/125), including separate
reference cases for this addition under the
[early-port policy](tech-stack.md#python-feature-policy-during-the-rust-port).

The runtime manifest stores `adapter_sha256` as 64 lowercase hexadecimal
characters. Missing or malformed identity gives `unknown`; it does not make
an otherwise valid runtime unusable. Publication hashes the package actually
copied into that runtime. This identity describes the installed copy at
publication, not a recurring integrity scan of its files.

The canonical digest starts with the bytes `aitts-adapter-v1` followed by a
zero byte. Regular files are ordered by their UTF-8 relative POSIX paths.
Files under `__pycache__` and files with suffix `.pyc` are excluded. For each
remaining file, SHA-256 receives the path byte count as an unsigned 8-byte
big-endian integer, the path bytes, the content byte count in the same format,
and the content bytes. Timestamps, modes and the installation's absolute path
are excluded. This includes package data as well as Python source.

## Explicit setup and recovery

The existing `model_setup` operation and `ai-tts model-setup MODEL` command
remain the entry points; there is no automatic refresh or new request field.

| State when setup is requested | Action |
| --- | --- |
| Healthy usable runtime, stale or unknown adapter | Stage a code-only refresh. |
| Failed setup or failed engine | Perform the existing complete runtime repair, which may download dependencies and weights. |
| Cancelled refresh, healthy incumbent and usable stale or unknown adapter | Retry code-only refresh. |
| Current, ready engine | Return ready without reinstalling. |
| No usable private runtime | Use ordinary setup; code-only refresh is unavailable. |

In **Settings → Speech models**, a usable idle stale or unknown adapter offers
**Retry setup** and a **Refresh worker** confirmation explaining that no model
download is needed. Failure changes the next confirmation to **Download &
install**. This prevents repeatedly copying new code into a broken environment
or reusing damaged assets forever. Existing **Use model** behavior and explicit
selection remain unchanged. Incompatible, loading and installing entries do
not offer code-only refresh.

If a repair is cancelled while the incumbent engine is still failed, the
catalog keeps `state: "failed"` and retains the cancellation message. The next
confirmation therefore continues to describe a full repair. A healthy
incumbent's cancelled refresh reports `cancelled` and remains code-only.

## Refresh publication and retained roots

Refresh creates a separate private candidate root. It copies the daemon's
adapter package and creates direct, resolved links to the previous runtime's
environment and assets inside the managed runtime tree. Repeated refreshes
reuse the original targets rather than building symlink chains. No download,
dependency installation or weight-file mutation occurs on this path.

The candidate warms offline before publication. The daemon then uses the
existing synthesis quiescence boundary, checks cancellation, atomically
replaces the manifest, registers the warmed worker and retires the previous
worker. The incumbent remains available until successful publication.
Staging, warmup and publication failures, or cancellation before publication,
leave the previous manifest, worker and weight bytes intact and remove the
unpublished candidate. Task cancellation waits for the staging thread before
removing its candidate; it cannot abandon that thread to publish later.

Successful refreshes retain previous roots because the new runtime still
references their environment and assets. These roots cannot be deleted merely
because the manifest points at a newer root. Runtime garbage collection is
outside this behavior; any future collector must follow those references.

The automated contract uses owned fake assets and controlled workers. It does
not establish live-model loading or mouse-driven menu behavior. A screenshot
showing the new status and both confirmation paths is not yet available.
This page is agent-written and has not received human editorial review.
