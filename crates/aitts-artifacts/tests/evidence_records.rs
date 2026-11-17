// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: medium (owned temporary files). Contract: the evidence files a clip
//! directory holds. Oracle: `fixtures/records`, which the Python `ClipEvidence`
//! writers left for the same scenario, clock, session and lowered log limit
//! (`scripts/generate_evidence_record_fixtures.py`). Records are compared parsed:
//! JSON files as values, logs line by line as values, text files as bytes.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

use std::cell::Cell;
use std::collections::BTreeMap;
use std::fs;
use std::os::unix::fs::{PermissionsExt, symlink};
use std::path::Path;

use aitts_artifacts::records::{EvidenceClock, EvidenceRecorder, GenerationInput, Phase};
use serde_json::{Map, Value, json};

const FIXTURE: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/records");
const LOG_LIMIT: usize = 400;

/// Each reading adds one second, as the fixture script's clocks do.
struct SteppingClock {
    wall: Cell<f64>,
    monotonic: Cell<f64>,
}

impl EvidenceClock for SteppingClock {
    fn wall(&self) -> f64 {
        let now = self.wall.get();
        self.wall.set(now + 1.0);
        now
    }
    fn monotonic(&self) -> f64 {
        let now = self.monotonic.get();
        self.monotonic.set(now + 1.0);
        now
    }
}

fn recorder(root: &Path) -> EvidenceRecorder<SteppingClock> {
    let clock = SteppingClock {
        wall: Cell::new(1_800_000_000.0),
        monotonic: Cell::new(100.0),
    };
    EvidenceRecorder::new(
        root,
        "fixture-session",
        json!({"os": "fixture", "architecture": "fixture"}),
        clock,
    )
    .with_log_limit(LOG_LIMIT)
}

fn details(value: &Value) -> Map<String, Value> {
    value.as_object().unwrap().clone()
}

/// The fixture script's scenario.
fn run_scenario(root: &Path) {
    let evidence = recorder(root);
    let input = GenerationInput {
        artifact_id: "clip-a",
        utterance_id: "utt_0001",
        segment_index: Some(0),
        text: "Hello, ünïcode world.",
        voice: "af_heart",
        speed: 1.25,
    };
    evidence.prepare(&input, "kokoro").unwrap();
    evidence
        .record(
            "clip-a",
            Phase::Synthesis,
            "chunk",
            &details(&json!({"index": 1, "text": "ünï"})),
        )
        .unwrap();
    evidence
        .generated(
            "clip-a",
            &json!({"model": "kokoro-82m", "voice": "af_heart"}),
        )
        .unwrap();
    evidence
        .record(
            "clip-a",
            Phase::Playback,
            "played",
            &details(&json!({"playback_session": "p1"})),
        )
        .unwrap();
    evidence
        .record(
            "clip-a",
            Phase::Playback,
            "big",
            &details(&json!({"blob": "x".repeat(LOG_LIMIT)})),
        )
        .unwrap();
    for index in 0..6 {
        evidence
            .record(
                "clip-b",
                Phase::Synthesis,
                "chunk",
                &details(&json!({"index": index})),
            )
            .unwrap();
    }
}

/// Relative path to bytes, for every file beneath `root`.
fn files(root: &Path) -> BTreeMap<String, Vec<u8>> {
    let mut out = BTreeMap::new();
    for clip in fs::read_dir(root).unwrap() {
        let clip = clip.unwrap();
        for file in fs::read_dir(clip.path()).unwrap() {
            let file = file.unwrap();
            let name = format!(
                "{}/{}",
                clip.file_name().to_str().unwrap(),
                file.file_name().to_str().unwrap()
            );
            out.insert(name, fs::read(file.path()).unwrap());
        }
    }
    out
}

fn scenario_files() -> (tempfile::TempDir, BTreeMap<String, Vec<u8>>) {
    let dir = tempfile::tempdir().unwrap();
    run_scenario(&dir.path().join("root"));
    let found = files(&dir.path().join("root"));
    (dir, found)
}

fn has_extension(name: &str, extension: &str) -> bool {
    Path::new(name)
        .extension()
        .is_some_and(|found| found == extension)
}

fn lines(bytes: &[u8]) -> Vec<Value> {
    std::str::from_utf8(bytes)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

#[test]
fn the_clip_directories_hold_the_python_file_names() {
    let (_dir, rust) = scenario_files();
    let python = files(Path::new(FIXTURE));
    assert_eq!(
        rust.keys().collect::<Vec<_>>(),
        python.keys().collect::<Vec<_>>()
    );
}

#[test]
fn json_records_equal_the_python_records() {
    let (_dir, rust) = scenario_files();
    let python = files(Path::new(FIXTURE));
    let mut compared = 0;
    for (name, bytes) in python
        .iter()
        .filter(|(name, _)| has_extension(name, "json"))
    {
        let parsed: Value = serde_json::from_slice(bytes).unwrap();
        let ours: Option<Value> = rust
            .get(name)
            .map(|ours| serde_json::from_slice(ours).unwrap());
        assert_eq!(ours, Some(parsed), "{name}");
        compared += 1;
    }
    assert_eq!(compared, 2, "JSON records compared");
}

#[test]
fn event_logs_equal_the_python_logs_line_by_line() {
    let (_dir, rust) = scenario_files();
    let python = files(Path::new(FIXTURE));
    let mut compared = 0;
    for (name, bytes) in python
        .iter()
        .filter(|(name, _)| has_extension(name, "jsonl"))
    {
        assert_eq!(
            rust.get(name).map(|ours| lines(ours)),
            Some(lines(bytes)),
            "{name}"
        );
        compared += 1;
    }
    assert_eq!(compared, 4, "logs compared, including the rotated one");
}

#[test]
fn text_records_have_the_python_bytes() {
    let (_dir, rust) = scenario_files();
    let python = files(Path::new(FIXTURE));
    let mut compared = 0;
    for (name, bytes) in python.iter().filter(|(name, _)| has_extension(name, "txt")) {
        assert_eq!(rust.get(name), Some(bytes), "{name}");
        compared += 1;
    }
    assert_eq!(compared, 2, "text records compared");
}

#[test]
fn every_record_file_and_directory_is_owner_only() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("root");
    run_scenario(&root);
    let mode = |path: &Path| fs::metadata(path).unwrap().permissions().mode() & 0o777;
    let mut checked = 0;
    assert_eq!(mode(&root), 0o700);
    for clip in fs::read_dir(&root).unwrap() {
        let clip = clip.unwrap().path();
        assert_eq!(mode(&clip), 0o700, "{}", clip.display());
        for file in fs::read_dir(&clip).unwrap() {
            let file = file.unwrap().path();
            assert_eq!(mode(&file), 0o600, "{}", file.display());
            checked += 1;
        }
    }
    assert_eq!(checked, 8, "files checked");
}

#[test]
fn an_event_over_the_python_limit_is_replaced_by_an_omission_row() {
    let dir = tempfile::tempdir().unwrap();
    let clock = SteppingClock {
        wall: Cell::new(1.0),
        monotonic: Cell::new(1.0),
    };
    let evidence = EvidenceRecorder::new(dir.path(), "s", json!({}), clock);
    // Oracle: Python `_MAX_LOG_BYTES = 1024 * 1024`.
    let blob = "x".repeat(1024 * 1024);
    evidence
        .record(
            "c",
            Phase::Synthesis,
            "big",
            &details(&json!({"blob": blob})),
        )
        .unwrap();
    let logged = lines(&fs::read(dir.path().join("c/synthesis.jsonl")).unwrap());
    assert_eq!(
        logged,
        [json!({"at": 1.0, "event": "oversized_event_omitted", "process_session": "s"})]
    );
}

#[test]
fn a_symbolic_link_in_place_of_a_log_is_refused_and_its_target_unchanged() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("root");
    let target = dir.path().join("target");
    fs::write(&target, b"kept").unwrap();
    fs::create_dir_all(root.join("c")).unwrap();
    symlink(&target, root.join("c/playback.jsonl")).unwrap();
    assert!(
        recorder(&root)
            .record("c", Phase::Playback, "played", &Map::new())
            .is_err()
    );
    assert_eq!(fs::read(&target).unwrap(), b"kept");
}

#[test]
fn a_symbolic_link_in_place_of_a_clip_directory_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("root");
    let outside = dir.path().join("outside");
    fs::create_dir_all(&root).unwrap();
    fs::create_dir(&outside).unwrap();
    symlink(&outside, root.join("c")).unwrap();
    assert!(recorder(&root).generated("c", &json!({})).is_err());
    assert_eq!(fs::read_dir(&outside).unwrap().count(), 0);
}

#[test]
fn an_identity_that_escapes_the_root_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("root");
    assert!(recorder(&root).generated("../x", &json!({})).is_err());
    assert!(!dir.path().join("x").exists());
}

/// The byte length of the first Python-written `clip-b` event line, newline included.
fn python_line_length() -> usize {
    let log = fs::read(Path::new(FIXTURE).join("clip-b/synthesis.previous.jsonl")).unwrap();
    log.iter().position(|byte| *byte == b'\n').unwrap() + 1
}

/// Log two `clip-b`-shaped events under `limit`; return the lines left in the current log.
fn lines_after_two_events(limit: usize) -> usize {
    let dir = tempfile::tempdir().unwrap();
    let clock = SteppingClock {
        wall: Cell::new(1_800_000_005.0),
        monotonic: Cell::new(104.0),
    };
    let evidence = EvidenceRecorder::new(dir.path(), "fixture-session", json!({}), clock)
        .with_log_limit(limit);
    for index in 0..2 {
        evidence
            .record(
                "c",
                Phase::Synthesis,
                "chunk",
                &details(&json!({"index": index})),
            )
            .unwrap();
    }
    lines(&fs::read(dir.path().join("c/synthesis.jsonl")).unwrap()).len()
}

// Oracle: Python rotates when `size + len(line) > limit`, with its own line length.
#[test]
fn two_python_length_lines_fit_a_limit_of_exactly_their_size() {
    assert_eq!(lines_after_two_events(2 * python_line_length()), 2);
}

#[test]
fn two_python_length_lines_rotate_under_a_limit_one_byte_smaller() {
    assert_eq!(lines_after_two_events(2 * python_line_length() - 1), 1);
}
