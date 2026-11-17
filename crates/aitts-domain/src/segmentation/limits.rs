// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Admission policy for a bounded speech projection, before input-derived allocation.

/// The resource whose admission limit was exceeded.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Resource {
    /// Submitted UTF-8 bytes, before front-matter removal.
    InputBytes,
    /// Parser container or AST nesting depth.
    Depth,
    /// AST nodes, including temporary buffers and the root.
    Nodes,
    /// Cumulative parser events and edit records admitted before allocation.
    Events,
    /// Shared parser state transitions, resolver calls, and AST event visits.
    Work,
}

/// A precise resource refusal. No partial spoken projection is returned.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LimitExceeded {
    /// Resource being admitted.
    pub resource: Resource,
    /// Requested or next observed amount.
    pub observed: usize,
    /// Maximum permitted amount.
    pub maximum: usize,
}

/// A lower-budget policy. Values cannot exceed the default hard ceilings.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Limits {
    /// Maximum submitted UTF-8 bytes. The default preserves the one-MiB wire allowance.
    pub input_bytes: usize,
    /// Maximum parser-container and AST nesting depth.
    pub depth: usize,
    /// Maximum AST node allocations, including temporary buffers.
    pub nodes: usize,
    /// Maximum parser events and edit records across tokenizers and resolvers.
    pub events: usize,
    /// Maximum shared parser work units.
    pub work: usize,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            input_bytes: 1_048_576,
            depth: 128,
            nodes: 65_536,
            events: 4_194_304,
            work: 64_000_000,
        }
    }
}

impl Limits {
    pub(super) fn validate(self) -> Result<(), LimitExceeded> {
        let maximum = Self::default();
        for (resource, observed, maximum) in [
            (Resource::InputBytes, self.input_bytes, maximum.input_bytes),
            (Resource::Depth, self.depth, maximum.depth),
            (Resource::Nodes, self.nodes, maximum.nodes),
            (Resource::Events, self.events, maximum.events),
            (Resource::Work, self.work, maximum.work),
        ] {
            if observed > maximum {
                return Err(LimitExceeded {
                    resource,
                    observed,
                    maximum,
                });
            }
        }
        Ok(())
    }
}
