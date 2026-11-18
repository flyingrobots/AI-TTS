// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the socket operations that change the queue or the hold.
//!
//! Each operation is sent to the conductor owner through its [`Mailbox`] and
//! answered with the Python daemon's reply shape. The API thread's store
//! connection is used only to classify an identifier the conductor does not
//! hold, such as a history item after a restart.

use aitts_protocol::control_reply::{Cancelled, Cleared, Reordered, Transport};
use aitts_protocol::error_reply::ErrorCode;
use aitts_protocol::reply::Reply;
use aitts_protocol::request::Request;
use aitts_protocol::value::{Nullable, Success};
use aitts_protocol::vocabulary::{ClearQueue, State as WireState};
use aitts_store::Store;

use crate::api::Refusal;
use crate::conductor::durable::DurableError;
use crate::conductor::mailbox::{self, Mailbox};
use crate::conductor::{Command, Outcome, Refusal as Refused};
use crate::projection;

/// Answer `request` if it is a queue or transport operation.
pub(crate) fn answer(
    mailbox: &Mailbox,
    store: &Store,
    request: &Request,
) -> Option<Result<Reply, Refusal>> {
    Some(match request {
        Request::Pause { .. } => transport(mailbox, Command::Pause).map(Reply::Pause),
        Request::Resume { .. } => transport(mailbox, Command::Resume).map(Reply::Resume),
        Request::Cancel { id } => cancel(mailbox, store, id),
        Request::Clear {
            queue: ClearQueue::Queue,
            ..
        } => clear(mailbox),
        Request::Reorder { ids } => reorder(mailbox, ids),
        _ => return None,
    })
}

/// Send one command and read back its outcome.
fn apply(mailbox: &Mailbox, command: Command) -> Result<Result<Outcome, Refused>, Refusal> {
    match mailbox.request(mailbox::Request::Apply(command)) {
        Ok(mailbox::Reply::Applied(Ok(outcome))) => Ok(Ok(outcome)),
        Ok(mailbox::Reply::Applied(Err(DurableError::Refused(refused)))) => Ok(Err(refused)),
        _ => Err(internal()),
    }
}

fn internal() -> Refusal {
    Refusal::new(ErrorCode::Internal, "internal error; see daemon log")
}

/// Take or release the hold, then report the device as Python `_transport_reply`.
fn transport(mailbox: &Mailbox, command: Command) -> Result<Transport, Refusal> {
    apply(mailbox, command)?.map_err(|_| internal())?;
    let Ok(mailbox::Reply::Transport { held, current }) =
        mailbox.request(mailbox::Request::Transport)
    else {
        return Err(internal());
    };
    let (current, state) = match current {
        Some((id, state)) => (
            Nullable::Value(id),
            Nullable::Value(projection::state(state)),
        ),
        None => (Nullable::Null, Nullable::Null),
    };
    Ok(Transport {
        ok: Success,
        state,
        current,
        held,
    })
}

/// Cancel work that is not on the device, as Python `_op_cancel`.
fn cancel(mailbox: &Mailbox, store: &Store, id: &str) -> Result<Reply, Refusal> {
    match apply(mailbox, Command::Cancel(id.to_owned()))? {
        Ok(_) => Ok(Reply::Cancel(Cancelled {
            ok: Success,
            id: id.to_owned(),
            state: WireState::Cancelled,
        })),
        Err(Refused::IllegalState { state, .. }) => Err(illegal_cancel(state)),
        // Not in the conductor: history the restart did not load, or unknown.
        Err(_) => match store.queue().get(id)? {
            Some(row) => Err(illegal_cancel(row.state)),
            None => Err(Refusal::new(
                ErrorCode::NotFound,
                format!("no utterance {id}"),
            )),
        },
    }
}

fn illegal_cancel(state: aitts_store::State) -> Refusal {
    let message = if matches!(
        state,
        aitts_store::State::Playing | aitts_store::State::Paused
    ) {
        "cancel is not legal for a playing utterance; that is 'skip'".to_owned()
    } else {
        format!(
            "cannot cancel an utterance in state {}",
            aitts_store::names::state(state)
        )
    };
    Refusal::new(ErrorCode::IllegalState, message)
}

/// Skip preempted speakers and cancel pending work, as Python `_op_clear`.
fn clear(mailbox: &Mailbox) -> Result<Reply, Refusal> {
    match apply(mailbox, Command::ClearQueue)? {
        Ok(Outcome::Cleared(count)) => Ok(Reply::Clear(Cleared {
            ok: Success,
            cleared: u64::try_from(count).map_err(|_| internal())?,
        })),
        _ => Err(internal()),
    }
}

/// Replace the pending order, as Python `_op_reorder`.
fn reorder(mailbox: &Mailbox, ids: &[String]) -> Result<Reply, Refusal> {
    match apply(mailbox, Command::Reorder(ids.to_vec()))? {
        Ok(_) => Ok(Reply::Reorder(Reordered {
            ok: Success,
            ids: ids.to_vec(),
        })),
        Err(refused) => Err(Refusal::new(ErrorCode::BadRequest, refused.to_string())),
    }
}
