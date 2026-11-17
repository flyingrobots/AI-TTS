// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Fixture access, controlled clocks, and the Python-shaped projection of a store.

#![allow(dead_code, reason = "each test binary uses a different subset")]

pub(crate) mod golden_ops;
pub(crate) mod sequences;

use std::cell::Cell;
use std::path::{Path, PathBuf};
use std::rc::Rc;

use aitts_store::{Clock, Segment, Store, Utterance, names};
use serde_json::{Map, Value, json};

/// Seconds that advance by one per reading, as the Python fixture generator's clock.
#[derive(Clone)]
pub(crate) struct SteppingClock(pub(crate) Rc<Cell<f64>>);

impl SteppingClock {
    pub(crate) fn starting_at(seconds: f64) -> Self {
        Self(Rc::new(Cell::new(seconds)))
    }
}

impl Clock for SteppingClock {
    fn now(&self) -> f64 {
        let next = self.0.get() + 1.0;
        self.0.set(next);
        next
    }
}

/// The clock the fixture generator holds still while Python recovers.
pub(crate) struct FixedClock(pub(crate) f64);

impl Clock for FixedClock {
    fn now(&self) -> f64 {
        self.0
    }
}

pub(crate) const RECOVER_AT: f64 = 2_000.0;

pub(crate) fn fixture(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(name)
}

/// Copy a Python-written fixture so the test never writes the checked-in file.
pub(crate) fn copy_fixture(name: &str) -> (tempfile::TempDir, PathBuf) {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("state.db");
    std::fs::copy(fixture(&format!("{name}.db")), &path).unwrap();
    (dir, path)
}

pub(crate) fn expected(name: &str) -> Value {
    let text = std::fs::read_to_string(fixture(&format!("{name}.json"))).unwrap();
    serde_json::from_str(&text).unwrap()
}

fn segment(segment: &Segment) -> Value {
    json!({
        "index": segment.index,
        "text": segment.text,
        "state": names::state(segment.state),
        "error": segment.error,
        "duration_ms": segment.duration_ms,
        "played_ms": segment.played_ms,
        "audio_path": segment.audio_path,
        "generation_artifact_id": segment.generation_artifact_id,
    })
}

fn utterance(store: &Store, utterance: &Utterance) -> Value {
    let segments: Vec<Value> = store
        .queue()
        .segments(&utterance.id)
        .unwrap()
        .iter()
        .map(segment)
        .collect();
    json!({
        "id": utterance.id,
        "text": utterance.text,
        "voice": utterance.voice,
        "speed": utterance.speed,
        "order_key": utterance.order_key,
        "submitted_at": utterance.submitted_at,
        "state_changed_at": utterance.state_changed_at,
        "source": utterance.source,
        "error": utterance.error,
        "duration_ms": utterance.duration_ms,
        "played_ms": utterance.played_ms,
        "audio_path": utterance.audio_path,
        "replay_of": utterance.replay_of,
        "generation_artifact_id": utterance.generation_artifact_id,
        "engine": utterance.engine,
        "playback": utterance.playback,
        "sensitivity": names::sensitivity(utterance.sensitivity),
        "priority": names::priority(utterance.priority),
        "state": names::state(utterance.state),
        "segments": segments,
    })
}

fn ids(utterances: &[Utterance]) -> Value {
    utterances.iter().map(|u| json!(u.id)).collect()
}

/// The same projection the Python generator writes, read through the four interfaces.
pub(crate) fn dump(store: &Store, all_ids: &[String]) -> Value {
    let queue = store.queue();
    let utterances: Vec<Value> = all_ids
        .iter()
        .map(|id| utterance(store, &queue.get(id).unwrap().unwrap()))
        .collect();
    let settings: Map<String, Value> = store
        .settings()
        .all()
        .unwrap()
        .into_iter()
        .map(|(key, value)| (key, json!(value)))
        .collect();
    let voices: Vec<Value> = store
        .voices()
        .list()
        .unwrap()
        .iter()
        .map(|v| {
            json!({"source": v.source, "voice": v.voice, "pinned": v.pinned, "assigned_at": v.assigned_at})
        })
        .collect();
    json!({
        "utterances": utterances,
        "input": ids(&queue.input().unwrap()),
        "playback": ids(&queue.playback().unwrap()),
        "history": ids(&store.history().list(100, None).unwrap()),
        "settings": settings,
        "voices": voices,
    })
}

/// The utterance ids an expected projection names, in its order.
pub(crate) fn expected_ids(expected: &Value) -> Vec<String> {
    expected["utterances"]
        .as_array()
        .unwrap()
        .iter()
        .map(|u| u["id"].as_str().unwrap().to_owned())
        .collect()
}
