// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Spoken punctuation, inline projection, and loose formatting cleanup.

#![deny(clippy::arithmetic_side_effects)]

use super::markdown::{Kind, Node};
use alloc::{borrow::ToOwned, format, string::String, vec::Vec};

pub(super) struct Block {
    pub text: String,
    pub heading: bool,
}

pub(super) fn terminal(mut text: String) -> String {
    if !text.is_empty() && !text.ends_with(['.', '!', '?', ':', ';']) {
        text.push('.');
    }
    text
}

pub(super) fn clean_stars(text: &str) -> String {
    let mut result = String::new();
    let mut remaining = text;
    while let Some(start) = remaining.find('*') {
        let prefix = remaining.get(..start).unwrap_or_default();
        let tail = remaining.get(start..).unwrap_or_default();
        let after_opening = tail.trim_start_matches('*');
        let opening_end = remaining.len().saturating_sub(after_opening.len());
        // Reject embedded openers before searching their tail. Every rejected
        // maximal star run is consumed once; its interior cannot open a match.
        let before = text
            .get(..text.len().saturating_sub(tail.len()))
            .unwrap_or_default();
        let valid_start = before.chars().next_back().is_none_or(char::is_whitespace);
        if !valid_start {
            result.push_str(remaining.get(..opening_end).unwrap_or_default());
            remaining = after_opening;
            continue;
        }
        let inside = after_opening.trim_start();
        let Some(close) = inside.find('*') else {
            break;
        };
        let content = inside.get(..close).unwrap_or_default().trim_end();
        let suffix = inside
            .get(close..)
            .unwrap_or_default()
            .trim_start_matches('*');
        let spaced = suffix.trim_start_matches([' ', '\t']);
        let suffix = if spaced.starts_with(['.', ',', '!', '?', ';', ':']) {
            spaced
        } else {
            suffix
        };
        let valid_end = suffix
            .chars()
            .next()
            .is_none_or(|character| character.is_whitespace() || ".,!?;:)]".contains(character));
        if valid_end {
            result.push_str(prefix);
            if content.chars().any(char::is_alphabetic) {
                result.push_str(content);
            } else {
                // A syntactic numeric match stays literal, but its closing star
                // is consumed just as Python's regex substitution consumes it.
                let matched = tail.len().saturating_sub(suffix.len());
                result.push_str(tail.get(..matched).unwrap_or_default());
            }
            remaining = suffix;
        } else {
            result.push_str(remaining.get(..opening_end).unwrap_or_default());
            remaining = after_opening;
        }
    }
    result.push_str(remaining);
    result
}

fn visit_inline(node: &Node, prose: &mut String, result: &mut String) {
    match node {
        Node::Code(text) => {
            result.push_str(&clean_stars(prose));
            prose.clear();
            result.push_str(text);
        }
        Node::Text(text) => prose.push_str(text),
        Node::Break => prose.push(' '),
        Node::Branch(_, children) => {
            for child in children {
                visit_inline(child, prose, result);
            }
        }
        Node::Rule => {}
    }
}

fn inline(node: &Node) -> String {
    let mut prose = String::new();
    let mut result = String::new();
    visit_inline(node, &mut prose, &mut result);
    result.push_str(&clean_stars(&prose));
    result.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn task_content(text: &str) -> &str {
    for marker in ["[ ]", "[x]", "[X]"] {
        if let Some(rest) = text.strip_prefix(marker)
            && rest.starts_with([' ', '\t'])
        {
            return rest.trim_start_matches([' ', '\t']);
        }
    }
    text
}

fn list(children: &[Node], start: Option<u64>) -> String {
    let mut items = Vec::new();
    for (offset, item) in children.iter().enumerate() {
        let joined = blocks(item)
            .into_iter()
            .map(|block| block.text)
            .filter(|text| !text.is_empty())
            .collect::<Vec<_>>()
            .join(" ");
        let content = task_content(&joined);
        let text = if let Some(start) = start {
            // CommonMark limits list starts to nine digits; usize fits within u128.
            let ordinal =
                u128::from(start).saturating_add(u128::try_from(offset).unwrap_or(u128::MAX));
            format!("{ordinal}. {content}")
        } else {
            content.to_owned()
        };
        items.push(terminal(text));
    }
    items.join("\n")
}

fn table(children: &[Node]) -> String {
    children
        .iter()
        .filter_map(|row| {
            let Node::Branch(Kind::Row, cells) = row else {
                return None;
            };
            let spoken = cells
                .iter()
                .map(inline)
                .filter(|text| !text.is_empty())
                .collect::<Vec<_>>()
                .join(". ");
            if spoken.is_empty() {
                None
            } else {
                Some(terminal(spoken))
            }
        })
        .collect::<Vec<_>>()
        .join("\n")
}

fn raw(children: &[Node]) -> String {
    children
        .iter()
        .filter_map(|node| match node {
            Node::Text(text) | Node::Code(text) => Some(text.as_str()),
            _ => None,
        })
        .collect()
}

pub(super) fn blocks(node: &Node) -> Vec<Block> {
    let Node::Branch(kind, children) = node else {
        return Vec::new();
    };
    let text = match kind {
        Kind::Paragraph | Kind::Cell => Some(inline(node)),
        Kind::Heading => Some(terminal(inline(node))),
        Kind::CodeBlock => Some(raw(children).trim().to_owned()),
        Kind::List(start) => Some(list(children, *start)),
        Kind::Table => Some(table(children)),
        _ => None,
    };
    if let Some(text) = text {
        return alloc::vec![Block {
            text,
            heading: *kind == Kind::Heading
        }];
    }
    // Tight list items have inline children without a Paragraph event.
    let mut result = Vec::new();
    let mut pending = Vec::new();
    for child in children {
        if matches!(
            child,
            Node::Text(_) | Node::Code(_) | Node::Break | Node::Branch(Kind::Inline, _)
        ) {
            pending.push(child);
        } else {
            flush_inline(&mut pending, &mut result);
            result.extend(blocks(child));
        }
    }
    flush_inline(&mut pending, &mut result);
    result
}

fn flush_inline(pending: &mut Vec<&Node>, blocks: &mut Vec<Block>) {
    if pending.is_empty() {
        return;
    }
    let mut prose = String::new();
    let mut result = String::new();
    for node in pending.drain(..) {
        visit_inline(node, &mut prose, &mut result);
    }
    result.push_str(&clean_stars(&prose));
    blocks.push(Block {
        text: result.split_whitespace().collect::<Vec<_>>().join(" "),
        heading: false,
    });
}
