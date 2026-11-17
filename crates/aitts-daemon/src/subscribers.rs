// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns event fan-out to subscribed connections.
//!
//! Each subscriber has a bounded backlog drained by its own writer thread. A
//! broadcast never waits on a socket: when a backlog is full, that subscriber is
//! closed, so it cannot hold up the others and its client knows it missed events.

use std::io::Write;
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::sync::mpsc::{Receiver, SyncSender, TrySendError, sync_channel};
use std::sync::{Arc, Mutex, PoisonError};

/// Event lines a subscriber may fall behind before it is closed.
pub(crate) const BACKLOG_EVENTS: usize = 256;

/// The writer half of a connection, shared by replies and events.
pub(crate) type Writer = Arc<Mutex<UnixStream>>;

struct Subscriber {
    connection: u64,
    backlog: SyncSender<Arc<[u8]>>,
    stream: UnixStream,
}

/// Every subscribed connection.
#[derive(Default)]
pub(crate) struct Subscribers {
    members: Mutex<Vec<Subscriber>>,
}

impl Subscribers {
    /// Subscribe `connection`, whose writer already sent the acknowledgement.
    pub(crate) fn add(&self, connection: u64, writer: &Writer) -> std::io::Result<()> {
        let stream = lock(writer).try_clone()?;
        let (backlog, events) = sync_channel(BACKLOG_EVENTS);
        let output = Arc::clone(writer);
        std::thread::Builder::new()
            .name("ai-ttsd-subscriber".to_owned())
            .spawn(move || drain(&events, &output))?;
        let mut members = self.members.lock().unwrap_or_else(PoisonError::into_inner);
        members.retain(|member| member.connection != connection);
        members.push(Subscriber {
            connection,
            backlog,
            stream,
        });
        Ok(())
    }

    /// Forget `connection`; its writer thread ends with its backlog.
    pub(crate) fn remove(&self, connection: u64) {
        self.members
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .retain(|member| member.connection != connection);
    }

    /// Queue one encoded event line for every subscriber, closing any that lag.
    pub(crate) fn broadcast(&self, line: &Arc<[u8]>) {
        self.members
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .retain(|member| match member.backlog.try_send(Arc::clone(line)) {
                Ok(()) => true,
                Err(TrySendError::Full(_) | TrySendError::Disconnected(_)) => {
                    let _closed = member.stream.shutdown(Shutdown::Both);
                    false
                }
            });
    }
}

fn drain(events: &Receiver<Arc<[u8]>>, output: &Writer) {
    while let Ok(line) = events.recv() {
        if lock(output).write_all(&line).is_err() {
            break;
        }
    }
}

/// Lock a writer; a panicked writer leaves only a partly written line behind.
pub(crate) fn lock(writer: &Writer) -> std::sync::MutexGuard<'_, UnixStream> {
    writer.lock().unwrap_or_else(PoisonError::into_inner)
}
