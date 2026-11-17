// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Bounded one-object JSON-line encoding and decoding, without a socket transport.

#![deny(clippy::arithmetic_side_effects)]

use crate::request::Request;
use core::fmt;
use serde::Serialize;
use std::io::{self, Write};

/// Maximum request bytes, including an optional final newline, matching Python IPC.
pub const MAX_REQUEST_BYTES: usize = 1_048_576;

/// Local admission ceiling for a reply or event, including its final newline.
pub const MAX_RESPONSE_BYTES: usize = 16 * 1_048_576;

pub(crate) fn decode<T: serde::de::DeserializeOwned>(line: &[u8]) -> Result<T, WireError> {
    if line.len() > MAX_RESPONSE_BYTES {
        return Err(WireError::TooLarge);
    }
    serde_json::from_slice(line).map_err(|_| WireError::InvalidMessage)
}

/// A typed framing or data refusal. It never retains submitted text or field values.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WireError {
    /// The serialized line exceeds its explicit byte budget.
    TooLarge,
    /// Invalid JSON syntax or unsupported value kinds, without payload content.
    InvalidMessage,
}
impl fmt::Display for WireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::TooLarge => "wire message exceeds its byte limit",
            Self::InvalidMessage => "message does not match the wire contract",
        })
    }
}
impl std::error::Error for WireError {}

/// Parse one request after checking its complete encoded size.
///
/// # Errors
/// Refuses over-limit input, malformed JSON/UTF-8, unknown fields, and wrong value kinds.
pub fn decode_request(line: &[u8]) -> Result<Request, WireError> {
    if line.len() > MAX_REQUEST_BYTES {
        return Err(WireError::TooLarge);
    }
    serde_json::from_slice(line).map_err(|_| WireError::InvalidMessage)
}

struct LimitedBytes {
    bytes: Vec<u8>,
    limit: usize,
    exceeded: bool,
}
impl Write for LimitedBytes {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if self
            .bytes
            .len()
            .checked_add(bytes.len())
            .is_none_or(|size| size > self.limit)
        {
            self.exceeded = true;
            return Err(io::Error::other("wire byte limit exceeded"));
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
pub(crate) fn encode<T: Serialize>(value: &T, limit: usize) -> Result<Vec<u8>, WireError> {
    let mut output = LimitedBytes {
        bytes: Vec::new(),
        limit: limit.saturating_sub(1),
        exceeded: false,
    };
    if serde_json::to_writer(&mut output, value).is_err() {
        return Err(if output.exceeded {
            WireError::TooLarge
        } else {
            WireError::InvalidMessage
        });
    }
    output.bytes.push(b'\n');
    Ok(output.bytes)
}

/// Encode a request with exactly one final newline and bounded output allocation.
///
/// # Errors
/// Refuses a request whose serialized line exceeds the request byte budget.
pub fn encode_request(request: &Request) -> Result<Vec<u8>, WireError> {
    encode(request, MAX_REQUEST_BYTES)
}
