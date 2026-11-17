// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Typed AI-TTS wire messages. This crate does not open sockets or operate a daemon.

#![forbid(unsafe_code)]
#![deny(missing_docs, clippy::print_stdout, clippy::print_stderr, clippy::exit)]

pub mod archive;
mod archive_decode;
pub mod archived_value;
pub mod catalog;
mod codec;
pub mod control_reply;
pub mod error_reply;
pub mod event;
pub mod evidence;
pub mod evidence_fields;
pub mod metrics;
pub mod operation;
pub mod provenance;
pub mod query_reply;
pub mod reply;
pub mod request;
pub mod schema;
pub mod settings;
pub mod snapshot;
pub mod status;
mod strict;
pub mod utterance;
pub mod value;
pub mod vocabulary;

pub use codec::{MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, WireError, decode_request, encode_request};
pub use event::{decode_event, encode_event};
pub use reply::{decode_reply, encode_reply};
pub use request::Request;
pub use schema::wire_schema;
