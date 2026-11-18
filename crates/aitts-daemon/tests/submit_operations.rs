// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (owned temporary files and a loopback Unix socket).
//! Conformance suite for `submit` and `requeue` over the socket.
//! Oracles: the Python reference transcript `aitts-protocol/tests/fixtures/wire/
//! submit.json` (decoded replies equal, except the generated `utt_` id, which is
//! checked for its format); the Python handlers `_op_submit`, `_op_requeue`,
//! `_replay`, `eligible_engine_names` and `VoiceRegistry.resolve`, read as the
//! specification; and Python `prepare_speech_segments`, which gives
//! `("bold text",)` for the Markdown `**bold** text` (run at this commit).

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

mod support;

use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

use aitts_daemon::{Config, EngineView};
use aitts_protocol::error_reply::ErrorCode;
use aitts_protocol::operation::Operation;
use aitts_protocol::reply::{Reply, decode_reply};
use aitts_protocol::value::Nullable;
use aitts_protocol::vocabulary::{ModelState, Priority, State};
use aitts_store::queue::{Fields, NewUtterance};
use aitts_store::{Store, SystemClock};
use serde_json::Value;
use support::request;

/// A daemon over a fresh database with `queued` items and a played `old` item,
/// speaking through one engine with `voices`.
fn config(dir: &Path, queued: &[&str], is_local: bool, voices: &[&str]) -> Config {
    let database = dir.join("queue.db");
    let store = Store::open(&database, SystemClock).unwrap();
    for id in std::iter::once("old").chain(queued.iter().copied()) {
        let new = NewUtterance::new(
            id.to_owned(),
            format!("{id} text"),
            voices[0].to_owned(),
            1.0,
        );
        store.queue().submit(&new).unwrap();
    }
    for to in [
        aitts_store::State::Synthesizing,
        aitts_store::State::Ready,
        aitts_store::State::Playing,
        aitts_store::State::Played,
    ] {
        store
            .queue()
            .transition("old", to, &Fields::default())
            .unwrap();
    }
    store.close().unwrap();
    Config {
        socket: dir.join("ai-tts.sock"),
        database,
        cache_dir: dir.join("cache"),
        engine: EngineView {
            name: "fake".to_owned(),
            voices: voices.iter().map(|voice| (*voice).to_owned()).collect(),
            is_local,
            state: ModelState::Cold,
        },
    }
}

struct Daemon {
    running: Option<aitts_daemon::Running>,
    socket: PathBuf,
    _dir: tempfile::TempDir,
}

impl Daemon {
    fn start(queued: &[&str], is_local: bool, voices: &[&str]) -> Self {
        let dir = tempfile::tempdir().unwrap();
        let config = config(dir.path(), queued, is_local, voices);
        let socket = config.socket.clone();
        Self {
            running: Some(aitts_daemon::start(config).unwrap()),
            socket,
            _dir: dir,
        }
    }

    fn ask(&self, operation: Operation, line: &str) -> Reply {
        let reply = request(&self.socket, format!("{line}\n").as_bytes());
        decode_reply(operation, &reply).unwrap_or_else(|error| {
            panic!("{line} gave {} ({error})", String::from_utf8_lossy(&reply))
        })
    }

    fn submitted(&self, line: &str) -> aitts_protocol::query_reply::Submitted {
        match self.ask(Operation::Submit, line) {
            Reply::Submit(submitted) => submitted,
            other => panic!("{line} was refused: {other:?}"),
        }
    }

    fn listed(&self) -> Vec<String> {
        let Reply::List(items) = self.ask(Operation::List, r#"{"op":"list","queue":"input"}"#)
        else {
            panic!("list failed")
        };
        items.items.into_iter().map(|item| item.id).collect()
    }

    fn item(&self, id: &str) -> aitts_protocol::utterance::Utterance {
        let Reply::Get(item) = self.ask(Operation::Get, &format!(r#"{{"op":"get","id":"{id}"}}"#))
        else {
            panic!("get {id} failed")
        };
        item.item
    }
}

impl Drop for Daemon {
    fn drop(&mut self) {
        // No assertion here: a panic while unwinding would abort the test binary.
        if let Some(running) = self.running.take() {
            let _outcome = running.stop(Duration::from_secs(5));
        }
    }
}

fn error_code(reply: &Reply) -> ErrorCode {
    match reply {
        Reply::Error(error) => error.error.r#type,
        other => panic!("expected an error reply, got {other:?}"),
    }
}

fn is_utterance_id(id: &str) -> bool {
    id.strip_prefix("utt_").is_some_and(|hex| {
        hex.len() == 32
            && hex
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    })
}

#[test]
fn submit_replies_equal_the_python_transcript_except_the_generated_id() {
    let daemon = Daemon::start(&[], true, &["bm_daniel"]);
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../aitts-protocol/tests/fixtures/wire/submit.json");
    let transcript: Vec<Value> =
        serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    for entry in transcript {
        let op = match entry["request"]["op"].as_str().unwrap() {
            "pause" => Operation::Pause,
            "submit" => Operation::Submit,
            other => panic!("unexpected {other}"),
        };
        let actual = decode_reply(
            op,
            &request(&daemon.socket, format!("{}\n", entry["request"]).as_bytes()),
        )
        .unwrap();
        let mut expected = entry["reply"].clone();
        if let Reply::Submit(submitted) = &actual {
            assert!(
                is_utterance_id(&submitted.id),
                "generated id {} is not utt_ and 32 hex digits",
                submitted.id
            );
            expected["id"] = Value::String(submitted.id.clone());
        }
        let expected = decode_reply(op, &serde_json::to_vec(&expected).unwrap()).unwrap();
        assert_eq!(
            actual, expected,
            "{} differs from the Python reply",
            entry["request"]
        );
    }
}

#[test]
fn submit_of_blank_text_is_a_bad_request() {
    let daemon = Daemon::start(&[], true, &["bm_daniel"]);
    assert_eq!(
        error_code(&daemon.ask(Operation::Submit, r#"{"op":"submit","text":"  \n"}"#)),
        ErrorCode::BadRequest
    );
}

#[test]
fn private_speech_on_a_remote_engine_is_refused() {
    let daemon = Daemon::start(&[], false, &["bm_daniel"]);
    assert_eq!(
        error_code(&daemon.ask(Operation::Submit, r#"{"op":"submit","text":"Secret."}"#)),
        ErrorCode::BadRequest
    );
}

#[test]
fn public_speech_on_a_remote_engine_is_accepted() {
    let daemon = Daemon::start(&[], false, &["bm_daniel"]);
    let submitted = daemon.submitted(r#"{"op":"submit","text":"Hello.","sensitivity":"public"}"#);
    assert_eq!(submitted.state, State::Queued);
}

#[test]
fn an_unknown_requested_voice_is_a_bad_request() {
    let daemon = Daemon::start(&[], true, &["bm_daniel"]);
    assert_eq!(
        error_code(&daemon.ask(
            Operation::Submit,
            r#"{"op":"submit","text":"Hi.","voice":"nobody"}"#
        )),
        ErrorCode::BadRequest
    );
}

#[test]
fn the_preempt_flag_admits_at_the_head() {
    let daemon = Daemon::start(&["a"], true, &["bm_daniel"]);
    let submitted = daemon.submitted(r#"{"op":"submit","text":"Now.","preempt":true}"#);
    assert_eq!(daemon.listed(), [submitted.id.clone(), "a".to_owned()]);
    assert_eq!(daemon.item(&submitted.id).priority, Priority::Preempt);
}

#[test]
fn markdown_that_changes_when_spoken_is_composite() {
    let daemon = Daemon::start(&[], true, &["bm_daniel"]);
    let submitted =
        daemon.submitted(r#"{"op":"submit","text":"**bold** text","content_format":"markdown"}"#);
    assert_eq!((submitted.composite, submitted.segment_count), (true, 1));
}

#[test]
fn an_agent_source_claims_a_voice_no_other_client_holds_and_keeps_it() {
    let daemon = Daemon::start(&[], true, &["bm_daniel", "bm_george"]);
    let first = daemon
        .submitted(r#"{"op":"submit","text":"One.","source":"agent-a"}"#)
        .voice;
    let second = daemon
        .submitted(r#"{"op":"submit","text":"Two.","source":"agent-b"}"#)
        .voice;
    let again = daemon
        .submitted(r#"{"op":"submit","text":"Three.","source":"agent-a"}"#)
        .voice;
    assert_ne!(first, second, "two clients share a voice");
    assert_eq!(again, first, "a client lost its claimed voice");
}

#[test]
fn requeue_of_a_played_item_replays_it_ahead_of_pending_work_when_urgent() {
    let daemon = Daemon::start(&["a"], true, &["bm_daniel"]);
    let Reply::Requeue(requeued) = daemon.ask(
        Operation::Requeue,
        r#"{"op":"requeue","id":"old","priority":"urgent"}"#,
    ) else {
        panic!("requeue was refused")
    };
    assert_eq!(
        (
            requeued.state,
            requeued.priority,
            requeued.composite,
            requeued.segment_count
        ),
        (State::Queued, Priority::Urgent, false, 1)
    );
    assert_eq!(daemon.listed(), [requeued.id.clone(), "a".to_owned()]);
    let replay = daemon.item(&requeued.id);
    assert_eq!(
        (replay.text, replay.replay_of),
        ("old text".to_owned(), Nullable::Value("old".to_owned()))
    );
}

#[test]
fn requeue_of_unfinished_work_is_illegal_state() {
    let daemon = Daemon::start(&["a"], true, &["bm_daniel"]);
    assert_eq!(
        error_code(&daemon.ask(Operation::Requeue, r#"{"op":"requeue","id":"a"}"#)),
        ErrorCode::IllegalState
    );
}

#[test]
fn requeue_of_an_unknown_id_is_not_found() {
    let daemon = Daemon::start(&[], true, &["bm_daniel"]);
    assert_eq!(
        error_code(&daemon.ask(Operation::Requeue, r#"{"op":"requeue","id":"missing"}"#)),
        ErrorCode::NotFound
    );
}

#[test]
fn concurrent_clients_submissions_all_land_in_each_clients_order() {
    let daemon = Daemon::start(&[], true, &["bm_daniel"]);
    // Any arrival order is legal; the oracle is order-independent: every
    // submission is accepted and each client's items keep its own order.
    let ids: Vec<Vec<String>> = thread::scope(|scope| {
        let handles: Vec<_> = (0..2)
            .map(|client| {
                let daemon = &daemon;
                scope.spawn(move || {
                    (0..4)
                        .map(|index| {
                            daemon
                                .submitted(&format!(
                                    r#"{{"op":"submit","text":"c{client} n{index}"}}"#
                                ))
                                .id
                        })
                        .collect::<Vec<_>>()
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|handle| handle.join().unwrap())
            .collect()
    });
    let listed = daemon.listed();
    for own in ids {
        let order: Vec<&String> = listed.iter().filter(|id| own.contains(id)).collect();
        assert_eq!(
            order,
            own.iter().collect::<Vec<_>>(),
            "a client's submissions are missing or reordered"
        );
    }
}
