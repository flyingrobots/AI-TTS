# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Selected-language voice assignment contracts at the registry boundary."""

import pytest

from aitts.engine import FakeEngine
from aitts.ipc import ApiError
from aitts.settings import SettingsService
from aitts.store import Store
from aitts.voice_registry import VoiceRegistry
from tests.test_settings_service import FakeEnvironment

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle(
        "user-selected voice languages: exhaust the selected pool by reusing a voice"
    ),
]


def registry(store: Store) -> VoiceRegistry:
    return VoiceRegistry(
        store,
        FakeEngine(voices=["af_heart", "bm_daniel", "ef_dora"]),
        default_voice=lambda: "af_heart",
        announce=lambda _: None,
    )


def test_default_pool_reuses_english_instead_of_allocating_spanish(store: Store) -> None:
    voices = registry(store)
    actual = [voices.resolve(source=f"agent-{index}", requested=None) for index in range(5)]
    assert actual == ["af_heart", "bm_daniel", "af_heart", "af_heart", "af_heart"]


def test_selected_spanish_pool_repeats_and_persists(store: Store) -> None:
    settings = SettingsService(store, FakeEnvironment(voices=("af_heart", "bm_daniel", "ef_dora")))
    settings.apply({"voice_languages": ["es"]})
    assert settings.values()["voice_languages"] == ["es"]
    voices = registry(store)
    assert [voices.resolve(source=f"agent-{index}", requested=None) for index in range(3)] == [
        "ef_dora"
    ] * 3
    restored = SettingsService(store, FakeEnvironment())
    assert restored.values()["voice_languages"] == ["es"]


def test_disabled_automatic_assignment_is_reallocated(store: Store) -> None:
    store.claim_voice("old-agent", "ef_dora")
    assert registry(store).resolve(source="old-agent", requested=None) == "af_heart"
    assignment = store.voice_assignment("old-agent")
    assert assignment is not None
    assert assignment.voice == "af_heart"


def test_listener_pin_remains_an_explicit_override(store: Store) -> None:
    store.pin_voice("pinned-agent", "ef_dora")
    assert registry(store).resolve(source="pinned-agent", requested=None) == "ef_dora"


def test_client_cannot_request_a_disabled_language(store: Store) -> None:
    with pytest.raises(ApiError, match="outside selected voice languages"):
        registry(store).resolve(source="agent", requested="ef_dora")
    assert store.voice_assignment("agent") is None


@pytest.mark.parametrize("value", [[], ["xx"], [1], "en", None, ["es"]])
def test_invalid_or_unavailable_language_selection_is_atomic(store: Store, value: object) -> None:
    settings = SettingsService(store, FakeEnvironment())
    before = settings.values()
    with pytest.raises(ApiError):
        settings.apply({"speed": 1.5, "voice_languages": value})
    assert settings.values() == before


def test_multiple_selected_languages_share_one_bounded_pool(store: Store) -> None:
    store.set_setting("voice_languages", "en,es")
    voices = registry(store)
    assert [voices.resolve(source=f"agent-{index}", requested=None) for index in range(4)] == [
        "af_heart",
        "bm_daniel",
        "ef_dora",
        "af_heart",
    ]


def test_metadata_free_backend_keeps_its_catalog(store: Store) -> None:
    voices = VoiceRegistry(
        store,
        FakeEngine(voices=["default"]),
        default_voice=lambda: "default",
        announce=lambda _: None,
    )
    assert voices.resolve(source="agent", requested=None) == "default"


class LanguageEngineEnvironment(FakeEnvironment):
    def engine_voices(self, name: str) -> list[str]:
        return ["ef_dora"] if name == "kokoro-mlx" else super().engine_voices(name)

    def available_voices(self) -> list[str]:
        return self.engine_voices(self.engine)

    def default_voice(self) -> str:
        return self.available_voices()[0]


def test_engine_switch_preserves_a_usable_stored_language_selection(store: Store) -> None:
    environment = LanguageEngineEnvironment()
    settings = SettingsService(store, environment)
    before = settings.values()
    with pytest.raises(ApiError, match="selected languages have no voices"):
        settings.apply({"engine": "kokoro-mlx", "speed": 1.5})
    assert settings.values() == before


def test_engine_and_compatible_language_can_change_together(store: Store) -> None:
    settings = SettingsService(store, LanguageEngineEnvironment())
    settings.apply({"engine": "kokoro-mlx", "voice_languages": ["es"]})
    assert settings.values()["engine"] == "kokoro-mlx"
    assert settings.values()["voice_languages"] == ["es"]
