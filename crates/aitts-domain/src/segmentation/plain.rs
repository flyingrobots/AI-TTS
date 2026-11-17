// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! ASCII word boundaries and paragraph-aware clip sizing, matching the Python policy.

#![deny(clippy::arithmetic_side_effects)]

use alloc::{borrow::ToOwned, string::String, vec, vec::Vec};
use core::ops::Range;

const TARGET: usize = 180;
const MAXIMUM: usize = 220;

pub(super) fn words(text: &str) -> Vec<Range<usize>> {
    let mut spans = Vec::new();
    let mut start = None;
    for (offset, character) in text.char_indices() {
        if character.is_ascii_alphanumeric() {
            start.get_or_insert(offset);
        } else if let Some(start) = start.take() {
            spans.push(start..offset);
        }
    }
    if let Some(start) = start {
        spans.push(start..text.len());
    }
    spans
}

fn paragraph_breaks(text: &str) -> Vec<Range<usize>> {
    let mut breaks = Vec::new();
    let mut consumed = 0;
    for (newline, _) in text.match_indices('\n') {
        if newline < consumed {
            continue;
        }
        let after = newline.saturating_add(1);
        let tail = text.get(after..).unwrap_or_default();
        let next = tail.trim_start_matches([' ', '\t']);
        let delimiter = if next.starts_with("\r\n") {
            2
        } else if next.starts_with('\n') {
            1
        } else {
            continue;
        };
        let prefix = text.get(..newline).unwrap_or_default();
        let start = if prefix.ends_with('\r') {
            newline.saturating_sub(1)
        } else {
            newline
        };
        consumed = after
            .saturating_add(tail.len().saturating_sub(next.len()))
            .saturating_add(delimiter);
        breaks.push(start..consumed);
    }
    breaks
}

fn paragraphs(text: &str) -> Vec<String> {
    if words(text).len() < 60 {
        return vec![text.to_owned()];
    }
    let mut pieces = Vec::new();
    let mut start = 0;
    for gap in paragraph_breaks(text) {
        pieces.push(text.get(start..gap.start).unwrap_or_default());
        start = gap.end;
    }
    pieces.push(text.get(start..).unwrap_or_default());
    let pieces: Vec<_> = pieces
        .into_iter()
        .map(str::trim)
        .filter(|part| !part.is_empty())
        .collect();
    if pieces.len() <= 1 {
        return vec![text.to_owned()];
    }
    let mut result: Vec<String> = Vec::new();
    let mut pending = Vec::new();
    let mut count: usize = 0;
    for piece in pieces {
        pending.push(piece);
        count = count.saturating_add(words(piece).len());
        if count >= 20 {
            result.push(pending.join("\n\n"));
            pending.clear();
            count = 0;
        }
    }
    if !pending.is_empty()
        && let Some(last) = result.last_mut()
    {
        last.push_str("\n\n");
        last.push_str(&pending.join("\n\n"));
    }
    if result.len() > 1 {
        result
    } else {
        vec![text.to_owned()]
    }
}

fn sections(text: &str) -> Vec<&str> {
    let mut starts = Vec::new();
    let mut offset: usize = 0;
    for line in text.split_inclusive('\n') {
        let head = line.trim_start_matches([' ', '\t']);
        let indentation = line.len().saturating_sub(head.len());
        let hashes = head.bytes().take_while(|byte| *byte == b'#').count();
        if indentation <= 3
            && (1..=6).contains(&hashes)
            && head
                .get(hashes..)
                .is_some_and(|tail| tail.starts_with([' ', '\t']))
        {
            starts.push(offset);
        }
        offset = offset.saturating_add(line.len());
    }
    if starts.is_empty() {
        return vec![text];
    }
    if starts
        .first()
        .is_some_and(|first| !text.get(..*first).unwrap_or_default().trim().is_empty())
    {
        starts.insert(0, 0);
    }
    starts.push(text.len());
    starts
        .windows(2)
        .filter_map(|pair| text.get(*pair.first()?..*pair.last()?))
        .collect()
}

fn sentence_break(gap: &str) -> bool {
    gap.char_indices().any(|(offset, character)| {
        matches!(character, '.' | '!' | '?')
            && gap
                .get(offset.saturating_add(1)..)
                .and_then(|tail| {
                    tail.trim_start_matches([']', ')', '"', '\''])
                        .chars()
                        .next()
                })
                .is_some_and(char::is_whitespace)
    })
}

fn nearest(text: &str, spans: &[Range<usize>], first: usize, paragraph: bool) -> Option<usize> {
    let target = first.saturating_add(TARGET).min(spans.len());
    let minimum = first.saturating_add(90).min(target);
    let maximum = first.saturating_add(MAXIMUM).min(spans.len());
    (minimum..=maximum)
        .filter(|index| {
            let Some(previous) = index.checked_sub(1).and_then(|index| spans.get(index)) else {
                return false;
            };
            let Some(next) = spans.get(*index) else {
                return false;
            };
            let gap = text.get(previous.end..next.start).unwrap_or_default();
            if paragraph {
                !paragraph_breaks(gap).is_empty()
            } else {
                sentence_break(gap)
            }
        })
        .min_by_key(|index| (index.abs_diff(target), *index))
}

fn bounded(text: &str) -> Vec<String> {
    let spans = words(text);
    if spans.len() <= TARGET {
        return if text.trim().is_empty() {
            Vec::new()
        } else {
            vec![text.trim().to_owned()]
        };
    }
    let mut result = Vec::new();
    let mut first = 0;
    let mut character = 0;
    while first < spans.len() {
        if spans.len().saturating_sub(first) <= MAXIMUM {
            result.push(text.get(character..).unwrap_or_default().trim().to_owned());
            break;
        }
        let final_word = nearest(text, &spans, first, true)
            .or_else(|| nearest(text, &spans, first, false))
            .unwrap_or_else(|| first.saturating_add(TARGET));
        let Some(next) = spans.get(final_word) else {
            break;
        };
        result.push(
            text.get(character..next.start)
                .unwrap_or_default()
                .trim()
                .to_owned(),
        );
        character = next.start;
        first = final_word;
    }
    result
}

pub(super) fn segment(text: &str) -> Vec<String> {
    if words(text).len() <= TARGET {
        return paragraphs(text);
    }
    let result: Vec<_> = sections(text)
        .into_iter()
        .flat_map(paragraphs)
        .flat_map(|paragraph| bounded(&paragraph))
        .filter(|part| !part.is_empty())
        .collect();
    if result.is_empty() {
        vec![text.to_owned()]
    } else {
        result
    }
}
