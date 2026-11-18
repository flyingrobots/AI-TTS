// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: medium (owned temporary files). Contract: the `request.json`,
//! `source.txt` and `audio.json` records. Oracle: `fixtures/writers/root`, which
//! the Python `ClipEvidence.submitted` and `audio_generated` wrote for the WAVs in
//! `fixtures/writers/audio` (written by `soundfile`) with the clock pinned
//! (`scripts/generate_evidence_writer_fixtures.py`). JSON is compared parsed.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    reason = "test code fails loudly"
)]

use std::fs;
use std::path::{Path, PathBuf};

use aitts_artifacts::records::{EvidenceClock, EvidenceRecorder};
use serde_json::{Value, json};

const FIXTURE: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/writers");

/// The fixture script's pinned `time.time()`.
struct PinnedClock;

impl EvidenceClock for PinnedClock {
    fn wall(&self) -> f64 {
        1_800_000_000.25
    }
    fn monotonic(&self) -> f64 {
        0.0
    }
}

fn recorder(root: &Path) -> EvidenceRecorder<PinnedClock> {
    EvidenceRecorder::new(root, "session", json!({}), PinnedClock)
}

fn python(relative: &str) -> PathBuf {
    Path::new(FIXTURE).join("root").join(relative)
}

fn parsed(path: &Path) -> Value {
    serde_json::from_slice(&fs::read(path).unwrap()).unwrap()
}

fn audio_record(name: &str) -> (Value, Value) {
    let dir = tempfile::tempdir().unwrap();
    let id = format!("clip-{name}");
    let input = Path::new(FIXTURE).join("audio").join(format!("{name}.wav"));
    recorder(dir.path()).audio_generated(&id, &input).unwrap();
    let ours = parsed(&dir.path().join(&id).join("audio.json"));
    (ours, parsed(&python(&format!("{id}/audio.json"))))
}

#[test]
fn submitted_writes_the_python_request_record() {
    let dir = tempfile::tempdir().unwrap();
    let payload = json!({
        "op": "speak",
        "text": "Hello, ünïcode world.",
        "voice": "af_heart",
        "speed": 1.1,
        "tags": ["agent", "ünï"],
    });
    recorder(dir.path())
        .submitted(
            "clip-s",
            "Hello, ünïcode world.",
            payload.as_object().unwrap(),
        )
        .unwrap();
    assert_eq!(
        parsed(&dir.path().join("clip-s/request.json")),
        parsed(&python("clip-s/request.json"))
    );
}

#[test]
fn submitted_writes_the_python_source_text() {
    let dir = tempfile::tempdir().unwrap();
    let payload = json!({"text": "Hello, ünïcode world."});
    recorder(dir.path())
        .submitted(
            "clip-s",
            "Hello, ünïcode world.",
            payload.as_object().unwrap(),
        )
        .unwrap();
    assert_eq!(
        fs::read(dir.path().join("clip-s/source.txt")).unwrap(),
        fs::read(python("clip-s/source.txt")).unwrap()
    );
}

#[test]
fn a_pcm16_clip_gets_the_python_audio_record() {
    let (ours, python) = audio_record("pcm16");
    assert_eq!(ours, python);
}

#[test]
fn a_pcm24_clip_gets_the_python_audio_record() {
    let (ours, python) = audio_record("pcm24");
    assert_eq!(ours, python);
}

#[test]
fn a_float_clip_with_nan_and_infinity_gets_the_python_audio_record() {
    let (ours, python) = audio_record("float");
    assert_eq!(ours, python);
}

#[test]
fn an_unsupported_audio_format_is_refused_without_a_record() {
    let dir = tempfile::tempdir().unwrap();
    // RIFF fmt (format 1, 1 channel, 8000 Hz, 8 bits): 8-bit PCM, which the daemon never writes.
    let mut wav = b"RIFF\x28\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x40\x1f\x00\x00\x40\x1f\x00\x00\x01\x00\x08\x00data\x04\x00\x00\x00".to_vec();
    wav.extend_from_slice(&[128, 129, 127, 128]);
    let input = dir.path().join("u8.wav");
    fs::write(&input, wav).unwrap();
    assert!(
        recorder(&dir.path().join("root"))
            .audio_generated("c", &input)
            .is_err()
    );
    assert!(!dir.path().join("root/c/audio.json").exists());
}

#[test]
fn a_file_that_is_not_a_wav_is_refused_without_a_record() {
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("x.wav");
    fs::write(&input, b"not audio").unwrap();
    assert!(
        recorder(&dir.path().join("root"))
            .audio_generated("c", &input)
            .is_err()
    );
    assert!(!dir.path().join("root/c/audio.json").exists());
}

#[test]
fn an_extensible_three_channel_clip_gets_the_python_audio_record() {
    let (ours, python) = audio_record("extensible");
    assert_eq!(ours, python);
}

#[test]
fn a_riff_file_that_is_not_wave_is_refused_without_a_record() {
    let dir = tempfile::tempdir().unwrap();
    let mut riff = fs::read(Path::new(FIXTURE).join("audio/pcm16.wav")).unwrap();
    riff[8..12].copy_from_slice(b"AVI "); // RIFF form type
    let input = dir.path().join("x.wav");
    fs::write(&input, riff).unwrap();
    assert!(
        recorder(&dir.path().join("root"))
            .audio_generated("c", &input)
            .is_err()
    );
    assert!(!dir.path().join("root/c/audio.json").exists());
}
