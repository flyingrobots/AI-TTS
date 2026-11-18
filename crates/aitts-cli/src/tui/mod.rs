// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The terminal dashboard's state: what it shows from daemon snapshots and
//! events, and what each key does. It draws nothing and opens no socket; the
//! caller supplies snapshots, events, keys and the clock.
#![allow(clippy::todo, reason = "RED stub")]

use serde::Serialize;
use serde_json::Value;

/// Source text with control characters made visible, as `\x1b`.
pub fn literal_text(_value: &str) -> String {
    todo!()
}

/// `m:ss`, or `--:--` when unknown.
pub fn clock_text(_milliseconds: Option<i64>) -> String {
    todo!()
}

/// The 20-cell dBFS bar for an output peak, or `Audio level unavailable`.
pub fn format_meter(_peak: Option<f64>) -> String {
    todo!()
}

/// The progress bar's total (`None` while unknown) and position.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Progress {
    /// Total milliseconds; `None` is an indeterminate bar.
    pub total: Option<f64>,
    /// Elapsed milliseconds.
    pub progress: f64,
}

/// Everything the dashboard shows.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Screen {
    /// The now-playing line.
    pub details: String,
    /// The current chunk or clip text.
    pub spoken: String,
    /// The level meter line.
    pub meter: String,
    /// The progress bar.
    pub progress: Progress,
    /// Queue rows: priority, voice, state, text.
    pub queue: Vec<Vec<String>>,
    /// Selected queue row.
    pub queue_cursor: usize,
    /// History rows: voice, result, text.
    pub history: Vec<Vec<String>>,
    /// Selected history row.
    pub history_cursor: usize,
    /// `queue` or `history`.
    pub focused: &'static str,
    /// The status line.
    pub status: String,
}

/// What the caller does after a key.
#[derive(Clone, Debug, PartialEq)]
pub enum Effect {
    /// Nothing to send.
    None,
    /// Send this request, then call [`Dashboard::command_done`].
    Command(Value),
    /// Close the dashboard; speech keeps running.
    Quit,
}

/// The dashboard state.
#[derive(Debug, Default)]
pub struct Dashboard {}

impl Dashboard {
    /// A dashboard that is still connecting.
    pub fn new() -> Self {
        Self {}
    }

    /// The subscription is acknowledged and `snapshot` was read.
    pub fn connected(&mut self, _snapshot: Value) {
        todo!()
    }

    /// The connection failed; the dashboard retries.
    pub fn disconnected(&mut self, _reason: &str) {
        todo!()
    }

    /// A newer snapshot.
    pub fn refresh(&mut self, _snapshot: Value) {
        todo!()
    }

    /// One daemon event. `snapshot` reads a fresh snapshot when the event needs one.
    pub fn event(&mut self, _event: &Value, _snapshot: &mut dyn FnMut() -> Value) {
        todo!()
    }

    /// A key press at monotonic time `now` in seconds.
    pub fn key(&mut self, _key: &str, _now: f64) -> Effect {
        todo!()
    }

    /// The command from [`Effect::Command`] finished; on success `snapshot` is fresh.
    pub fn command_done(&mut self, _outcome: Result<Value, String>) {
        todo!()
    }

    /// What is shown now.
    pub fn screen(&self) -> Screen {
        todo!()
    }
}
