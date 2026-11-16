// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the engine-neutral spoken projection and bounded text segments.

use alloc::{string::String, vec::Vec};
use core::fmt;

mod limits;
mod markdown;
mod plain;
mod spoken;

pub use limits::{LimitExceeded, Limits, Resource};

/// Explicit input format. A missing format preserves the legacy Markdown behavior.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ContentFormat {
    /// Preserve markup as literal text.
    PlainText,
    /// Render Markdown into spoken blocks before segmentation.
    Markdown,
}

/// A parser refusal, retained as an error instead of silently changing the spoken text.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum InvalidMarkdown {
    /// The parser refused the input.
    Parser(String),
    /// The submitted input or parser growth exceeded the requested policy.
    Limit(LimitExceeded),
    /// A requested policy exceeds the hard resource ceilings.
    Policy(LimitExceeded),
}

impl fmt::Display for InvalidMarkdown {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Parser(message) => formatter.write_str(message),
            Self::Limit(limit) | Self::Policy(limit) => write!(
                formatter,
                "{:?}: observed {}, maximum {}",
                limit.resource, limit.observed, limit.maximum
            ),
        }
    }
}
impl core::error::Error for InvalidMarkdown {}

/// Project submitted text into ordered speech segments, without engine or file access.
///
/// # Errors
/// Propagates a Markdown parser refusal. Plain text does not use the parser.
pub fn prepare(text: &str, format: Option<ContentFormat>) -> Result<Vec<String>, InvalidMarkdown> {
    prepare_with_limits(text, format, Limits::default())
}

/// Allocate an ordered spoken projection under an explicit lower resource budget.
///
/// # Errors
/// Refuses an invalid policy, exceeded resource limit, or parser error without partial output.
pub fn prepare_with_limits(
    text: &str,
    format: Option<ContentFormat>,
    limits: Limits,
) -> Result<Vec<String>, InvalidMarkdown> {
    limits.validate().map_err(InvalidMarkdown::Policy)?;
    if text.len() > limits.input_bytes {
        return Err(InvalidMarkdown::Limit(LimitExceeded {
            resource: Resource::InputBytes,
            observed: text.len(),
            maximum: limits.input_bytes,
        }));
    }
    if format == Some(ContentFormat::PlainText) {
        return Ok(plain::segment(text));
    }
    let body = markdown::without_front_matter(text);
    let (tree, is_plain) = markdown::parse(body, limits)?;
    if is_plain {
        return Ok(plain::segment(&spoken::clean_stars(body)));
    }
    let mut result = Vec::new();
    let mut section = Vec::new();
    for block in spoken::blocks(&tree) {
        if block.heading && !section.is_empty() {
            result.extend(plain::segment(&section.join("\n\n")));
            section.clear();
        }
        if !block.text.is_empty() {
            section.push(block.text);
        }
    }
    if !section.is_empty() {
        result.extend(plain::segment(&section.join("\n\n")));
    }
    result.retain(|text| !text.trim().is_empty());
    Ok(result)
}
