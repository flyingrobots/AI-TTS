// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: medium. Oracle: literal escaped stars remain literal after Markdown projection.
//! The large input must complete within the generous two-second projection regression bound.

#![allow(clippy::unwrap_used, reason = "test code fails loudly")]

use aitts_domain::segmentation::{ContentFormat, prepare};
use proptest::prelude::*;
use std::time::{Duration, Instant};
mod support;

#[test]
fn rejected_literal_star_runs_have_bounded_projection_time() {
    for count in [128, 512, 2_048, 8_192, 32_000] {
        let input = format!("# H\n\na{} x *", "\\*".repeat(count));
        let expected = format!("H.\n\na{} x *", "*".repeat(count));
        let started = Instant::now();
        let actual = prepare(&input, Some(ContentFormat::Markdown)).unwrap();
        assert_eq!(actual, vec![expected]);
        assert!(
            started.elapsed() < Duration::from_secs(2),
            "projection repeatedly rescanned the rejected {count}-star run"
        );
    }
}

proptest! {
    #![proptest_config(support::config())]
    #[test]
    fn generated_embedded_star_runs_preserve_every_literal_marker(
        prefix in "[A-Za-z0-9]{1,6}", count in 1usize..2_048,
    ) {
        let input = format!("# H\n\n{prefix}{} x *", "\\*".repeat(count));
        let expected = format!("H.\n\n{prefix}{} x *", "*".repeat(count));
        prop_assert_eq!(prepare(&input, Some(ContentFormat::Markdown)).unwrap(), vec![expected]);
    }
}
