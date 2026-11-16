// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! A single JSON Schema for requests, replies, and subscription events.

use crate::{Request, event::Event, reply::Reply};
use schemars::{JsonSchema, Schema};
use serde::Serialize;

/// Any one wire message. Decode replies with their originating operation.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, JsonSchema)]
#[serde(untagged)]
pub enum WireMessage {
    /// A client request.
    Request(Box<Request>),
    /// An operation's response.
    Reply(Box<Reply>),
    /// An asynchronous subscription event.
    Event(Box<Event>),
}

/// Export the JSON Schema for the entire supported message vocabulary.
///
/// Encoded-line size, aggregate archival budgets, and daemon business policy
/// are enforced outside JSON Schema, as described in the crate contract.
pub fn wire_schema() -> Schema {
    schemars::schema_for!(WireMessage)
}
