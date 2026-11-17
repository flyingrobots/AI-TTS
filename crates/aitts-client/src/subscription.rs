// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the event stream and its reconnection after a failure.

use crate::blocking::Client;
use crate::error::ClientError;
use crate::line::LineReader;
use aitts_protocol::event::{Event, decode_event};
use aitts_protocol::operation::Operation;
use aitts_protocol::reply::{Reply, decode_reply};
use std::time::Duration;

const SUBSCRIBE: &[u8] = b"{\"op\":\"subscribe\"}\n";

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
    client: Client,
    policy: ReconnectPolicy,
    /// `None` after a failure, until a reconnection succeeds.
    connection: Option<LineReader>,
}

fn acknowledged(client: &Client) -> Result<LineReader, ClientError> {
    let mut connection = LineReader::connect(&client.socket, client.limit, SUBSCRIBE)?;
    match decode_reply(Operation::Subscribe, &connection.next_line()?) {
        Ok(Reply::Subscribe(_)) => Ok(connection),
        Ok(Reply::Error(refusal)) => Err(ClientError::Refused(refusal.error.r#type)),
        Ok(_) => Err(ClientError::Wire(aitts_protocol::WireError::InvalidMessage)),
        Err(error) => Err(ClientError::Wire(error)),
    }
}

impl Subscription {
    pub(crate) fn open(client: Client, policy: ReconnectPolicy) -> Result<Self, ClientError> {
        let connection = Some(acknowledged(&client)?);
        Ok(Self {
            client,
            policy,
            connection,
        })
    }

    /// Wait for the next event, subscribing again if the connection failed.
    ///
    /// # Errors
    /// [`ClientError::TimedOut`] when the daemon is quiet for the time limit;
    /// [`ClientError::Wire`] for a line that is not an event; the last connect
    /// failure when every reconnection attempt fails.
    pub fn next_delivery(&mut self) -> Result<Delivery, ClientError> {
        if let Some(connection) = &mut self.connection {
            match connection.next_line() {
                Ok(line) => {
                    return decode_event(&line)
                        .map(Delivery::Event)
                        .map_err(ClientError::Wire);
                }
                Err(ClientError::TimedOut) => return Err(ClientError::TimedOut),
                Err(ClientError::Wire(error)) => {
                    // An unframed stream cannot be resynchronized; the next call reconnects.
                    self.connection = None;
                    return Err(ClientError::Wire(error));
                }
                Err(_) => self.connection = None,
            }
        }
        self.reconnect()
    }

    fn reconnect(&mut self) -> Result<Delivery, ClientError> {
        let mut last = ClientError::Closed;
        for attempt in 0..self.policy.attempts {
            if attempt > 0 {
                std::thread::sleep(self.policy.delay);
            }
            match acknowledged(&self.client) {
                Ok(connection) => {
                    self.connection = Some(connection);
                    return Ok(Delivery::Resubscribed);
                }
                Err(error) => last = error,
            }
        }
        Err(last)
    }
}
