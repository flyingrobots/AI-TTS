// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! A recording peer and an in-process runner for the `ai-tts` client.

#![allow(dead_code, reason = "each test binary uses a different subset")]
#![allow(clippy::unwrap_used, reason = "test code fails loudly")]

use std::ffi::OsString;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};
use std::thread::JoinHandle;

use aitts_cli::Environment;
use serde_json::Value;

/// The daemon error every recorded request receives.
pub(crate) const REFUSAL: &str = r#"{"ok":false,"error":{"type":"not_found","message":"peer"}}"#;
const STOP: &[u8] = b"STOP\n";

/// A socket peer that answers every request with [`REFUSAL`] and records it.
pub(crate) struct Recorder {
    pub(crate) socket: PathBuf,
    _dir: tempfile::TempDir,
    handle: JoinHandle<Vec<Value>>,
}

impl Recorder {
    pub(crate) fn start() -> Self {
        let dir = tempfile::tempdir().unwrap();
        let socket = dir.path().join("peer.sock");
        let listener = UnixListener::bind(&socket).unwrap();
        let handle = std::thread::spawn(move || {
            let mut seen = Vec::new();
            for stream in listener.incoming() {
                let stream = stream.unwrap();
                let mut line = Vec::new();
                BufReader::new(&stream)
                    .read_until(b'\n', &mut line)
                    .unwrap();
                if line == STOP {
                    return seen;
                }
                seen.push(serde_json::from_slice(&line).unwrap());
                let mut writer = &stream;
                let _ = writer.write_all(format!("{REFUSAL}\n").as_bytes());
            }
            seen
        });
        Self {
            socket,
            _dir: dir,
            handle,
        }
    }

    /// Stop the peer and return each request it read, parsed.
    pub(crate) fn finish(self) -> Vec<Value> {
        UnixStream::connect(&self.socket)
            .unwrap()
            .write_all(STOP)
            .unwrap();
        self.handle.join().unwrap()
    }
}

/// The result of one in-process command.
pub(crate) struct Outcome {
    pub(crate) status: u8,
    pub(crate) stdout: Vec<u8>,
}

impl Outcome {
    pub(crate) fn json(&self) -> Value {
        serde_json::from_slice(&self.stdout).unwrap()
    }
}

/// Run `ai-tts --socket <socket> <argv...>` in process.
pub(crate) fn run(socket: &Path, argv: &[&str]) -> Outcome {
    let mut command: Vec<OsString> = vec!["--socket".into(), socket.into()];
    command.extend(argv.iter().map(OsString::from));
    let (mut stdout, mut stderr) = (Vec::new(), Vec::new());
    let status = aitts_cli::run(command, &Environment::default(), &mut stdout, &mut stderr);
    Outcome { status, stdout }
}

/// Parsed-JSON equality where a float and an integer of the same value match,
/// because Python writes `2.0` where serde may write `2`.
pub(crate) fn same_json(left: &Value, right: &Value) -> bool {
    match (left, right) {
        (Value::Number(a), Value::Number(b)) => a.as_f64() == b.as_f64(),
        (Value::Array(a), Value::Array(b)) => {
            a.len() == b.len() && a.iter().zip(b).all(|(x, y)| same_json(x, y))
        }
        (Value::Object(a), Value::Object(b)) => {
            a.len() == b.len()
                && a.iter()
                    .all(|(k, v)| b.get(k).is_some_and(|w| same_json(v, w)))
        }
        _ => left == right,
    }
}
