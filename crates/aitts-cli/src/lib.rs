// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The `ai-tts` command-line client. It keeps the Python CLI's argument
//! grammar, request payloads, JSON replies and exit statuses
//! (`docs/design/features.md` section 8).

#![forbid(unsafe_code)]
#![deny(missing_docs, clippy::print_stdout, clippy::print_stderr, clippy::exit)]

mod grammar;
mod payload;

use aitts_client::{Client, ClientError};
use aitts_protocol::decode_request;
use serde_json::{Value, json};
use std::ffi::OsString;
use std::io::Write;
use std::path::PathBuf;
use std::time::Duration;

/// The daemon accepted the operation.
pub const EXIT_OK: u8 = 0;
/// The daemon refused the operation, or the command line was refused.
pub const EXIT_DAEMON_ERROR: u8 = 1;
/// The daemon could not be reached, or argument parsing failed.
pub const EXIT_UNREACHABLE: u8 = 2;

/// Each socket read and write waits this long, as the Python client does.
const LIMIT: Duration = Duration::from_secs(10);

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

impl Environment {
    /// `aitts.paths.default_socket`: `AI_TTS_SOCKET`, else `<home>/ai-tts.sock`.
    fn socket(&self) -> PathBuf {
        let set = |value: &Option<OsString>| value.clone().filter(|value| !value.is_empty());
        if let Some(socket) = set(&self.socket) {
            return self.expand(socket);
        }
        let home = set(&self.home).map_or_else(
            || self.expand("~/Library/Application Support/ai-tts".into()),
            |home| self.expand(home),
        );
        home.join("ai-tts.sock")
    }

    fn expand(&self, path: OsString) -> PathBuf {
        let path = PathBuf::from(path);
        match (path.strip_prefix("~"), &self.user_home) {
            (Ok(rest), Some(home)) => home.join(rest),
            _ => path,
        }
    }
}

fn emit(out: &mut dyn Write, value: &Value) {
    // A closed stdout leaves nothing to report to; the exit status still tells.
    let _ = serde_json::to_writer_pretty(&mut *out, value)
        .and_then(|()| out.write_all(b"\n").map_err(serde_json::Error::io));
}

fn failure(kind: &str, message: &str) -> Value {
    json!({"ok": false, "error": {"type": kind, "message": message}})
}

fn send(socket: PathBuf, request: &Value, out: &mut dyn Write) -> u8 {
    let typed = match decode_request(request.to_string().as_bytes()) {
        Ok(typed) => typed,
        Err(error) => {
            // The daemon decodes with the same types and would refuse it identically.
            emit(
                out,
                &failure("bad_request", &format!("invalid request: {error}")),
            );
            return EXIT_DAEMON_ERROR;
        }
    };
    let reply = match Client::new(socket, LIMIT).request(&typed) {
        Ok(reply) => reply,
        Err(error) => {
            let kind = match error {
                ClientError::Wire(_) | ClientError::Refused(_) => "internal",
                _ => "unreachable",
            };
            emit(out, &failure(kind, &error.to_string()));
            return error.exit_status();
        }
    };
    match serde_json::to_value(&reply) {
        Ok(value) => {
            let accepted = value.get("ok") == Some(&json!(true));
            emit(out, &value);
            if accepted { EXIT_OK } else { EXIT_DAEMON_ERROR }
        }
        Err(error) => {
            emit(out, &failure("internal", &error.to_string()));
            EXIT_DAEMON_ERROR
        }
    }
}

/// Run one command. `args` excludes the program name. Returns the exit status.
pub fn run(
    args: impl IntoIterator<Item = OsString>,
    env: &Environment,
    out: &mut dyn Write,
    err: &mut dyn Write,
) -> u8 {
    let program = std::iter::once(OsString::from("ai-tts")).chain(args);
    let matches = match grammar::grammar().try_get_matches_from(program) {
        Ok(matches) => matches,
        Err(error) => {
            let rendered = error.render().to_string();
            return if error.use_stderr() {
                let _ = err.write_all(rendered.as_bytes());
                EXIT_UNREACHABLE
            } else {
                let _ = out.write_all(rendered.as_bytes());
                EXIT_OK
            };
        }
    };
    let Some((name, sub)) = matches.subcommand() else {
        return EXIT_UNREACHABLE;
    };
    if name == "wait" || (name == "say" && sub.get_flag("wait")) {
        let _ = writeln!(
            err,
            "ai-tts: waiting for playback is not in the Rust client yet"
        );
        return EXIT_DAEMON_ERROR;
    }
    let socket = matches
        .get_one::<PathBuf>("socket")
        .map_or_else(|| env.socket(), |path| env.expand(path.clone().into()));
    match payload::payload(name, sub) {
        Ok(request) => send(socket, &request, out),
        Err(payload::Refused(message)) => {
            let _ = writeln!(err, "{message}");
            EXIT_DAEMON_ERROR
        }
    }
}
