// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns accepted connections: line framing, subscription, and replies.
//!
//! Framing follows the Python `IPCServer`: one JSON object per line of at most
//! `MAX_REQUEST_BYTES`, including its newline. A longer line gets a `bad_request`
//! reply and the connection closes. Bytes left at end of input are one last line.

use std::collections::BTreeMap;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::mpsc::{Sender, sync_channel};
use std::sync::{Arc, Mutex, PoisonError};

use aitts_protocol::control_reply::Subscribed;
use aitts_protocol::error_reply::ErrorCode;
use aitts_protocol::reply::{Reply, encode_reply};
use aitts_protocol::value::Success;
use aitts_protocol::{MAX_REQUEST_BYTES, Request, WireError, decode_request};

use crate::api::{Job, Refusal};
use crate::subscribers::{Subscribers, Writer, lock};

/// State every connection thread shares with the runtime.
#[derive(Default)]
pub(crate) struct Shared {
    pub(crate) stopping: AtomicBool,
    pub(crate) clients: Mutex<BTreeMap<u64, UnixStream>>,
    pub(crate) subscribers: Subscribers,
    pub(crate) jobs: Mutex<Option<Sender<Job>>>,
    pub(crate) live_connections: AtomicUsize,
    next_connection: AtomicU64,
}

impl Shared {
    /// Close every open connection so its thread ends.
    pub(crate) fn close_all(&self) {
        for stream in self.clients().values() {
            let _closed = stream.shutdown(Shutdown::Both);
        }
    }

    fn clients(&self) -> std::sync::MutexGuard<'_, BTreeMap<u64, UnixStream>> {
        self.clients.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

/// Serve `stream` on its own thread.
pub(crate) fn spawn(stream: UnixStream, shared: &Arc<Shared>) {
    let id = shared.next_connection.fetch_add(1, Ordering::Relaxed);
    let Ok(registered) = stream.try_clone() else {
        return;
    };
    shared.clients().insert(id, registered);
    shared.live_connections.fetch_add(1, Ordering::SeqCst);
    let owner = Arc::clone(shared);
    let spawned = std::thread::Builder::new()
        .name("ai-ttsd-client".to_owned())
        .spawn(move || {
            serve(id, stream, &owner);
            owner.subscribers.remove(id);
            owner.clients().remove(&id);
            owner.live_connections.fetch_sub(1, Ordering::SeqCst);
        });
    if spawned.is_err() {
        shared.clients().remove(&id);
        shared.live_connections.fetch_sub(1, Ordering::SeqCst);
    }
}

fn serve(id: u64, stream: UnixStream, shared: &Shared) {
    if shared.stopping.load(Ordering::SeqCst) {
        return;
    }
    let Ok(output) = stream.try_clone() else {
        return;
    };
    let writer: Writer = Arc::new(Mutex::new(output));
    let mut reader = BufReader::new(stream);
    loop {
        let mut line = Vec::new();
        let limit = u64::try_from(MAX_REQUEST_BYTES)
            .unwrap_or(u64::MAX)
            .saturating_add(1);
        match (&mut reader).take(limit).read_until(b'\n', &mut line) {
            Ok(0) | Err(_) => return,
            Ok(_) => {}
        }
        if line.len() > MAX_REQUEST_BYTES {
            let _ = send(&writer, &too_large());
            return;
        }
        if !answer(id, &line, &writer, shared) {
            return;
        }
    }
}

/// Reply to one line; false when the connection can no longer be written.
fn answer(id: u64, line: &[u8], writer: &Writer, shared: &Shared) -> bool {
    match decode_request(line) {
        Err(WireError::TooLarge) => send(writer, &too_large()),
        Err(WireError::InvalidMessage) => send(
            writer,
            &Refusal::new(
                ErrorCode::BadRequest,
                "request does not match the wire contract",
            )
            .into_reply(),
        ),
        Ok(Request::Subscribe { .. }) => {
            let acknowledged = send(
                writer,
                &Reply::Subscribe(Subscribed {
                    ok: Success,
                    subscribed: Success,
                }),
            );
            acknowledged && shared.subscribers.add(id, writer).is_ok()
        }
        Ok(request) => send(writer, &ask(request, shared)),
    }
}

fn ask(request: Request, shared: &Shared) -> Reply {
    let (answer, reply) = sync_channel(1);
    let queued = shared
        .jobs
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .as_ref()
        .is_some_and(|jobs| jobs.send(Job { request, answer }).is_ok());
    if !queued {
        return Refusal::new(ErrorCode::Internal, "daemon is stopping").into_reply();
    }
    reply
        .recv()
        .unwrap_or_else(|_| Refusal::new(ErrorCode::Internal, "daemon is stopping").into_reply())
}

fn too_large() -> Reply {
    Refusal::new(ErrorCode::BadRequest, "request line too large").into_reply()
}

fn send(writer: &Writer, reply: &Reply) -> bool {
    let line = encode_reply(reply).or_else(|_| {
        encode_reply(
            &Refusal::new(ErrorCode::Internal, "reply exceeds the wire limit").into_reply(),
        )
    });
    line.is_ok_and(|line| lock(writer).write_all(&line).is_ok())
}
