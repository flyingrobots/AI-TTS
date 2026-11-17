// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Fixture databases, daemon configuration, and a line-oriented test client.

#![allow(dead_code, reason = "each test binary uses a different subset")]

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};

use aitts_daemon::{Config, EngineView};
use aitts_protocol::vocabulary::ModelState;
use serde_json::Value;

/// The Python-written store fixture and the JSON the Python `Store` read back from it.
pub(crate) fn store_fixture(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../aitts-store/tests/fixtures")
        .join(name)
}

pub(crate) fn golden() -> Value {
    let text = std::fs::read_to_string(store_fixture("golden.json")).unwrap();
    serde_json::from_str(&text).unwrap()
}

/// A configuration in a fresh directory, over a private copy of `golden.db`.
pub(crate) fn golden_config(dir: &Path) -> Config {
    let database = dir.join("ai-tts.db");
    std::fs::copy(store_fixture("golden.db"), &database).unwrap();
    Config {
        socket: dir.join("ai-tts.sock"),
        database,
        cache_dir: dir.join("cache"),
        engine: EngineView {
            name: "kokoro".to_owned(),
            voices: vec!["af_heart".to_owned(), "bm_daniel".to_owned()],
            is_local: true,
            state: ModelState::Cold,
        },
    }
}

/// Send one request line and read one reply line on a new connection.
pub(crate) fn request(socket: &Path, line: &[u8]) -> Vec<u8> {
    let mut stream = UnixStream::connect(socket).unwrap();
    stream.write_all(line).unwrap();
    read_line(&stream)
}

/// A reply that has not arrived in this time is a failure, not a hang.
pub(crate) const REPLY_LIMIT: std::time::Duration = std::time::Duration::from_secs(10);

pub(crate) fn read_line(stream: &UnixStream) -> Vec<u8> {
    stream.set_read_timeout(Some(REPLY_LIMIT)).unwrap();
    let mut reply = Vec::new();
    BufReader::new(stream)
        .read_until(b'\n', &mut reply)
        .unwrap();
    reply
}

pub(crate) fn json(reply: &[u8]) -> Value {
    serde_json::from_slice(reply).unwrap()
}
