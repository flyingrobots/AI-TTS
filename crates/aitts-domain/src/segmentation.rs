// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the engine-neutral spoken projection and bounded text segments.

use alloc::{string::String, vec::Vec};
use core::fmt;

mod markdown;
mod plain;
mod spoken;

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
pub struct InvalidMarkdown(String);

impl fmt::Display for InvalidMarkdown {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}
impl core::error::Error for InvalidMarkdown {}

/// Project submitted text into ordered speech segments, without engine or file access.
///
/// # Errors
/// Propagates a Markdown parser refusal. Plain text does not use the parser.
pub fn prepare(text: &str, format: Option<ContentFormat>) -> Result<Vec<String>, InvalidMarkdown> {
    if format == Some(ContentFormat::PlainText) {
        return Ok(plain::segment(text));
    }
    let body = markdown::without_front_matter(text);
    let (tree, is_plain) = markdown::parse(body)?;
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
