// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The Markdown AST is adapted to spoken blocks with HTML and linkification disabled.

use super::{InvalidMarkdown, LimitExceeded, Limits, Resource};
use ::markdown::{Constructs, ParseOptions, mdast, to_mdast_bounded};
use alloc::{string::String, string::ToString, vec, vec::Vec};

#[derive(Clone, Copy, Debug, PartialEq)]
pub(super) enum Kind {
    Root,
    Paragraph,
    Heading,
    List(Option<u64>),
    Item,
    Table,
    Row,
    Cell,
    CodeBlock,
    Inline,
    Other,
}

#[derive(Debug)]
pub(super) enum Node {
    Branch(Kind, Vec<Node>),
    Text(String),
    Code(String),
    Break,
    Rule,
}

pub(super) fn parse(body: &str, limits: Limits) -> Result<(Node, bool), InvalidMarkdown> {
    let options = ParseOptions {
        constructs: Constructs {
            html_flow: false,
            html_text: false,
            gfm_table: true,
            gfm_strikethrough: true,
            ..Constructs::default()
        },
        gfm_strikethrough_single_tilde: false,
        ..ParseOptions::default()
    };
    let parser_limits = ::markdown::limits::Limits {
        bytes: limits.input_bytes,
        depth: limits.depth,
        nodes: limits.nodes,
        events: limits.events,
        work: limits.work,
    };
    let tree = to_mdast_bounded(body, &options, parser_limits).map_err(parser_error)?;
    let plain = is_plain(&tree);
    Ok((adapt(&tree), plain))
}

fn parser_error(error: ::markdown::limits::Error) -> InvalidMarkdown {
    match error {
        ::markdown::limits::Error::UnsupportedOptions => {
            InvalidMarkdown::Parser("unsupported bounded parser options".into())
        }
        ::markdown::limits::Error::Parse(message) => InvalidMarkdown::Parser(message.to_string()),
        ::markdown::limits::Error::Limit(limit) => {
            let resource = match limit.resource {
                ::markdown::limits::Resource::Bytes => Resource::InputBytes,
                ::markdown::limits::Resource::Depth => Resource::Depth,
                ::markdown::limits::Resource::Nodes => Resource::Nodes,
                markdown::limits::Resource::Events => Resource::Events,
                ::markdown::limits::Resource::Work => Resource::Work,
            };
            InvalidMarkdown::Limit(LimitExceeded {
                resource,
                observed: limit.observed,
                maximum: limit.maximum,
            })
        }
    }
}

fn is_plain(node: &mdast::Node) -> bool {
    matches!(
        node,
        mdast::Node::Root(_) | mdast::Node::Paragraph(_) | mdast::Node::Text(_)
    ) && node
        .children()
        .is_none_or(|children| children.iter().all(is_plain))
}

fn adapt(node: &mdast::Node) -> Node {
    let kind = match node {
        mdast::Node::Root(_) => Kind::Root,
        mdast::Node::Paragraph(_) => Kind::Paragraph,
        mdast::Node::Heading(_) => Kind::Heading,
        mdast::Node::List(list) => Kind::List(if list.ordered {
            list.start.map(u64::from)
        } else {
            None
        }),
        mdast::Node::ListItem(_) => Kind::Item,
        mdast::Node::Table(_) => Kind::Table,
        mdast::Node::TableRow(_) => Kind::Row,
        mdast::Node::TableCell(_) => Kind::Cell,
        mdast::Node::Text(text) => return Node::Text(text.value.clone()),
        mdast::Node::InlineCode(code) => return Node::Code(code.value.clone()),
        mdast::Node::Code(code) => {
            return Node::Branch(
                Kind::CodeBlock,
                vec![Node::Text(
                    code.value.replace("\r\n", "\n").replace('\r', "\n"),
                )],
            );
        }
        mdast::Node::Image(image) => {
            return Node::Branch(Kind::Inline, vec![Node::Text(image.alt.clone())]);
        }
        mdast::Node::ImageReference(image) => {
            return Node::Branch(Kind::Inline, vec![Node::Text(image.alt.clone())]);
        }
        mdast::Node::Emphasis(_)
        | mdast::Node::Strong(_)
        | mdast::Node::Delete(_)
        | mdast::Node::Link(_)
        | mdast::Node::LinkReference(_) => Kind::Inline,
        mdast::Node::Break(_) => return Node::Break,
        mdast::Node::ThematicBreak(_) | mdast::Node::Definition(_) => return Node::Rule,
        _ => Kind::Other,
    };
    Node::Branch(
        kind,
        node.children()
            .map_or_else(Vec::new, |children| children.iter().map(adapt).collect()),
    )
}

pub(super) fn without_front_matter(text: &str) -> &str {
    let mut lines = text.split_inclusive(python_line_end);
    let Some(first) = lines.next() else {
        return text;
    };
    if trim_python(first.trim_start_matches('\u{feff}')) != "---" {
        return text;
    }
    let mut remaining = text.get(first.len()..).unwrap_or_default();
    for line in lines {
        remaining = remaining.get(line.len()..).unwrap_or_default();
        if matches!(trim_python(line), "---" | "...") {
            return remaining.trim_start_matches(['\r', '\n']);
        }
    }
    text
}

fn python_line_end(character: char) -> bool {
    matches!(
        character,
        '\n' | '\r' | '\u{b}' | '\u{c}' | '\u{1c}'..='\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}'
    )
}

fn trim_python(text: &str) -> &str {
    text.trim_matches(|character: char| {
        character.is_whitespace() || matches!(character, '\u{1c}'..='\u{1f}')
    })
}
