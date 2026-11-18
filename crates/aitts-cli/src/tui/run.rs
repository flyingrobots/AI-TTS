// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module runs the dashboard: the input loop, the daemon watcher that
//! subscribes again after a failure, and the terminal session that is always
//! left (raw mode off, main screen back) on exit, on error and on panic.

use super::{Dashboard, Effect, Screen};
use aitts_client::{Client, ClientError, Delivery, ReconnectPolicy};
use aitts_protocol::decode_request;
use aitts_protocol::reply::Reply;
use serde_json::{Value, json};
use std::io;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{Receiver, Sender};
use std::time::Duration;

/// Each command and snapshot request waits at most this long, as the Python client.
const REQUEST_LIMIT: Duration = Duration::from_secs(5);
/// A quiet subscription is read again after this long, so `stop` is noticed.
const QUIET: Duration = Duration::from_millis(250);
/// The Python dashboard reads up to 50 history items.
const HISTORY_LIMIT: u64 = 50;

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
    session: &mut dyn Session,
    inputs: &Receiver<Input>,
    commands: &mut dyn Commands,
    clock: &dyn Fn() -> f64,
) -> io::Result<()> {
    // Made before entering, so a terminal entered only part way is still left.
    let entered = Entered {
        session,
        left: false,
    };
    entered.session.enter()?;
    let mut dashboard = Dashboard::new();
    entered.session.draw(&dashboard.screen())?;
    for input in inputs {
        match input {
            Input::Connected(snapshot) => dashboard.connected(snapshot),
            Input::Disconnected(reason) => dashboard.disconnected(&reason),
            Input::Event(event) => {
                let shown = dashboard.snapshot().clone();
                dashboard.event(&event, &mut || {
                    commands.snapshot().unwrap_or_else(|_| shown.clone())
                });
            }
            Input::Key(key) => match dashboard.key(&key, clock()) {
                Effect::Quit => break,
                Effect::None => {}
                Effect::Command(request) => {
                    let outcome = commands.send(&request).and_then(|()| commands.snapshot());
                    dashboard.command_done(outcome);
                }
            },
        }
        entered.session.draw(&dashboard.screen())?;
    }
    entered.leave()
}

/// The entered terminal: left once, by [`Entered::leave`] or on drop (an
/// error return or a panic unwinding through [`run`]).
struct Entered<'session> {
    session: &'session mut dyn Session,
    left: bool,
}

impl Entered<'_> {
    fn leave(mut self) -> io::Result<()> {
        self.left = true;
        self.session.leave()
    }
}

impl Drop for Entered<'_> {
    fn drop(&mut self) {
        if !self.left {
            // Nothing can report this failure; the terminal is in the best state left.
            let _ = self.session.leave();
        }
    }
}

/// One snapshot, as the Python dashboard reads it.
///
/// # Errors
/// The daemon's error message, or why it could not be reached.
pub fn snapshot(socket: &Path) -> Result<Value, String> {
    let request = json!({"op": "snapshot", "limit": HISTORY_LIMIT});
    exchange(socket, &request)
}

fn exchange(socket: &Path, request: &Value) -> Result<Value, String> {
    let typed =
        decode_request(request.to_string().as_bytes()).map_err(|error| error.to_string())?;
    match Client::new(socket, REQUEST_LIMIT).request(&typed) {
        Ok(Reply::Error(refusal)) => Err(refusal.error.message),
        Ok(reply) => serde_json::to_value(reply).map_err(|error| error.to_string()),
        Err(error) => Err(error.to_string()),
    }
}

/// [`Commands`] over the daemon socket.
#[derive(Debug)]
pub struct SocketCommands<'socket> {
    /// The daemon socket.
    pub socket: &'socket Path,
}

impl Commands for SocketCommands<'_> {
    fn snapshot(&mut self) -> Result<Value, String> {
        snapshot(self.socket)
    }

    fn send(&mut self, request: &Value) -> Result<(), String> {
        exchange(self.socket, request).map(|_| ())
    }
}

/// Forward one subscription until `stop`, a closed `inputs`, or a failure.
fn forward(socket: &Path, inputs: &Sender<Input>, stop: &AtomicBool) -> Result<(), String> {
    let policy = ReconnectPolicy {
        delay: Duration::ZERO,
        attempts: 1,
    };
    let mut events = Client::new(socket, QUIET)
        .subscribe_to_progress(policy)
        .map_err(|error| error.to_string())?;
    if inputs.send(Input::Connected(snapshot(socket)?)).is_err() {
        return Ok(());
    }
    while !stop.load(Ordering::SeqCst) {
        let input = match events.next_delivery() {
            Ok(Delivery::Event(event)) => {
                Input::Event(serde_json::to_value(event).map_err(|error| error.to_string())?)
            }
            // Events sent while disconnected are lost, so read the state again.
            Ok(Delivery::Resubscribed) => Input::Connected(snapshot(socket)?),
            Err(ClientError::TimedOut) => continue,
            Err(error) => return Err(error.to_string()),
        };
        if inputs.send(input).is_err() {
            return Ok(());
        }
    }
    Ok(())
}

/// Subscribe to `socket` (with playback progress) and forward a snapshot and
/// each event to `inputs`, until `stop` is set or `inputs` closes. After a
/// failure it reports [`Input::Disconnected`], calls `wait`, and subscribes again.
pub fn watch(socket: &Path, inputs: &Sender<Input>, stop: &AtomicBool, wait: &dyn Fn()) {
    while !stop.load(Ordering::SeqCst) {
        match forward(socket, inputs, stop) {
            Ok(()) => return,
            Err(reason) => {
                if inputs.send(Input::Disconnected(reason)).is_err() {
                    return;
                }
            }
        }
        wait();
    }
}
