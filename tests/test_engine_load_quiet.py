# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Loading the model must not bury a real warning under upstream noise.

Building the Kokoro model raises ninety-odd warnings from inside torch, about
torch APIs this project does not call, in code it does not own. There is
nothing an operator can do with any of them, and that is the problem: a wall
of unactionable noise at first speech is how a warning that *does* matter goes
unread. The repository's standing rule is zero warnings, and the only honest
way to hold it over third-party code is to silence exactly the known ones and
leave everything else audible.
"""

from __future__ import annotations

import warnings

import pytest

from aitts.engines.kokoro import quiet_upstream_model_load

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("the repository's zero-warnings rule in CLAUDE.md"),
]

UPSTREAM = [
    pytest.param(
        "`torch.nn.utils.weight_norm` is deprecated in favor of "
        "`torch.nn.utils.parametrizations.weight_norm`.",
        FutureWarning,
        id="weight_norm",
    ),
    pytest.param(
        "`torch.jit.script` is deprecated. Please switch to `torch.compile` or `torch.export`.",
        DeprecationWarning,
        id="jit_script",
    ),
    pytest.param(
        "dropout option adds dropout after all but last recurrent layer, so non-zero dropout "
        "expects num_layers greater than 1",
        UserWarning,
        id="rnn_dropout",
    ),
]


@pytest.mark.parametrize(("message", "category"), UPSTREAM)
def test_a_known_upstream_load_warning_is_silenced(message: str, category: type[Warning]) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with quiet_upstream_model_load():
            warnings.warn(message, category, stacklevel=1)

    # Each of these is raised many times by one model load; they are what the
    # suppression exists for.
    assert [str(entry.message) for entry in caught] == []


def test_an_unrecognised_warning_is_still_heard() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with quiet_upstream_model_load():
            warnings.warn("the cache directory is not writable", UserWarning, stacklevel=1)

    # A blanket suppression around the model load would swallow this too, and
    # then the rule is being met by not listening.
    assert [str(entry.message) for entry in caught] == ["the cache directory is not writable"]


def test_a_warning_of_the_same_category_but_another_subject_is_still_heard() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with quiet_upstream_model_load():
            warnings.warn("`aitts.legacy` is deprecated", DeprecationWarning, stacklevel=1)

    # Filtering by category alone would silence every future deprecation this
    # project is warned about, which is the deprecation it most needs to hear.
    assert [str(entry.message) for entry in caught] == ["`aitts.legacy` is deprecated"]


def test_the_suppression_does_not_outlive_the_load() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with quiet_upstream_model_load():
            pass
        warnings.warn(
            "`torch.jit.script` is deprecated. Please switch to `torch.compile`.",
            DeprecationWarning,
            stacklevel=1,
        )

    # The filter is installed for the load and no longer: a process-wide
    # filterwarnings call would quietly change what the whole suite hears.
    assert len(caught) == 1
