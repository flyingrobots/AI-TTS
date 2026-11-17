//! AI-TTS local modification: parser-owned resource admission.
//!
//! Original markdown 1.0.0 remains MIT licensed. See the package PATCH.md.

use crate::message::Message;
use alloc::{boxed::Box, format, string::ToString};
use core::cell::Cell;

/// Limits for one complete parse, shared across every child tokenizer and AST buffer.
#[derive(Clone, Copy, Debug)]
pub struct Limits {
    pub bytes: usize,
    pub depth: usize,
    pub nodes: usize,
    pub events: usize,
    pub work: usize,
}

/// The resource refused by the bounded parser.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Resource {
    Bytes,
    Depth,
    Nodes,
    Events,
    Work,
}

/// An admission failure, before retaining the next object or doing the next unit of work.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LimitExceeded {
    pub resource: Resource,
    pub observed: usize,
    pub maximum: usize,
}

/// A bounded-parser result distinguishes resource refusals from Markdown diagnostics.
#[derive(Debug)]
pub enum Error {
    Limit(LimitExceeded),
    Parse(Message),
    UnsupportedOptions,
}

#[derive(Debug)]
pub(crate) struct Budget {
    pub limits: Limits,
    work: Cell<usize>,
    nodes: Cell<usize>,
    events: Cell<usize>,
    failure: Cell<Option<LimitExceeded>>,
}

impl Budget {
    pub fn new(limits: Limits) -> Self {
        Self {
            limits,
            work: Cell::new(0),
            nodes: Cell::new(0),
            events: Cell::new(0),
            failure: Cell::new(None),
        }
    }

    pub fn check(
        &self,
        resource: Resource,
        observed: usize,
        maximum: usize,
    ) -> Result<(), Message> {
        if observed > maximum {
            let failure = LimitExceeded {
                resource,
                observed,
                maximum,
            };
            if self.failure.get().is_none() {
                self.failure.set(Some(failure));
            }
            return Err(Message {
                place: None,
                reason: format!("{:?}: observed {}, maximum {}", resource, observed, maximum),
                rule_id: Box::new("resource-limit".to_string()),
                source: Box::new("markdown-rs-aitts".to_string()),
            });
        }
        Ok(())
    }

    pub fn depth(&self, depth: usize) -> Result<(), Message> {
        self.check(Resource::Depth, depth, self.limits.depth)
    }

    pub fn node(&self, depth: usize) -> Result<(), Message> {
        self.depth(depth)?;
        let next = self.nodes.get().saturating_add(1);
        self.check(Resource::Nodes, next, self.limits.nodes)?;
        self.nodes.set(next);
        Ok(())
    }

    pub fn events(&self, count: usize) -> Result<(), Message> {
        let next = self.events.get().saturating_add(count);
        self.check(Resource::Events, next, self.limits.events)?;
        self.events.set(next);
        Ok(())
    }

    pub fn tick(&self) -> Result<(), Message> {
        self.spend(1)
    }

    pub fn spend(&self, count: usize) -> Result<(), Message> {
        let next = self.work.get().saturating_add(count);
        self.check(Resource::Work, next, self.limits.work)?;
        self.work.set(next);
        Ok(())
    }

    pub fn error(&self, message: Message) -> Error {
        match self.failure.get() {
            Some(failure) => Error::Limit(failure),
            None => Error::Parse(message),
        }
    }
}
