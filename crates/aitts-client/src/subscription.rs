// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the event stream and its reconnection after a failure.

use crate::error::ClientError;
use aitts_protocol::event::Event;
use std::time::Duration;

/// How a subscription connects again after its connection fails.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ReconnectPolicy {
    /// The wait before each new attempt after the first.
    pub delay: Duration,
    /// The attempts made before the failure is returned.
    pub attempts: u32,
}

/// One item of a subscription stream.
#[derive(Clone, Debug, PartialEq)]
pub enum Delivery {
    /// An event from the daemon.
    Event(Event),
    /// The connection failed and a new subscription is acknowledged. Events sent
    /// between the two connections are lost, so a caller reads current state again.
    Resubscribed,
}

/// A live subscription. It reads events with the client's time limit.
#[derive(Debug)]
pub struct Subscription {
    pub(crate) policy: ReconnectPolicy,
}

impl Subscription {
    /// Wait for the next event, subscribing again if the connection failed.
    ///
    /// # Errors
    /// [`ClientError::TimedOut`] when the daemon is quiet for the time limit;
    /// [`ClientError::Wire`] for a line that is not an event; the last connect
    /// failure when every reconnection attempt fails.
    #[expect(
        clippy::todo,
        reason = "RED stub, replaced by the implementation commit"
    )]
    pub fn next_delivery(&mut self) -> Result<Delivery, ClientError> {
        let _ = self.policy;
        todo!()
    }
}
