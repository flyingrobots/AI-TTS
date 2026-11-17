// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! A scripted socket peer that replays chosen bytes, and the captured transcripts.

#![allow(dead_code, reason = "each test binary uses a different subset")]

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixListener;
use std::path::PathBuf;
use std::sync::mpsc::{Sender, channel};
use std::thread::JoinHandle;

use serde_json::Value;

/// One connection's script: bytes written after the request line, in order.
pub(crate) struct Script {
    pub(crate) chunks: Vec<Vec<u8>>,
    /// Keep the connection open after the chunks until the peer is dropped.
    pub(crate) hold: bool,
}

/// A listener that serves one connection per script, in order.
pub(crate) struct Peer {
    pub(crate) socket: PathBuf,
    _dir: tempfile::TempDir,
    release: Sender<()>,
    handle: Option<JoinHandle<Vec<Vec<u8>>>>,
}

impl Peer {
    pub(crate) fn serve(scripts: Vec<Script>) -> Self {
        let dir = tempfile::tempdir().unwrap();
        let socket = dir.path().join("peer.sock");
        let listener = UnixListener::bind(&socket).unwrap();
        let (release, held) = channel::<()>();
        let handle = std::thread::spawn(move || {
            let mut received = Vec::new();
            for script in scripts {
                let (stream, _) = listener.accept().unwrap();
                let mut reader = BufReader::new(stream.try_clone().unwrap());
                let mut line = Vec::new();
                reader.read_until(b'\n', &mut line).unwrap();
                received.push(line);
                let mut writer = stream;
                for chunk in &script.chunks {
                    // A peer that stops reading may close first; that is the test's subject.
                    if writer
                        .write_all(chunk)
                        .and_then(|()| writer.flush())
                        .is_err()
                    {
                        break;
                    }
                    // Pacing, not synchronization: it lets each chunk reach a separate read.
                    std::thread::sleep(std::time::Duration::from_millis(1));
                }
                if script.hold {
                    let _ = held.recv();
                }
            }
            received
        });
        Self {
            socket,
            _dir: dir,
            release,
            handle: Some(handle),
        }
    }

    /// The request lines the peer read, one per served connection.
    pub(crate) fn received(mut self) -> Vec<Vec<u8>> {
        let _ = self.release.send(());
        self.handle.take().unwrap().join().unwrap()
    }
}

pub(crate) fn once(chunks: Vec<Vec<u8>>) -> Peer {
    Peer::serve(vec![Script {
        chunks,
        hold: false,
    }])
}

pub(crate) fn line(value: &Value) -> Vec<u8> {
    let mut bytes = serde_json::to_vec(value).unwrap();
    bytes.push(b'\n');
    bytes
}

/// Every captured record of the Python reference conversations (oracle: Python 38d967c).
pub(crate) fn transcripts() -> Vec<(&'static str, Vec<Value>)> {
    macro_rules! fixture {
        ($name:literal) => {
            (
                $name,
                serde_json::from_str::<Vec<Value>>(include_str!(concat!(
                    "../../../aitts-protocol/tests/fixtures/wire/",
                    $name,
                    ".json"
                )))
                .unwrap(),
            )
        };
    }
    vec![
        fixture!("submit"),
        fixture!("status"),
        fixture!("list"),
        fixture!("history"),
        fixture!("pause"),
        fixture!("resume"),
        fixture!("skip"),
        fixture!("settings"),
        fixture!("subscribe"),
    ]
}
