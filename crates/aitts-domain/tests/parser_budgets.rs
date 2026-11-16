// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium. Oracle: bounded parsing preserves the unlimited admitted projection,
//! or returns a typed refusal without partial output or a cleanup panic.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]
use aitts_domain::segmentation::{
    ContentFormat, InvalidMarkdown, LimitExceeded, Limits, Resource, prepare, prepare_with_limits,
};

#[test]
fn every_small_work_budget_returns_output_or_a_typed_refusal() {
    // Size: medium. Exercise refusal during tokenization, container exits,
    // resolvers, event-map updates and AST construction, including cleanup.
    for text in [
        "> Hello **reader**.\n\n- Second paragraph.",
        "[text](https://example.invalid) **strong**",
        "| A | B |\n|---|---|\n| one | two |",
        "- one\n- two\n\n# End",
    ] {
        let expected = prepare(text, Some(ContentFormat::Markdown)).unwrap();
        for work in 0..1024 {
            match prepare_with_limits(
                text,
                Some(ContentFormat::Markdown),
                Limits {
                    work,
                    ..Limits::default()
                },
            ) {
                Ok(actual) => assert_eq!(actual, expected),
                Err(error) => assert!(
                    matches!(
                        error,
                        InvalidMarkdown::Limit(LimitExceeded {
                            resource: Resource::Work,
                            ..
                        })
                    ),
                    "{error:?}"
                ),
            }
        }
    }
}

#[test]
fn event_budgets_refuse_growth_in_every_parser_phase() {
    for text in [
        "> Hello **reader**.\n\n- Second paragraph.",
        "[text](https://example.invalid) **strong**",
        "| A | B |\n|---|---|\n| one | two |",
    ] {
        let expected = prepare(text, Some(ContentFormat::Markdown)).unwrap();
        let mut boundary = None;
        for events in 0..512 {
            match prepare_with_limits(
                text,
                Some(ContentFormat::Markdown),
                Limits {
                    events,
                    ..Limits::default()
                },
            ) {
                Ok(actual) => {
                    assert_eq!(actual, expected);
                    boundary.get_or_insert(events);
                }
                Err(error) => assert!(
                    matches!(
                        error,
                        InvalidMarkdown::Limit(LimitExceeded {
                            resource: Resource::Events,
                            ..
                        })
                    ),
                    "{error:?}"
                ),
            }
        }
        let boundary = boundary.unwrap();
        assert!(boundary > 0 && boundary < 512);
        assert!(
            matches!(prepare_with_limits(text, Some(ContentFormat::Markdown), Limits { events: boundary - 1, ..Limits::default() }), Err(InvalidMarkdown::Limit(limit)) if limit.resource == Resource::Events && limit.observed > limit.maximum)
        );
    }
    assert_eq!(
        prepare_with_limits(
            "",
            None,
            Limits {
                events: 4_194_305,
                ..Limits::default()
            }
        ),
        Err(InvalidMarkdown::Policy(LimitExceeded {
            resource: Resource::Events,
            observed: 4_194_305,
            maximum: 4_194_304
        }))
    );
}

#[test]
fn shallow_prose_near_one_mib_preserves_all_words() {
    // Size: medium. Ordinary shallow text exercises word/segment allocations.
    let text = "word ".repeat(209_715);
    assert_eq!(text.len(), 1_048_575);
    let result = prepare(&text, Some(ContentFormat::Markdown)).unwrap();
    assert_eq!(
        result
            .iter()
            .map(|part| part.split_whitespace().count())
            .sum::<usize>(),
        209_715
    );
    for part in result {
        assert!(part.split_whitespace().count() <= 220);
        assert!(part.split_whitespace().all(|word| word == "word"));
    }
}

#[test]
fn unmatched_closers_charge_the_backward_attention_scan() {
    let text = "a* ".repeat(2_000);
    assert_eq!(
        prepare_with_limits(
            &text,
            Some(ContentFormat::Markdown),
            Limits {
                work: 200_000,
                ..Limits::default()
            }
        ),
        Err(InvalidMarkdown::Limit(LimitExceeded {
            resource: Resource::Work,
            observed: 200_001,
            maximum: 200_000
        }))
    );
}

#[test]
fn repeated_parser_actions_share_counters() {
    for (limits, resource, maximum) in [
        (
            Limits {
                work: 4,
                ..Limits::default()
            },
            Resource::Work,
            4,
        ),
        (
            Limits {
                events: 2,
                ..Limits::default()
            },
            Resource::Events,
            2,
        ),
    ] {
        assert_eq!(
            prepare_with_limits("hello", Some(ContentFormat::Markdown), limits),
            Err(InvalidMarkdown::Limit(LimitExceeded {
                resource,
                observed: maximum + 1,
                maximum
            }))
        );
    }
}

mod support;
use proptest::prelude::*;
proptest! {
    #![proptest_config(support::config())]
    #[test]
    fn generated_lower_budgets_preserve_projection_or_refuse(
        parts in prop::collection::vec(prop::sample::select(vec!["word", " ", "\n", "*", "_", "[", "]", "(", ")", "> ", "- ", "# ", "`", "|", "~"]), 0..48),
        work in 0usize..4096, events in 0usize..2048, depth in 0usize..16, nodes in 0usize..32,
    ) {
        let text = parts.concat();
        let expected = prepare(&text, Some(ContentFormat::Markdown)).unwrap();
        match prepare_with_limits(&text, Some(ContentFormat::Markdown), Limits { work, events, depth, nodes, ..Limits::default() }) {
            Ok(actual) => prop_assert_eq!(actual, expected),
            Err(error) => prop_assert!(matches!(error, InvalidMarkdown::Limit(_)), "{error:?}"),
        }
    }
}

#[test]
fn event_map_scans_share_the_parser_work_budget() {
    let text = "# Heading\n\n".repeat(257);
    assert!(
        matches!(prepare_with_limits(&text, Some(ContentFormat::Markdown), Limits { work: 200_000, ..Limits::default() }), Err(InvalidMarkdown::Limit(limit)) if limit.resource == Resource::Work && limit.maximum == 200_000)
    );
}

#[test]
fn repeated_emphasis_charges_bulk_moves_before_the_ast_depth_check() {
    let text = format!("{}x{}", "*".repeat(4_096), "*".repeat(4_096));
    assert!(
        matches!(prepare_with_limits(&text, Some(ContentFormat::Markdown), Limits { work: 1_000_000, ..Limits::default() }), Err(InvalidMarkdown::Limit(limit)) if limit.resource == Resource::Work && limit.maximum == 1_000_000)
    );
}
