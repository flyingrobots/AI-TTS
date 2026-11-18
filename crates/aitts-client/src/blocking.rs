// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns one request and one reply per connection, with a time limit.

use crate::error::ClientError;
use crate::line::LineReader;
use crate::subscription::{ReconnectPolicy, Subscription};
use aitts_protocol::reply::{Reply, decode_reply};
use aitts_protocol::{Request, encode_request};
use std::path::PathBuf;
use std::time::Duration;

/// A client for the daemon at one socket path. It holds no open connection.
#[derive(Clone, Debug)]
pub struct Client {
    pub(crate) socket: PathBuf,
    pub(crate) limit: Duration,
}

impl Client {
    /// A client that waits at most `limit` for each socket read and write.
    pub fn new(socket: impl Into<PathBuf>, limit: Duration) -> Self {
        Self {
            socket: socket.into(),
            limit,
        }
    }

    /// Send `request` on a new connection and decode its one reply line.
    ///
    /// A daemon `ok: false` reply is returned as [`Reply::Error`], not as an error.
    ///
    /// # Errors
    /// [`ClientError`] when the daemon is unreachable, silent, closes early, or
    /// sends a line that does not decode as the reply to this operation.
    pub fn request(&self, request: &Request) -> Result<Reply, ClientError> {
        let line = encode_request(request).map_err(ClientError::Wire)?;
        let reply = LineReader::connect(&self.socket, self.limit, &line)?.next_line()?;
        decode_reply(request.operation(), &reply).map_err(ClientError::Wire)
    }

    /// Subscribe now; the returned stream subscribes again after a failure.
    ///
    /// # Errors
    /// [`ClientError`] when the first subscription is not acknowledged.
    pub fn subscribe(&self, policy: ReconnectPolicy) -> Result<Subscription, ClientError> {
        Subscription::open(self.clone(), policy)
    }

    /// As [`Client::subscribe`], with `playback_progress` events as well.
    ///
    /// # Errors
    /// [`ClientError`] when the first subscription is not acknowledged.
    #[allow(clippy::todo, reason = "RED stub")]
    pub fn subscribe_to_progress(
        &self,
        _policy: ReconnectPolicy,
    ) -> Result<Subscription, ClientError> {
        todo!()
    }
}
