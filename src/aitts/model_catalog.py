# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The curated local speech models offered by guided setup."""

from __future__ import annotations

from dataclasses import dataclass

from aitts.engines.kokoro import VOICES

WORKER_PROTOCOL_VERSION = 1


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


MODELS = {
    model.name: model
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
