// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The terminal dashboard's state: what it shows from daemon snapshots and
//! events, and what each key does. It draws nothing and opens no socket; the
//! caller supplies snapshots, events, keys and the clock.

use serde::Serialize;
use serde_json::{Value, json};

/// Two `d` presses on the same clip within this many seconds cancel it.
const DELETE_WINDOW_SECONDS: f64 = 1.0;
/// Table cells keep this many characters.
const CELL_CHARACTERS: usize = 160;
const CONNECTED: &str = "Connected · q closes this view; speech keeps running";

/// Source text with control characters made visible, as `\x1b`.
pub fn literal_text(value: &str) -> String {
    value
        .chars()
        .map(|character| {
            if character.is_control() && character != '\n' && character != '\t' {
                format!("\\x{:02x}", u32::from(character))
            } else {
                character.to_string()
            }
        })
        .collect()
}

/// `m:ss`, or `--:--` when unknown.
pub fn clock_text(milliseconds: Option<i64>) -> String {
    let Some(milliseconds) = milliseconds else {
        return "--:--".to_owned();
    };
    let seconds = milliseconds.max(0) / 1000;
    format!("{}:{:02}", seconds / 60, seconds % 60)
}

/// The 20-cell dBFS bar for an output peak, or `Audio level unavailable`.
pub fn format_meter(peak: Option<f64>) -> String {
    const WIDTH: f64 = 20.0;
    let Some(peak) = peak.filter(|peak| peak.is_finite()) else {
        return "Audio level unavailable".to_owned();
    };
    let peak = peak.clamp(0.0, 1.0);
    let decibels = if peak > 0.0 {
        (20.0 * peak.log10()).max(-60.0)
    } else {
        -60.0
    };
    // Python's round() rounds half to even.
    let filled = ((decibels + 60.0) / 60.0 * WIDTH).round_ties_even();
    let filled: usize = (0..=20u8)
        .find(|n| f64::from(*n) >= filled)
        .map_or(20, usize::from);
    let label = if peak > 0.0 {
        format!("{decibels:.0}")
    } else {
        "-inf".to_owned()
    };
    format!(
        "Output [{}{}] {label} dBFS",
        "█".repeat(filled),
        "·".repeat(20 - filled)
    )
}

/// Python's `str()` of a JSON value.
fn python_str(value: &Value) -> String {
    match value {
        Value::Null => "None".to_owned(),
        Value::Bool(true) => "True".to_owned(),
        Value::Bool(false) => "False".to_owned(),
        Value::String(text) => text.clone(),
        other => other.to_string(),
    }
}

/// Python's `str.title()`: each run of letters starts upper case.
fn title(text: &str) -> String {
    let mut previous_letter = false;
    text.chars()
        .map(|character| {
            let out: String = if previous_letter {
                character.to_lowercase().collect()
            } else {
                character.to_uppercase().collect()
            };
            previous_letter = character.is_alphabetic();
            out
        })
        .collect()
}

/// Python's `str.isspace()`, which also counts U+001C to U+001F.
fn python_space(character: char) -> bool {
    character.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&character)
}

/// A table cell: whitespace runs to one space, control characters escaped,
/// then at most 160 characters.
fn cell(value: Option<&Value>) -> String {
    let text = value.map_or_else(String::new, python_str);
    let joined = text
        .split(python_space)
        .filter(|word| !word.is_empty())
        .collect::<Vec<_>>()
        .join(" ");
    literal_text(&joined)
        .chars()
        .take(CELL_CHARACTERS)
        .collect()
}

/// One table: rows keyed by clip id, and the selected row.
#[derive(Debug, Default)]
struct Table {
    ids: Vec<String>,
    rows: Vec<Vec<String>>,
    cursor: usize,
}

impl Table {
    fn selected(&self) -> Option<&String> {
        self.ids.get(self.cursor)
    }

    /// Replace the rows; keep the selected clip selected when it remains.
    fn fill(&mut self, items: &[&Value], fields: &[&str]) {
        let selected = self.selected().cloned();
        let previous = self.cursor;
        self.ids = items.iter().map(|item| python_str(&item["id"])).collect();
        self.rows = items
            .iter()
            .map(|item| fields.iter().map(|field| cell(item.get(*field))).collect())
            .collect();
        let row = selected
            .and_then(|id| self.ids.iter().position(|other| *other == id))
            .unwrap_or(previous);
        self.cursor = if self.ids.is_empty() {
            0
        } else {
            row.min(self.ids.len() - 1)
        };
    }

    fn step(&mut self, delta: isize) {
        let last = self.ids.len().saturating_sub(1);
        self.cursor = self.cursor.saturating_add_signed(delta).min(last);
    }
}

/// Which table keys act on.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
enum Focus {
    #[default]
    Queue,
    History,
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
#[derive(Debug)]
pub struct Dashboard {
    snapshot: Value,
    connected: bool,
    queue: Table,
    history: Table,
    focus: Focus,
    meter: String,
    status: String,
    /// The clip and time of a first `d`, until another key.
    delete_candidate: Option<(String, f64)>,
}

impl Default for Dashboard {
    fn default() -> Self {
        Self::new()
    }
}

impl Dashboard {
    /// A dashboard that is still connecting.
    pub fn new() -> Self {
        Self {
            snapshot: json!({}),
            connected: false,
            queue: Table::default(),
            history: Table::default(),
            focus: Focus::Queue,
            meter: format_meter(None),
            status: "Connecting…".to_owned(),
            delete_candidate: None,
        }
    }

    /// The subscription is acknowledged and `snapshot` was read.
    pub fn connected(&mut self, snapshot: Value) {
        self.refresh(snapshot);
        self.connected = true;
        CONNECTED.clone_into(&mut self.status);
    }

    /// The connection failed; the dashboard retries.
    pub fn disconnected(&mut self, reason: &str) {
        self.connected = false;
        self.status = literal_text(&format!("Disconnected: {reason} · retrying…"));
    }

    /// `snapshot.status`, or null.
    fn status(&self) -> &Value {
        self.snapshot.get("status").unwrap_or(&Value::Null)
    }

    fn pending(&self) -> Vec<&Value> {
        self.snapshot
            .get("plan")
            .and_then(Value::as_array)
            .map_or_else(Vec::new, |plan| {
                plan.iter()
                    .filter(|item| {
                        !matches!(
                            item.get("state").and_then(Value::as_str),
                            Some("Playing" | "Paused")
                        )
                    })
                    .collect()
            })
    }

    /// A newer snapshot.
    pub fn refresh(&mut self, snapshot: Value) {
        self.snapshot = snapshot;
        let pending: Vec<Value> = self.pending().into_iter().cloned().collect();
        let history: Vec<Value> = self
            .snapshot
            .get("history")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        self.queue.fill(
            &pending.iter().collect::<Vec<_>>(),
            &["priority", "voice", "state", "text"],
        );
        self.history.fill(
            &history.iter().collect::<Vec<_>>(),
            &["voice", "state", "text"],
        );
    }

    /// One daemon event. `snapshot` reads a fresh snapshot when the event needs one.
    pub fn event(&mut self, event: &Value, snapshot: &mut dyn FnMut() -> Value) {
        if event.get("event") != Some(&json!("playback_progress")) {
            self.refresh(snapshot());
            return;
        }
        if event.get("playback_held") != self.status().get("playback_held") {
            self.refresh(snapshot());
        }
        let Some(current) = self
            .snapshot
            .pointer_mut("/status/current")
            .and_then(Value::as_object_mut)
        else {
            return;
        };
        if event.get("id") != current.get("id") {
            return;
        }
        let position = event.get("position_ms").cloned().unwrap_or(Value::Null);
        current.insert("position_ms".to_owned(), position);
        self.meter = format_meter(event.get("audio_peak").and_then(Value::as_f64));
    }

    fn command(&mut self, mut payload: Value) -> Effect {
        if !self.connected {
            "Daemon unavailable; command was not sent.".clone_into(&mut self.status);
            return Effect::None;
        }
        if let Value::Object(map) = &mut payload {
            map.insert("origin".to_owned(), json!("tui"));
        }
        Effect::Command(payload)
    }

    fn table(&mut self) -> &mut Table {
        match self.focus {
            Focus::Queue => &mut self.queue,
            Focus::History => &mut self.history,
        }
    }

    fn delete(&mut self, now: f64) -> Effect {
        let Some(id) = self
            .queue
            .selected()
            .cloned()
            .filter(|_| self.focus == Focus::Queue)
        else {
            return Effect::None;
        };
        let previous = self.delete_candidate.replace((id.clone(), now));
        if previous.is_some_and(|(other, then)| other == id && now - then < DELETE_WINDOW_SECONDS) {
            self.delete_candidate = None;
            return self.command(json!({"op": "cancel", "id": id}));
        }
        "Press d again to cancel this queued clip.".clone_into(&mut self.status);
        Effect::None
    }

    fn reorder(&mut self, delta: isize) -> Effect {
        let Some(id) = self
            .queue
            .selected()
            .cloned()
            .filter(|_| self.focus == Focus::Queue)
        else {
            return Effect::None;
        };
        let mut ids: Vec<String> = self
            .pending()
            .iter()
            .map(|item| python_str(&item["id"]))
            .collect();
        let Some(index) = ids.iter().position(|other| *other == id) else {
            return Effect::None;
        };
        match index.checked_add_signed(delta).filter(|to| *to < ids.len()) {
            Some(to) => {
                ids.swap(index, to);
                self.command(json!({"op": "reorder", "ids": ids}))
            }
            None => Effect::None,
        }
    }

    /// A key press at monotonic time `now` in seconds.
    pub fn key(&mut self, key: &str, now: f64) -> Effect {
        if key != "d" {
            self.delete_candidate = None;
        }
        match key {
            "space" => {
                let held = self.status().get("playback_held") == Some(&json!(true));
                self.command(json!({"op": if held { "resume" } else { "pause" }}))
            }
            "j" | "k" => {
                self.table().step(if key == "j" { 1 } else { -1 });
                Effect::None
            }
            "d" => self.delete(now),
            "J" => self.reorder(1),
            "K" => self.reorder(-1),
            "n" => self.command(json!({"op": "next_segment"})),
            "p" => self.command(json!({"op": "previous_segment"})),
            "r" => self.command(json!({"op": "rewind"})),
            "s" => self.command(json!({"op": "skip"})),
            "tab" => {
                self.focus = match self.focus {
                    Focus::Queue => Focus::History,
                    Focus::History => Focus::Queue,
                };
                Effect::None
            }
            "enter" => match self
                .history
                .selected()
                .cloned()
                .filter(|_| self.focus == Focus::History)
            {
                Some(id) => self.command(json!({"op": "requeue", "id": id})),
                None => Effect::None,
            },
            "q" => Effect::Quit,
            _ => Effect::None,
        }
    }

    /// The command from [`Effect::Command`] finished; on success the value is a fresh snapshot.
    pub fn command_done(&mut self, outcome: Result<Value, String>) {
        match outcome {
            Ok(snapshot) => {
                self.refresh(snapshot);
                "Connected".clone_into(&mut self.status);
            }
            Err(reason) => {
                self.status = literal_text(&format!("Could not complete command: {reason}"));
            }
        }
    }

    /// What is shown now.
    pub fn screen(&self) -> Screen {
        let status = self.status();
        let current = status["current"].as_object();
        let field = |key: &str| current.and_then(|map| map.get(key));
        let segment = field("active_segment")
            .and_then(Value::as_object)
            .filter(|s| !s.is_empty());
        let position = field("position_ms").filter(|p| !p.is_null() && *p != &json!(0));
        let duration = field("duration_ms").filter(|d| !d.is_null());
        let voice = field("voice")
            .or_else(|| status.get("voice"))
            .map_or_else(String::new, python_str);
        let speed = field("speed").map_or_else(|| "1".to_owned(), python_str);
        let rate = self
            .snapshot
            .get("settings")
            .unwrap_or(&Value::Null)
            .get("playback_rate")
            .map_or_else(|| "1".to_owned(), python_str);
        let state = status
            .get("playback_state")
            .map_or_else(|| "idle".to_owned(), python_str);
        let mut details = format!(
            "{} · {voice} · voice speed {speed}x · playback {rate}x · {} / {}",
            title(&state),
            clock_text(position.and_then(Value::as_i64).or(Some(0))),
            clock_text(duration.and_then(Value::as_i64)),
        );
        if let Some(segment) = segment {
            let part = |key: &str| segment.get(key).map_or_else(String::new, python_str);
            details = format!("{details} · Chunk {}/{}", part("number"), part("count"));
        }
        let spoken = segment
            .and_then(|segment| segment.get("text"))
            .or_else(|| field("text"))
            .map_or_else(String::new, python_str);
        let has_current = current.is_some_and(|map| !map.is_empty());
        let progress = Progress {
            total: if has_current {
                duration.and_then(Value::as_f64)
            } else {
                Some(1.0)
            },
            progress: position.and_then(Value::as_f64).unwrap_or(0.0),
        };
        Screen {
            details: literal_text(&details),
            spoken: literal_text(&spoken),
            meter: self.meter.clone(),
            progress,
            queue: self.queue.rows.clone(),
            queue_cursor: self.queue.cursor,
            history: self.history.rows.clone(),
            history_cursor: self.history.cursor,
            focused: match self.focus {
                Focus::Queue => "queue",
                Focus::History => "history",
            },
            status: self.status.clone(),
        }
    }
}
