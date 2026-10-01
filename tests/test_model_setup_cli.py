# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

import pytest

from aitts.cli import _build_parser, _payload_for

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("documented local model CLI commands map to the daemon setup contract"),
]


@pytest.mark.parametrize("name", ["kokoro", "kokoro-mlx", "chatterbox"])
def test_model_setup_projects_only_the_curated_model_name(name: str) -> None:
    args = _build_parser().parse_args(["model-setup", name])
    assert _payload_for(args) == {"op": "model_setup", "name": name}


def test_model_setup_cancellation_maps_to_the_active_job() -> None:
    args = _build_parser().parse_args(["cancel-model-setup"])
    assert _payload_for(args) == {"op": "cancel_model_setup"}


def test_cli_refuses_arbitrary_package_or_model_install_input() -> None:
    with pytest.raises(SystemExit) as rejected:
        _build_parser().parse_args(["model-setup", "https://untrusted.example/model"])
    assert rejected.value.code == 2
