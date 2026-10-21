# Supply-chain update: certifi and pillow advisories

Change-kind: bug fix

CI's supply-chain job failed with 9 known vulnerabilities published on 2026-10-19:
- `certifi 2026.7.22`: `PYSEC-2026-4320` (`GHSA-6q48-6c7w-9gw2`)
- `pillow 12.3.0`: `CVE-2026-112895`, `CVE-2026-112400`, `CVE-2026-112397`, `CVE-2026-112896`, `CVE-2026-112897`, `CVE-2026-112395`, `CVE-2026-112404`, `CVE-2026-112899`

## Remediation

1. **`certifi`**: Updated in `uv.lock` from `2026.7.22` to `2026.10.19`. Added regression test `tests/test_certifi_dependency_security.py` asserting that `"emSign ECC Root CA - G3"` is excluded from `certifi.contents()`. Fails against `certifi 2026.7.22` (where the root was bundled) and passes on `2026.10.19`.
2. **`pillow`**: `chatterbox-tts` requires `gradio>=5.44.1`, and all published versions of `gradio` (up to `6.30.0`) pin `pillow<13.0,>=8.0`. Pillow 13.0.0 is therefore unsatisfiable until upstream `gradio` releases support for Pillow 13.
3. Carved out the 8 unfixable upstream `pillow 12.3.0` CVEs via `--ignore-vuln` in the CI `pip-audit` step with explicit tracking until `gradio` cuts a compatible release.
