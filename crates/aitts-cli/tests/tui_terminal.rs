// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small (in-process; the terminal is a byte buffer and a recorded raw-mode switch).
//! Oracles: issue #140 ("the terminal is restored after an exit and after a
//! panic"), the xterm private modes crossterm writes for the alternate screen
//! (`CSI ? 1049 h` to enter, `CSI ? 1049 l` to leave) and the cursor
//! (`CSI ? 25 l` / `h`), and the Python dashboard's key bindings.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::unnecessary_wraps,
    clippy::string_slice,
    reason = "test code fails loudly; record_raw must match RawMode"
)]

use aitts_cli::tui::{Commands, Input, TerminalSession, key_name, run};
use ratatui::Viewport;
use ratatui::crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use ratatui::layout::Rect;
use serde_json::{Value, json};
use std::cell::RefCell;
use std::io;
use std::rc::Rc;
use std::sync::mpsc::channel;

thread_local! {
    static RAW: RefCell<Vec<bool>> = const { RefCell::new(Vec::new()) };
}

/// A writer the test can read after the session has written to it.
#[derive(Clone, Default)]
struct Shared(Rc<RefCell<Vec<u8>>>);

impl io::Write for Shared {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.0.borrow_mut().extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn record_raw(on: bool) -> io::Result<()> {
    RAW.with(|raw| raw.borrow_mut().push(on));
    Ok(())
}

const ENTER_ALTERNATE: &str = "\u{1b}[?1049h";
const LEAVE_ALTERNATE: &str = "\u{1b}[?1049l";
const SHOW_CURSOR: &str = "\u{1b}[?25h";

struct Panics;

impl Commands for Panics {
    fn snapshot(&mut self) -> Result<Value, String> {
        Ok(json!({}))
    }
    fn send(&mut self, _request: &Value) -> Result<(), String> {
        panic!("planted failure in a command")
    }
}

/// Run until the inputs end; return the bytes written and the raw-mode switches.
fn session_after(items: Vec<Input>, panics: bool) -> (String, Vec<bool>) {
    RAW.with(|raw| raw.borrow_mut().clear());
    let viewport = Viewport::Fixed(Rect::new(0, 0, 40, 12));
    let out = Shared::default();
    let mut session = TerminalSession::new(out.clone(), record_raw, viewport).unwrap();
    let (sender, receiver) = channel();
    for item in items {
        sender.send(item).unwrap();
    }
    drop(sender);
    let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        run(&mut session, &receiver, &mut Panics, &|| 0.0)
    }));

    assert_eq!(outcome.is_err(), panics, "panic outcome");
    drop(session);
    let written = String::from_utf8_lossy(&out.0.borrow()).into_owned();
    (written, RAW.with(|raw| raw.borrow().clone()))
}

fn assert_left(written: &str, raw: &[bool]) {
    assert_eq!(raw, [true, false], "raw mode switches");
    let enter = written
        .find(ENTER_ALTERNATE)
        .expect("never entered the alternate screen");
    let leave = written
        .rfind(LEAVE_ALTERNATE)
        .expect("never left the alternate screen");
    assert!(enter < leave, "left before entering");
    assert!(
        written[leave..].contains(SHOW_CURSOR),
        "cursor not shown after leaving"
    );
}

#[test]
fn q_leaves_raw_mode_and_the_alternate_screen() {
    let (written, raw) = session_after(vec![Input::Key("q".into())], false);
    assert_left(&written, &raw);
}

#[test]
fn a_panic_leaves_raw_mode_and_the_alternate_screen() {
    let snapshot = json!({"status": {"playback_held": true}});
    let items = vec![Input::Connected(snapshot), Input::Key("space".into())];
    let (written, raw) = session_after(items, true);
    assert_left(&written, &raw);
}

#[test]
fn keys_have_the_python_binding_names() {
    let key = |code, modifiers| key_name(KeyEvent::new(code, modifiers));
    let none = KeyModifiers::NONE;
    assert_eq!(key(KeyCode::Char(' '), none).as_deref(), Some("space"));
    assert_eq!(key(KeyCode::Char('j'), none).as_deref(), Some("j"));
    assert_eq!(
        key(KeyCode::Char('J'), KeyModifiers::SHIFT).as_deref(),
        Some("J")
    );
    assert_eq!(key(KeyCode::Enter, none).as_deref(), Some("enter"));
    assert_eq!(key(KeyCode::Tab, none).as_deref(), Some("tab"));
    assert_eq!(
        key(KeyCode::Char('c'), KeyModifiers::CONTROL).as_deref(),
        Some("q")
    );
    assert_eq!(key(KeyCode::Char('d'), KeyModifiers::CONTROL), None);
    assert_eq!(key(KeyCode::F(1), none), None);
}
