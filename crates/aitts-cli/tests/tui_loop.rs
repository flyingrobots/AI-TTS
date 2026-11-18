// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small (in-process; a recording terminal session and scripted daemon).
//! Oracles: issue #140 ("the terminal is restored after an exit and after a
//! panic"; the known failure "the terminal stays in raw mode after a
//! failure") and the Python dashboard's command flow (send, then read a
//! snapshot; `origin: tui`). The session records its calls; the terminal is
//! restored when `leave` is the last call and `enter` was called once.

#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    clippy::panic,
    reason = "test code fails loudly"
)]

mod support;

use aitts_cli::tui::{Commands, Input, Screen, Session, run};
use serde_json::{Value, json};
use std::io;
use std::sync::mpsc::channel;

#[derive(Default)]
struct Recorder {
    calls: Vec<&'static str>,
    last: Option<Screen>,
    fail_draw: bool,
}

impl Session for Recorder {
    fn enter(&mut self) -> io::Result<()> {
        self.calls.push("enter");
        Ok(())
    }
    fn draw(&mut self, screen: &Screen) -> io::Result<()> {
        self.calls.push("draw");
        self.last = Some(screen.clone());
        if self.fail_draw {
            Err(io::Error::other("terminal gone"))
        } else {
            Ok(())
        }
    }
    fn leave(&mut self) -> io::Result<()> {
        self.calls.push("leave");
        Ok(())
    }
}

struct Daemon {
    snapshot: Value,
    sent: Vec<Value>,
    panic_on_send: bool,
}

impl Commands for Daemon {
    fn snapshot(&mut self) -> Result<Value, String> {
        Ok(self.snapshot.clone())
    }
    fn send(&mut self, request: &Value) -> Result<(), String> {
        assert!(!self.panic_on_send, "planted failure in a command");
        self.sent.push(request.clone());
        Ok(())
    }
}

fn held() -> Value {
    support::tui::scenario("held queue")["snapshots"][0].clone()
}

fn daemon() -> Daemon {
    Daemon {
        snapshot: held(),
        sent: Vec::new(),
        panic_on_send: false,
    }
}

fn restored(calls: &[&str]) -> bool {
    calls.first() == Some(&"enter")
        && calls.last() == Some(&"leave")
        && calls.iter().filter(|call| **call == "enter").count() == 1
}

fn inputs(items: Vec<Input>) -> std::sync::mpsc::Receiver<Input> {
    let (sender, receiver) = channel();
    for item in items {
        sender.send(item).unwrap();
    }
    receiver
}

#[test]
fn q_leaves_the_terminal_restored() {
    let mut session = Recorder::default();
    let keys = inputs(vec![
        Input::Connected(held()),
        Input::Key("q".into()),
        Input::Key("space".into()),
    ]);
    let mut daemon = daemon();
    run(&mut session, &keys, &mut daemon, &|| 0.0).unwrap();
    assert!(restored(&session.calls), "{:?}", session.calls);
    assert!(daemon.sent.is_empty(), "a key after q was handled");
}

#[test]
fn closed_input_leaves_the_terminal_restored() {
    let mut session = Recorder::default();
    run(&mut session, &inputs(vec![]), &mut daemon(), &|| 0.0).unwrap();
    assert!(restored(&session.calls), "{:?}", session.calls);
}

#[test]
fn a_panic_in_a_command_leaves_the_terminal_restored() {
    let mut session = Recorder::default();
    let keys = inputs(vec![Input::Connected(held()), Input::Key("space".into())]);
    let mut daemon = Daemon {
        panic_on_send: true,
        ..daemon()
    };
    let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        run(&mut session, &keys, &mut daemon, &|| 0.0)
    }));
    assert!(outcome.is_err(), "the planted panic did not happen");
    assert!(restored(&session.calls), "{:?}", session.calls);
}

#[test]
fn a_terminal_error_leaves_the_terminal_restored() {
    let mut session = Recorder {
        fail_draw: true,
        ..Recorder::default()
    };
    let outcome = run(
        &mut session,
        &inputs(vec![Input::Connected(held())]),
        &mut daemon(),
        &|| 0.0,
    );
    assert!(outcome.is_err());
    assert!(restored(&session.calls), "{:?}", session.calls);
}

#[test]
fn a_key_sends_its_request_then_shows_a_fresh_snapshot() {
    let mut session = Recorder::default();
    let keys = inputs(vec![Input::Connected(held()), Input::Key("space".into())]);
    let mut daemon = daemon();
    run(&mut session, &keys, &mut daemon, &|| 0.0).unwrap();
    assert_eq!(daemon.sent, vec![json!({"op": "resume", "origin": "tui"})]);
    assert_eq!(session.last.unwrap().status, "Connected");
}

#[test]
fn the_screen_follows_connection_events_and_disconnects() {
    let mut session = Recorder::default();
    let event = json!({"event": "history_changed"});
    let keys = inputs(vec![
        Input::Connected(held()),
        Input::Event(event),
        Input::Disconnected("daemon stopped".into()),
    ]);
    run(&mut session, &keys, &mut daemon(), &|| 0.0).unwrap();
    let screen = session.last.unwrap();
    assert_eq!(screen.status, "Disconnected: daemon stopped · retrying…");
    assert_eq!(screen.queue.len(), 5, "the last snapshot stays shown");
}
