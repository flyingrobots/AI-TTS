// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module runs the dashboard: the input loop, the daemon watcher that
//! subscribes again after a failure, and the terminal session that is always
//! left (raw mode off, main screen back) on exit, on error and on panic.
#![allow(clippy::todo, reason = "RED stub")]

use super::Screen;
use serde_json::Value;
use std::io;
use std::path::Path;
use std::sync::atomic::AtomicBool;
use std::sync::mpsc::{Receiver, Sender};

/// One input to the dashboard loop.
#[derive(Clone, Debug, PartialEq)]
pub enum Input {
    /// A key, named as the dashboard model names it (`space`, `j`, `enter`, ...).
    Key(String),
    /// A daemon event.
    Event(Value),
    /// The subscription is acknowledged; this is a fresh snapshot.
    Connected(Value),
    /// The connection failed; the watcher retries.
    Disconnected(String),
}

/// The terminal the dashboard draws on.
pub trait Session {
    /// Enter raw mode and the alternate screen.
    ///
    /// # Errors
    /// The terminal refused.
    fn enter(&mut self) -> io::Result<()>;
    /// Draw one screen.
    ///
    /// # Errors
    /// Writing to the terminal failed.
    fn draw(&mut self, screen: &Screen) -> io::Result<()>;
    /// Leave the alternate screen and raw mode.
    ///
    /// # Errors
    /// The terminal refused.
    fn leave(&mut self) -> io::Result<()>;
}

/// Daemon requests made by the loop.
pub trait Commands {
    /// A fresh snapshot.
    ///
    /// # Errors
    /// The daemon's failure, as text for the status line.
    fn snapshot(&mut self) -> Result<Value, String>;
    /// Send one request built by a key.
    ///
    /// # Errors
    /// The daemon's failure, as text for the status line.
    fn send(&mut self, request: &Value) -> Result<(), String>;
}

/// Run the dashboard until `q`, or until `inputs` closes. The session is left
/// in every case, including a panic in a command.
///
/// # Errors
/// The terminal failed.
pub fn run(
    _session: &mut dyn Session,
    _inputs: &Receiver<Input>,
    _commands: &mut dyn Commands,
    _clock: &dyn Fn() -> f64,
) -> io::Result<()> {
    todo!()
}

/// Subscribe to `socket` (with playback progress) and forward a snapshot and
/// each event to `inputs`, until `stop` is set or `inputs` closes. After a
/// failure it reports [`Input::Disconnected`], calls `wait`, and subscribes again.
pub fn watch(_socket: &Path, _inputs: &Sender<Input>, _stop: &AtomicBool, _wait: &dyn Fn()) {
    todo!()
}
