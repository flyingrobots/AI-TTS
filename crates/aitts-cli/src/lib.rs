// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The `ai-tts` command-line client. It keeps the Python CLI's argument
//! grammar, request payloads, JSON replies and exit statuses
//! (`docs/design/features.md` section 8).

#![forbid(unsafe_code)]
#![deny(missing_docs, clippy::print_stdout, clippy::print_stderr, clippy::exit)]

mod grammar;
pub mod mcp;
mod mcp_schema;
mod mcp_tools;
mod payload;
mod wait;

use aitts_client::{Client, ClientError};
use aitts_protocol::decode_request;
use clap::ArgMatches;
use serde_json::{Value, json};
use std::ffi::OsString;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Duration;

/// The daemon accepted the operation.
pub const EXIT_OK: u8 = 0;
/// The daemon refused the operation, or the command line was refused.
pub const EXIT_DAEMON_ERROR: u8 = 1;
/// The daemon could not be reached, or argument parsing failed.
pub const EXIT_UNREACHABLE: u8 = 2;
/// `wait` or `say --wait` ended in a terminal state other than `Played`.
pub const EXIT_NOT_PLAYED: u8 = 3;

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
    pub fn socket(&self) -> PathBuf {
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

/// A failed exchange: the exit status and the JSON to print.
pub(crate) struct Failed(pub(crate) u8, pub(crate) Value);

fn client_failure(error: ClientError) -> Failed {
    let kind = match error {
        ClientError::Wire(_) | ClientError::Refused(_) => "internal",
        _ => "unreachable",
    };
    Failed(error.exit_status(), failure(kind, &error.to_string()))
}

/// Send `request` and return the daemon's `ok: true` reply as JSON.
pub(crate) fn exchange(socket: &Path, request: &Value) -> Result<Value, Failed> {
    let typed = decode_request(request.to_string().as_bytes()).map_err(|error| {
        // The daemon decodes with the same types and would refuse it identically.
        Failed(
            EXIT_DAEMON_ERROR,
            failure("bad_request", &format!("invalid request: {error}")),
        )
    })?;
    let reply = Client::new(socket, LIMIT)
        .request(&typed)
        .map_err(client_failure)?;
    let value = serde_json::to_value(&reply)
        .map_err(|error| Failed(EXIT_DAEMON_ERROR, failure("internal", &error.to_string())))?;
    if value.get("ok") == Some(&json!(true)) {
        Ok(value)
    } else {
        Err(Failed(EXIT_DAEMON_ERROR, value))
    }
}

fn finish(out: &mut dyn Write, result: Result<(Value, u8), Failed>) -> u8 {
    let (value, status) = result.unwrap_or_else(|Failed(status, value)| (value, status));
    emit(out, &value);
    status
}

fn command(name: &str, sub: &ArgMatches, socket: &Path) -> Result<(Value, u8), Failed> {
    let timeout = sub.try_get_one::<f64>("timeout").ok().flatten().copied();
    if name == "wait" {
        let id = sub.get_one::<String>("id").cloned().unwrap_or_default();
        let state = wait::final_state(socket, &id, timeout)?;
        return Ok((
            json!({"ok": true, "id": id, "final_state": state}),
            wait::status(state),
        ));
    }
    let request = payload::payload(name, sub)
        .map_err(|payload::Refused(message)| Failed(EXIT_DAEMON_ERROR, json!(message)))?;
    let mut reply = exchange(socket, &request)?;
    if name == "say" && sub.get_flag("wait") {
        let id = reply
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
        let state = wait::final_state(socket, &id, timeout)?;
        if let Value::Object(map) = &mut reply {
            map.insert("final_state".into(), json!(state));
        }
        return Ok((reply, wait::status(state)));
    }
    Ok((reply, EXIT_OK))
}

/// The `--socket` value and the command name, skipping only the global
/// `--socket` option (or an unambiguous prefix of it) before the command.
pub fn leading(args: &[OsString]) -> (Option<PathBuf>, Option<String>) {
    let mut socket = None;
    let mut rest = args.iter();
    while let Some(arg) = rest.next() {
        let Some(text) = arg.to_str() else {
            return (socket, None);
        };
        let (option, value) = text
            .split_once('=')
            .map_or((text, None), |(o, v)| (o, Some(v)));
        if option.len() >= 3 && "--socket".starts_with(option) {
            socket = match value {
                Some(value) => Some(PathBuf::from(value)),
                None => rest.next().map(PathBuf::from),
            };
            continue;
        }
        return (socket, Some(text.to_owned()));
    }
    (socket, None)
}

/// Whether the command is `daemon` or `tui`, which the Python `ai-tts-py` runs.
pub fn hands_off(args: &[OsString]) -> bool {
    matches!(leading(args).1.as_deref(), Some("daemon" | "tui"))
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
    let socket = matches
        .get_one::<PathBuf>("socket")
        .map_or_else(|| env.socket(), |path| env.expand(path.clone().into()));
    match command(name, sub, &socket) {
        // A refused command line goes to standard error, as Python's SystemExit(msg).
        Err(Failed(status, Value::String(message))) => {
            let _ = writeln!(err, "{message}");
            status
        }
        result => finish(out, result),
    }
}
