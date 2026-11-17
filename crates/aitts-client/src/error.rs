// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the client's typed failures and their process exit statuses.

use aitts_protocol::WireError;
use core::fmt;
use std::io;

/// Exit status for a caller that cannot reach the daemon, as in the Python CLI.
pub const EXIT_UNREACHABLE: u8 = 2;

/// Exit status for a caller that reached the daemon but got an unusable reply.
pub const EXIT_FAILURE: u8 = 1;

/// Why a request or subscription did not produce a reply or event.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[non_exhaustive]
pub enum ClientError {
    /// The socket could not be connected: it is absent, or nothing listens on it.
    Unreachable(io::ErrorKind),
    /// No complete line arrived within the client's time limit.
    TimedOut,
    /// The daemon closed the connection before a complete line.
    Closed,
    /// Reading or writing the connected socket failed.
    Io(io::ErrorKind),
    /// The line was too large or did not match the wire contract.
    Wire(WireError),
}

impl ClientError {
    /// The process exit status a command-line caller reports for this error.
    pub const fn exit_status(&self) -> u8 {
        match self {
            Self::Wire(_) => EXIT_FAILURE,
            Self::Unreachable(_) | Self::TimedOut | Self::Closed | Self::Io(_) => EXIT_UNREACHABLE,
        }
    }
}

impl fmt::Display for ClientError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Unreachable(kind) => write!(formatter, "cannot reach the daemon: {kind}"),
            Self::TimedOut => formatter.write_str("timed out waiting for the daemon"),
            Self::Closed => {
                formatter.write_str("the daemon closed the connection without answering")
            }
            Self::Io(kind) => write!(formatter, "daemon socket failed: {kind}"),
            Self::Wire(error) => write!(formatter, "invalid daemon reply: {error}"),
        }
    }
}

impl std::error::Error for ClientError {}
