// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns daemon start and bounded stop.
//!
//! Start order: take the lease, open the store, replace a stale socket, bind with
//! mode 0600, then accept. Stop order: refuse new work, close every connection,
//! let the API thread close the store, remove the socket, release the lease.

use core::fmt;
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::PathBuf;
use std::sync::atomic::Ordering;
use std::sync::mpsc::{channel, sync_channel};
use std::sync::{Arc, PoisonError};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use aitts_protocol::event::{Event, encode_event};
use aitts_protocol::vocabulary::ModelState;
use aitts_store::{Store, SystemClock};

use crate::api::{self, ReadApi};
use crate::connection::{self, Shared};
use crate::lease::{self, Lease};
use crate::socket_file;

/// The engine the daemon reports. This crate runs no engine; the caller observes one.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EngineView {
    /// The selected engine's name.
    pub name: String,
    /// Its voice catalog.
    pub voices: Vec<String>,
    /// Whether synthesis stays on this machine.
    pub is_local: bool,
    /// Its readiness.
    pub state: ModelState,
}

/// Where the daemon serves and what it reads.
#[derive(Clone, Debug)]
pub struct Config {
    /// The Unix socket path; the lease is `<socket>.lock`.
    pub socket: PathBuf,
    /// The shared SQLite state file.
    pub database: PathBuf,
    /// The cached audio directory measured by `metrics`.
    pub cache_dir: PathBuf,
    /// The engine status and voices report.
    pub engine: EngineView,
}

/// Why the daemon did not start. Nothing it started is left running.
#[derive(Debug)]
pub enum StartError {
    /// Another daemon holds the socket lease.
    AlreadyRunning,
    /// The socket or lock path holds a symbolic link or a non-socket entry; it is kept.
    SocketOccupied,
    /// A server answers on the socket path.
    LiveSocket,
    /// The state database could not be opened.
    Store(aitts_store::Error),
    /// A file or socket operation failed.
    Io(std::io::Error),
}

impl fmt::Display for StartError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::AlreadyRunning => formatter.write_str("another daemon is already running"),
            Self::SocketOccupied => {
                formatter.write_str("socket path is occupied by a non-socket entry")
            }
            Self::LiveSocket => formatter.write_str("socket is already owned by a live server"),
            Self::Store(error) => write!(formatter, "cannot open the state database: {error}"),
            Self::Io(error) => write!(formatter, "cannot serve the socket: {error}"),
        }
    }
}

impl std::error::Error for StartError {}

/// How a stop ended.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[must_use]
pub enum StopOutcome {
    /// Every thread finished and the store closed.
    Clean,
    /// The limit passed first. The socket is removed and the lease released anyway.
    TimedOut,
}

/// A serving daemon. Dropping it without [`Running::stop`] leaves threads serving.
#[must_use]
pub struct Running {
    shared: Arc<Shared>,
    socket: PathBuf,
    accept: JoinHandle<()>,
    api: JoinHandle<()>,
    lease: Lease,
}

impl fmt::Debug for Running {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("Running")
            .field("socket", &self.socket)
            .finish_non_exhaustive()
    }
}

/// Start serving `config.socket`.
///
/// # Errors
/// Returns [`StartError`] when the lease, the store, or the socket is unavailable.
pub fn start(config: Config) -> Result<Running, StartError> {
    let lease = lease::acquire(&config.socket)?;
    let (jobs, api) = start_api(&config)?;
    let listener = match socket_file::bind_private(&config.socket) {
        Ok(listener) => listener,
        Err(error) => {
            drop(jobs);
            let _ = api.join();
            return Err(error);
        }
    };
    let shared = Arc::new(Shared::default());
    *shared.jobs.lock().unwrap_or_else(PoisonError::into_inner) = Some(jobs);
    let owner = Arc::clone(&shared);
    let accept = std::thread::Builder::new()
        .name("ai-ttsd-accept".to_owned())
        .spawn(move || accept_loop(&listener, &owner))
        .map_err(StartError::Io)?;
    Ok(Running {
        shared,
        socket: config.socket,
        accept,
        api,
        lease,
    })
}

fn start_api(
    config: &Config,
) -> Result<(std::sync::mpsc::Sender<api::Job>, JoinHandle<()>), StartError> {
    let (jobs, requests) = channel();
    let (ready, opened) = sync_channel(1);
    let database = config.database.clone();
    let engine = config.engine.clone();
    let cache_dir = config.cache_dir.clone();
    let handle = std::thread::Builder::new()
        .name("ai-ttsd-api".to_owned())
        .spawn(move || match Store::open(&database, SystemClock) {
            Ok(store) => {
                let _ = ready.send(Ok(()));
                let started = Instant::now();
                api::serve(
                    ReadApi {
                        store,
                        engine,
                        cache_dir,
                        started,
                    },
                    &requests,
                );
            }
            Err(error) => {
                let _ = ready.send(Err(error));
            }
        })
        .map_err(StartError::Io)?;
    match opened.recv() {
        Ok(Ok(())) => Ok((jobs, handle)),
        Ok(Err(error)) => Err(StartError::Store(error)),
        Err(_) => Err(StartError::Io(std::io::Error::other(
            "the API thread ended",
        ))),
    }
}

fn accept_loop(listener: &UnixListener, shared: &Arc<Shared>) {
    for stream in listener.incoming() {
        if shared.stopping.load(Ordering::SeqCst) {
            return;
        }
        if let Ok(stream) = stream {
            connection::spawn(stream, shared);
        }
    }
}

impl Running {
    /// The socket being served.
    pub fn socket(&self) -> &std::path::Path {
        &self.socket
    }

    /// Send `event` to every subscriber without waiting on any of them.
    pub fn broadcast(&self, event: &Event) {
        if let Ok(line) = encode_event(event) {
            self.shared.subscribers.broadcast(&Arc::from(line));
        }
    }

    /// Stop within `limit`: close connections, close the store, remove the socket.
    pub fn stop(self, limit: Duration) -> StopOutcome {
        let deadline = Instant::now() + limit;
        self.shared.stopping.store(true, Ordering::SeqCst);
        // Wake the accept loop; a refused connection also means it is gone.
        drop(UnixStream::connect(&self.socket));
        self.shared.close_all();
        self.shared
            .jobs
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .take();
        let finished = wait_until(deadline, || {
            self.accept.is_finished()
                && self.api.is_finished()
                && self.shared.live_connections.load(Ordering::SeqCst) == 0
        });
        let _removed = std::fs::remove_file(&self.socket);
        drop(self.lease);
        if finished {
            StopOutcome::Clean
        } else {
            StopOutcome::TimedOut
        }
    }
}

fn wait_until(deadline: Instant, done: impl Fn() -> bool) -> bool {
    while !done() {
        if Instant::now() >= deadline {
            return false;
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    true
}
