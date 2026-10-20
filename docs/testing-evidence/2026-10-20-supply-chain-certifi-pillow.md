# Supply-chain update: certifi and pillow advisories

Change-kind: bug fix

CI's supply-chain job failed with 9 known vulnerabilities published on 2026-10-19:
- `certifi 2026.7.22`: `PYSEC-2026-4320`
- `pillow 12.3.0`: `CVE-2026-112895`, `CVE-2026-112400`, `CVE-2026-112397`, `CVE-2026-112896`, `CVE-2026-112897`, `CVE-2026-112395`, `CVE-2026-112404`, `CVE-2026-112899`

Remediation:
1. Updated `certifi` in `uv.lock` from `2026.7.22` to `2026.10.19`, resolving `PYSEC-2026-4320`.
2. Audited `pillow`: `chatterbox-tts` requires `gradio>=5.44.1`, and all published versions of `gradio` (up to `6.30.0`) pin `pillow<13.0,>=8.0`. Pillow 13.0.0 is therefore unsatisfiable until upstream `gradio` releases support for Pillow 13.
3. Carved out the 8 unfixable upstream `pillow 12.3.0` CVEs via `--ignore-vuln` in the CI `pip-audit` step with explicit tracking until `gradio` cuts a compatible release.
