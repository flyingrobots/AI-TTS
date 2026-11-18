// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns waiting for an utterance's terminal state, as
//! `aitts.client.Client.wait_for_terminal` does: subscribe first, then read the
//! current state, then read events until a terminal `state_changed` arrives.

use crate::{EXIT_NOT_PLAYED, EXIT_OK, Failed, exchange, failure};
use aitts_client::{Client, ClientError, Delivery, ReconnectPolicy};
use aitts_protocol::event::Event;
use aitts_protocol::vocabulary::State;
use serde_json::{Value, json};
use std::path::Path;
use std::time::{Duration, Instant};

/// One read waits at most this long before the deadline is checked again.
const POLL: Duration = Duration::from_millis(500);

const fn terminal(state: State) -> bool {
    matches!(
        state,
        State::Played | State::Skipped | State::Cancelled | State::Failed
    )
}

/// Exit 0 only for `Played`.
pub(crate) fn status(state: State) -> u8 {
    if state == State::Played {
        EXIT_OK
    } else {
        EXIT_NOT_PLAYED
    }
}

fn late(id: &str, timeout: Option<f64>) -> Failed {
    let seconds = timeout.unwrap_or_default();
    let message = format!("utterance {id} did not finish within {seconds}s");
    Failed(crate::EXIT_UNREACHABLE, failure("unreachable", &message))
}

fn current(socket: &Path, id: &str) -> Result<State, Failed> {
    let reply = exchange(socket, &json!({"op": "get", "id": id}))?;
    serde_json::from_value(reply.pointer("/item/state").cloned().unwrap_or(Value::Null)).map_err(
        |error| {
            Failed(
                crate::EXIT_DAEMON_ERROR,
                failure("internal", &error.to_string()),
            )
        },
    )
}

/// Block until utterance `id` is terminal, or until `timeout` seconds pass.
pub(crate) fn final_state(socket: &Path, id: &str, timeout: Option<f64>) -> Result<State, Failed> {
    let limit = timeout
        .and_then(|seconds| Duration::try_from_secs_f64(seconds).ok())
        .map_or(POLL, |limit| limit.min(POLL))
        .max(Duration::from_millis(1));
    let deadline = timeout.map(|seconds| {
        Instant::now() + Duration::try_from_secs_f64(seconds).unwrap_or(Duration::ZERO)
    });
    let policy = ReconnectPolicy {
        delay: Duration::ZERO,
        attempts: 1,
    };
    let mut events = Client::new(socket, limit)
        .subscribe(policy)
        .map_err(crate::client_failure)?;
    let mut state = current(socket, id)?;
    while !terminal(state) {
        if deadline.is_some_and(|deadline| Instant::now() >= deadline) {
            return Err(late(id, timeout));
        }
        match events.next_delivery() {
            Ok(Delivery::Event(Event::StateChanged {
                id: changed, to, ..
            })) if changed == id => {
                state = to;
            }
            // Events sent while disconnected are lost, so read the state again.
            Ok(Delivery::Resubscribed) => state = current(socket, id)?,
            Ok(Delivery::Event(_)) | Err(ClientError::TimedOut | ClientError::Wire(_)) => {}
            Err(error) => return Err(crate::client_failure(error)),
        }
    }
    Ok(state)
}
