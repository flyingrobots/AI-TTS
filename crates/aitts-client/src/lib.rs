// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Clients for the AI-TTS daemon's Unix socket: one blocking request and reply
//! with a time limit ([`Client::request`]), and an event stream that subscribes
//! again after the daemon restarts ([`Client::subscribe`]).
//!
//! Wire types and line limits come from `aitts-protocol`. This crate parses no
//! command line and prints nothing.

#![forbid(unsafe_code)]
#![deny(missing_docs, clippy::print_stdout, clippy::print_stderr, clippy::exit)]

mod blocking;
mod error;
mod line;
mod subscription;

pub use blocking::Client;
pub use error::{ClientError, EXIT_FAILURE, EXIT_UNREACHABLE};
pub use subscription::{Delivery, ReconnectPolicy, Subscription};
