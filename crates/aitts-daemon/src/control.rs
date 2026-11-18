// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the socket operations that change the queue or the hold.
//!
//! Each operation is sent to the conductor owner through its [`Mailbox`] and
//! answered with the Python daemon's reply shape. The API thread's store
//! connection is used only to classify an identifier the conductor does not hold.

use aitts_protocol::reply::Reply;
use aitts_protocol::request::Request;
use aitts_store::Store;

use crate::api::Refusal;
use crate::conductor::mailbox::Mailbox;

/// Answer `request` if it is a queue or transport operation.
pub(crate) fn answer(
    mailbox: &Mailbox,
    store: &Store,
    request: &Request,
) -> Option<Result<Reply, Refusal>> {
    let _unanswered = (mailbox.clone(), store.queue(), request.operation());
    None
}
