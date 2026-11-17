// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The `ai-tts` command-line client. It keeps the Python CLI's argument
//! grammar, request payloads, JSON replies and exit statuses.

#![forbid(unsafe_code)]
#![deny(missing_docs, clippy::print_stdout, clippy::print_stderr, clippy::exit)]

use std::ffi::OsString;
use std::io::Write;
use std::path::PathBuf;

/// The daemon accepted the operation.
pub const EXIT_OK: u8 = 0;
/// The daemon refused the operation, or the command line was refused.
pub const EXIT_DAEMON_ERROR: u8 = 1;
/// The daemon could not be reached, or argument parsing failed.
pub const EXIT_UNREACHABLE: u8 = 2;

/// The process environment values that choose the daemon socket.
#[derive(Clone, Debug, Default)]
pub struct Environment {
    /// `AI_TTS_SOCKET`.
    pub socket: Option<OsString>,
    /// `AI_TTS_HOME`.
    pub home: Option<OsString>,
    /// The user's home directory, used for the default daemon home.
    pub user_home: Option<PathBuf>,
}

/// Run one command. `args` excludes the program name. Returns the exit status.
#[allow(clippy::todo, reason = "RED stub")]
pub fn run(
    _args: impl IntoIterator<Item = OsString>,
    _env: &Environment,
    _out: &mut dyn Write,
    _err: &mut dyn Write,
) -> u8 {
    todo!()
}
