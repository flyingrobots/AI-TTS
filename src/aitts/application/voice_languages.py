# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Language metadata and the listener's automatic voice pool."""

from collections.abc import Sequence

LANGUAGE_CODES = ("en", "es", "fr", "hi", "it", "pt", "ja", "zh", "other")
_PREFIX_LANGUAGES = dict(
    zip("abefhipjz", ("en", "en", "es", "fr", "hi", "it", "pt", "ja", "zh"), strict=True)
)


def voice_language(voice: str) -> str:
    """Read Kokoro's documented language prefix; other catalogs lack this metadata."""
    if voice[3:] and voice[1:3] in {"f_", "m_"}:
        return _PREFIX_LANGUAGES.get(voice[0], "other")
    return "other"


def automatic_voice_pool(catalog: Sequence[str], languages: Sequence[str]) -> list[str]:
    """Filter language-aware catalogs, leaving metadata-free backends usable."""
    if all(voice_language(voice) == "other" for voice in catalog):
        return list(catalog)
    return [voice for voice in catalog if voice_language(voice) in languages]


def stored_voice_languages(raw: str) -> list[str]:
    """Read a saved language selection, with English as the safe default."""
    selected = raw.split(",")
    return selected if selected and all(code in LANGUAGE_CODES for code in selected) else ["en"]
