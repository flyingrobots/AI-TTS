# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The curated local speech models offered by guided setup."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from aitts.engines.kokoro import VOICES

if TYPE_CHECKING:
    from collections.abc import Mapping

WORKER_PROTOCOL_VERSION = 1

# SHA-256 of each allowlisted file at its pinned revision, taken from the Hugging Face
# LFS object ids (or the file bytes for small non-LFS files). A revision pin alone
# trusts the server and transport; these digests are checked before any file is loaded.
_DIGESTS: dict[str, dict[str, str]] = json.loads(
    (Path(__file__).parent / "model_digests.json").read_text(encoding="utf-8")
)


class ModelIntegrityError(ValueError):
    """A downloaded model file is missing or differs from its pinned digest."""


@dataclass(frozen=True)
class LocalModel:
    """A supported runtime and immutable model snapshot, not arbitrary install input."""

    name: str
    title: str
    description: str
    repository: str
    revision: str
    files: tuple[str, ...]
    voices: tuple[str, ...] = VOICES
    apple_silicon: bool = False
    sha256: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def verify_assets(self, assets: Path) -> None:
        """Refuse a snapshot unless every allowlisted file matches its pinned digest."""
        for filename in self.files:
            path = assets / filename
            expected = self.sha256.get(filename)
            if expected is None or path.is_symlink() or not path.is_file():
                message = f"model integrity check failed: {filename}"
                raise ModelIntegrityError(message)
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != expected:
                message = f"model integrity check failed: {filename}"
                raise ModelIntegrityError(message)


def _pinned(model: LocalModel) -> LocalModel:
    digests = _DIGESTS[model.name]
    return replace(model, sha256=MappingProxyType({file: digests[file] for file in model.files}))


MODELS = {
    model.name: _pinned(model)
    for model in (
        LocalModel(
            "kokoro",
            "Kokoro",
            "Compact speech model with multiple voices and languages.",
            "hexgrad/Kokoro-82M",
            "f3ff3571791e39611d31c381e3a41a3af07b4987",
            ("config.json", "kokoro-v1_0.pth", *tuple(f"voices/{v}.pt" for v in VOICES)),
        ),
        LocalModel(
            "kokoro-mlx",
            "Kokoro · Apple Silicon",
            "The same Kokoro voices, accelerated with Apple's MLX framework.",
            "mlx-community/Kokoro-82M-bf16",
            "a71e4d38b236d968966a2002c4c895dbd12b1c3c",
            (
                "config.json",
                "kokoro-v1_0.safetensors",
                *tuple(f"voices/{v}.safetensors" for v in VOICES),
            ),
            apple_silicon=True,
        ),
        LocalModel(
            "chatterbox",
            "Chatterbox Turbo",
            "An alternative local speech model with one built-in voice.",
            "ResembleAI/chatterbox-turbo",
            "749d1c1a46eb10492095d68fbcf55691ccf137cd",
            (
                "ve.safetensors",
                "t3_turbo_v1.safetensors",
                "s3gen_meanflow.safetensors",
                "conds.pt",
                "tokenizer_config.json",
                "vocab.json",
                "merges.txt",
                "added_tokens.json",
                "special_tokens_map.json",
            ),
            voices=("default",),
        ),
    )
}
