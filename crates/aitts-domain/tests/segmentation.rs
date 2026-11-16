// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: small. Oracle: the unchanged, independently authored 40-case Python corpus.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]
use aitts_domain::segmentation::{ContentFormat, prepare};
use proptest::prelude::*;
use serde::Deserialize;
mod support;

#[derive(Deserialize)]
struct Corpus {
    schema_version: u32,
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    content_format: Option<String>,
    text: String,
    segments: Vec<String>,
}

#[test]
fn html_disabled_projection_still_parses_inner_markdown() {
    // Independently inspected literals, then checked against the Python public API.
    let cases = [
        ("<div>\n**bold**\n</div>", vec!["<div> bold </div>"]),
        (
            "<div>\n`<literal>` and [link](https://example.invalid)\n</div>",
            vec!["<div> <literal> and link </div>"],
        ),
        (
            "<div>\n\n# Heading\n\n</div>",
            vec!["<div>", "Heading.\n\n</div>"],
        ),
        (
            "<!-- *comment* -->\n\nHello.",
            vec!["<!-- comment -->\n\nHello."],
        ),
    ];
    for (input, expected) in cases {
        assert_eq!(
            prepare(input, Some(ContentFormat::Markdown)).unwrap(),
            expected,
            "{input}"
        );
    }
}

#[test]
fn loose_emphasis_cleanup_preserves_arithmetic_code_and_multiline_prose() {
    // These expectations are independently readable and also match Python's focused tests.
    for (input, expected) in [
        (
            "Here is * bold * text and ** spaced ** emphasis.",
            "Here is bold text and spaced emphasis.",
        ),
        ("2 * 3 * 4", "2 * 3 * 4"),
        ("Use `* literal *` here.", "Use * literal * here."),
        (
            "---\ntitle: ignored\n---\n** first\nsecond **",
            "first\nsecond",
        ),
        ("** spaced **.", "spaced."),
        ("** spaced ** .", "spaced."),
    ] {
        assert_eq!(
            prepare(input, Some(ContentFormat::Markdown)).unwrap(),
            vec![expected],
            "{input}"
        );
    }
}

#[test]
fn embedded_star_runs_keep_original_preceding_character_context() {
    // Python's cleanup requires whitespace before the entire opening star run.
    for input in ["1** hello **", "hello** world **", "a*** loose ***"] {
        assert_eq!(
            prepare(input, Some(ContentFormat::Markdown)).unwrap(),
            vec![input]
        );
    }
}

#[test]
fn all_forty_existing_golden_cases_match_exact_strings_and_boundaries() {
    let corpus: Corpus = serde_json::from_str(include_str!(
        "../../../tests/corpus/segmentation/cases.json"
    ))
    .unwrap();
    assert_eq!(corpus.schema_version, 1);
    assert_eq!(corpus.cases.len(), 40);
    let mut mismatches = Vec::new();
    for case in corpus.cases {
        let format = match case.content_format.as_deref() {
            Some("plain_text") => Some(ContentFormat::PlainText),
            Some("markdown") => Some(ContentFormat::Markdown),
            None => None,
            unknown => panic!("unsupported corpus format {unknown:?}"),
        };
        let actual = prepare(&case.text, format).unwrap();
        if actual != case.segments {
            mismatches.push(format!(
                "{}: expected {:?}; got {:?}",
                case.id, case.segments, actual
            ));
        }
    }
    assert!(
        mismatches.is_empty(),
        "{} corpus mismatches:\n{}",
        mismatches.len(),
        mismatches.join("\n")
    );
}

proptest! {
    #![proptest_config(support::config())]
    #[test]
    fn generated_plain_words_are_preserved_in_order_and_bounded(words in prop::collection::vec("word[0-9]{1,4}", 0..500), paragraphs in any::<bool>()) {
        let separator = if paragraphs { "\n\n" } else { " " };
        let text = words.join(separator);
        let segments = prepare(&text, Some(ContentFormat::PlainText)).unwrap();
        let actual: Vec<_> = segments.iter().flat_map(|segment| segment.split_whitespace()).collect();
        prop_assert_eq!(actual, words.iter().map(String::as_str).collect::<Vec<_>>());
        prop_assert!(!segments.is_empty());
        for segment in segments { prop_assert!(segment.split_whitespace().count() <= 220); }
    }
}
