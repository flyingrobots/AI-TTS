// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The `ai-ttsd` Rust daemon: process lifetime, the Unix socket server, and the
//! operations that only read state.
//!
//! [`start`] takes the socket lease, opens the shared state database, and serves
//! JSON lines on a mode 0600 Unix socket. [`Running::stop`] ends service within a
//! time limit. Operations that change state and audio are not part of this crate yet;
//! the daemon refuses them with a `bad_request` reply.
//!
//! Concurrency model: one thread accepts connections, one thread per connection
//! reads and writes lines, and one API thread owns the store and answers requests
//! in arrival order. Each subscriber has its own bounded backlog and writer thread,
//! so a slow subscriber cannot block a broadcast.

#![forbid(unsafe_code)]
#![deny(missing_docs, clippy::print_stdout, clippy::print_stderr, clippy::exit)]

mod api;
mod cache_usage;
pub mod conductor;
mod connection;
mod lease;
mod projection;
mod runtime;
mod settings_view;
mod socket_file;
mod status;
mod subscribers;
pub mod synthesis;

pub use runtime::{Config, EngineView, Running, StartError, StopOutcome, start};
