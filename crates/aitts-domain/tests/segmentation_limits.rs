// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: small. Oracle: explicit input, AST-depth, node, and shared-work budgets.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]
use aitts_domain::segmentation::{
    ContentFormat, InvalidMarkdown, LimitExceeded, Limits, Resource, prepare, prepare_with_limits,
};

#[test]
fn byte_admission_is_inclusive_and_precedes_projection() {
    let limits = Limits {
        input_bytes: 4,
        ..Limits::default()
    };
    assert_eq!(
        prepare_with_limits("éé", Some(ContentFormat::PlainText), limits).unwrap(),
        ["éé"]
    );
    assert_eq!(
        prepare_with_limits("éé!", Some(ContentFormat::PlainText), limits),
        Err(InvalidMarkdown::Limit(LimitExceeded {
            resource: Resource::InputBytes,
            observed: 5,
            maximum: 4
        }))
    );
}

#[test]
fn depth_node_and_work_limits_are_distinct_refusals() {
    for (limits, resource) in [
        (
            Limits {
                depth: 1,
                ..Limits::default()
            },
            Resource::Depth,
        ),
        (
            Limits {
                nodes: 2,
                ..Limits::default()
            },
            Resource::Nodes,
        ),
        (
            Limits {
                work: 0,
                ..Limits::default()
            },
            Resource::Work,
        ),
    ] {
        let error =
            prepare_with_limits("hello", Some(ContentFormat::Markdown), limits).unwrap_err();
        assert!(
            matches!(error, InvalidMarkdown::Limit(limit) if limit.resource == resource),
            "{error:?}"
        );
    }
}

#[test]
fn flat_documents_do_not_consume_a_document_wide_nesting_quota() {
    for text in ["# Heading\n\n".repeat(257), "- Item\n".repeat(257)] {
        assert_ne!(
            prepare(&text, Some(ContentFormat::Markdown)).unwrap(),
            Vec::<String>::new()
        );
    }
}

#[test]
fn structural_limits_accept_the_boundary_and_refuse_the_next_node() {
    for (text, limits, resource, observed, maximum) in [
        (
            "hello",
            Limits {
                nodes: 2,
                ..Limits::default()
            },
            Resource::Nodes,
            3,
            2,
        ),
        (
            "> > hello",
            Limits {
                depth: 3,
                ..Limits::default()
            },
            Resource::Depth,
            4,
            3,
        ),
    ] {
        assert_eq!(
            prepare_with_limits(text, Some(ContentFormat::Markdown), limits),
            Err(InvalidMarkdown::Limit(LimitExceeded {
                resource,
                observed,
                maximum
            }))
        );
        let accepted = match resource {
            Resource::Nodes => Limits {
                nodes: observed,
                ..limits
            },
            Resource::Depth => Limits {
                depth: observed,
                ..limits
            },
            _ => limits,
        };
        assert_eq!(
            prepare_with_limits(text, Some(ContentFormat::Markdown), accepted).unwrap(),
            ["hello"]
        );
    }
}

#[test]
fn work_admission_is_shared_across_parser_phases_and_child_tokenizers() {
    // Find the smallest budget for a fixed public input. Its exact value is an
    // internal parser detail; inclusive admission and accumulation are contracts.
    let text = "> Hello **reader**.\n\n- Second paragraph.";
    let mut low = 0;
    let mut high = 10_000;
    while low < high {
        let middle = low + (high - low) / 2;
        let limits = Limits {
            work: middle,
            ..Limits::default()
        };
        match prepare_with_limits(text, Some(ContentFormat::Markdown), limits) {
            Ok(_) => high = middle,
            Err(InvalidMarkdown::Limit(limit)) if limit.resource == Resource::Work => {
                assert_eq!(limit.observed, middle + 1);
                low = middle + 1;
            }
            other => panic!("unexpected result: {other:?}"),
        }
    }
    assert!(low > 0 && low < 10_000);
    assert_eq!(
        prepare_with_limits(
            text,
            Some(ContentFormat::Markdown),
            Limits {
                work: low,
                ..Limits::default()
            }
        )
        .unwrap(),
        ["Hello reader.\n\nSecond paragraph."]
    );
    assert_eq!(
        prepare_with_limits(
            text,
            Some(ContentFormat::Markdown),
            Limits {
                work: low - 1,
                ..Limits::default()
            }
        ),
        Err(InvalidMarkdown::Limit(LimitExceeded {
            resource: Resource::Work,
            observed: low,
            maximum: low - 1
        }))
    );
    // More child tokenizers and AST events share the same finite allowance.
    let doubled = format!("{text}\n\n{text}");
    assert!(
        matches!(prepare_with_limits(&doubled, Some(ContentFormat::Markdown), Limits { work: low, ..Limits::default() }), Err(InvalidMarkdown::Limit(limit)) if limit.resource == Resource::Work)
    );
}

#[test]
fn nested_cpu_witness_is_refused_before_materializing_a_deep_tree() {
    let text = format!("{}hello", "> ".repeat(16_381));
    assert_eq!(text.len(), 32_767);
    assert_eq!(
        prepare(&text, Some(ContentFormat::Markdown)),
        Err(InvalidMarkdown::Limit(LimitExceeded {
            resource: Resource::Depth,
            observed: 129,
            maximum: 128
        }))
    );
}

#[test]
fn default_byte_allowance_is_one_mib_for_plain_and_shallow_markdown() {
    // Size: medium. A shallow document near the transport limit must remain usable.
    let text = "x".repeat(1_048_576);
    for format in [ContentFormat::PlainText, ContentFormat::Markdown] {
        assert_eq!(prepare(&text, Some(format)).unwrap(), [text.as_str()]);
        assert_eq!(
            prepare(&(text.clone() + "x"), Some(format)),
            Err(InvalidMarkdown::Limit(LimitExceeded {
                resource: Resource::InputBytes,
                observed: 1_048_577,
                maximum: 1_048_576
            }))
        );
    }
}

#[test]
fn caller_policies_cannot_raise_hard_ceilings() {
    for (limits, resource, observed, maximum) in [
        (
            Limits {
                input_bytes: 1_048_577,
                ..Limits::default()
            },
            Resource::InputBytes,
            1_048_577,
            1_048_576,
        ),
        (
            Limits {
                depth: 129,
                ..Limits::default()
            },
            Resource::Depth,
            129,
            128,
        ),
        (
            Limits {
                nodes: 65_537,
                ..Limits::default()
            },
            Resource::Nodes,
            65_537,
            65_536,
        ),
        (
            Limits {
                work: 64_000_001,
                ..Limits::default()
            },
            Resource::Work,
            64_000_001,
            64_000_000,
        ),
    ] {
        assert_eq!(
            prepare_with_limits("", None, limits),
            Err(InvalidMarkdown::Policy(LimitExceeded {
                resource,
                observed,
                maximum
            }))
        );
    }
}
