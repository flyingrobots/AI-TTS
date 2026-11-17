// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns one request and one reply per connection, with a time limit.

use crate::error::ClientError;
use crate::subscription::{ReconnectPolicy, Subscription};
use aitts_protocol::Request;
use aitts_protocol::reply::Reply;
use std::path::PathBuf;
use std::time::Duration;

/// A client for the daemon at one socket path. It holds no open connection.
#[derive(Clone, Debug)]
pub struct Client {
    pub(crate) socket: PathBuf,
    pub(crate) limit: Duration,
}

impl Client {
    /// A client that waits at most `limit` for each connect, write, and reply line.
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
    #[expect(
        clippy::todo,
        reason = "RED stub, replaced by the implementation commit"
    )]
    pub fn request(&self, request: &Request) -> Result<Reply, ClientError> {
        let _ = (&self.socket, self.limit, request);
        todo!()
    }

    /// Subscribe now; the returned stream subscribes again after a failure.
    ///
    /// # Errors
    /// [`ClientError`] when the first subscription is not acknowledged.
    #[expect(
        clippy::todo,
        reason = "RED stub, replaced by the implementation commit"
    )]
    pub fn subscribe(&self, policy: ReconnectPolicy) -> Result<Subscription, ClientError> {
        let _ = policy;
        todo!()
    }
}
