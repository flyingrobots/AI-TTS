// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Reproducible property configuration; an explicit runner seed overrides the default.

use proptest::test_runner::{Config, RngSeed};

pub(super) fn config() -> Config {
    let mut config = Config {
        cases: 128,
        max_shrink_iters: 2_048,
        ..Config::default()
    };
    if matches!(config.rng_seed, RngSeed::Random) {
        config.rng_seed = RngSeed::Fixed(130);
    }
    config
}
