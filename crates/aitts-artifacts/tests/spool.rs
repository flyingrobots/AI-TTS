// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Size: medium (owned temporary files, one thread). Contract: the `Spool` API
//! and the WAV file it leaves. Oracles: `aitts.streaming.SpoolingPCMStream`
//! (read, seek, end and completion rules) and Python's `wave` module, which wrote
//! `fixtures/python-cached.wav` (10 frames, sample i = i * 257; see the evidence
//! record for the generator).

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test code fails loudly"
)]

use std::fs;
use std::os::unix::fs::{PermissionsExt, symlink};
use std::path::{Path, PathBuf};

use aitts_artifacts::spool::Spool;

const FIXTURE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/tests/fixtures/python-cached.wav"
);

fn fixture_pcm() -> Vec<u8> {
    (0..10i16).flat_map(|i| (i * 257).to_le_bytes()).collect()
}

fn spool_path(dir: &tempfile::TempDir) -> PathBuf {
    dir.path().join(".utt.wav.part")
}

fn mode(path: &Path) -> u32 {
    fs::metadata(path).unwrap().permissions().mode() & 0o777
}

#[test]
fn a_sealed_spool_is_byte_identical_to_the_python_wav() {
    let dir = tempfile::tempdir().unwrap();
    let path = spool_path(&dir);
    let mut spool = Spool::create(&path, 4).unwrap();
    let pcm = fixture_pcm();
    spool.append(&pcm[..6]).unwrap();
    spool.append(&pcm[6..]).unwrap();
    let duration_ms = spool.seal().unwrap();
    assert_eq!(fs::read(&path).unwrap(), fs::read(FIXTURE).unwrap());
    assert_eq!(duration_ms, 0, "10 frames at 24 kHz is 0 ms, rounded down");
}

#[test]
fn a_new_spool_file_is_owner_only() {
    let dir = tempfile::tempdir().unwrap();
    let path = spool_path(&dir);
    Spool::create(&path, 4).unwrap();
    assert_eq!(mode(&path), 0o600);
}

#[test]
fn a_symbolic_link_in_place_of_the_spool_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let target = dir.path().join("victim");
    fs::write(&target, b"kept").unwrap();
    symlink(&target, spool_path(&dir)).unwrap();
    assert!(Spool::create(&spool_path(&dir), 4).is_err());
    assert_eq!(fs::read(&target).unwrap(), b"kept");
}

#[test]
fn a_read_during_production_returns_the_live_bytes() {
    let dir = tempfile::tempdir().unwrap();
    let mut spool = Spool::create(&spool_path(&dir), 8).unwrap();
    spool.append(&[1, 0, 2, 0, 3, 0]).unwrap();
    let read = spool.read(2);
    assert_eq!(read.pcm, [1, 0, 2, 0]);
    assert_eq!(read.position_frames, 2);
}

#[test]
fn an_underflow_returns_no_samples_and_no_end() {
    let dir = tempfile::tempdir().unwrap();
    let mut spool = Spool::create(&spool_path(&dir), 8).unwrap();
    spool.append(&[1, 0]).unwrap();
    spool.read(1);
    let read = spool.read(4);
    assert_eq!(read.pcm, Vec::<u8>::new());
    assert!(!read.ended && !read.complete, "{read:?}");
}

#[test]
fn a_sealed_drained_spool_is_complete_but_not_ended_until_finish() {
    let dir = tempfile::tempdir().unwrap();
    let mut spool = Spool::create(&spool_path(&dir), 8).unwrap();
    spool.append(&[1, 0]).unwrap();
    spool.seal().unwrap();
    let read = spool.read(4);
    assert!(read.complete && !read.ended, "{read:?}");
    spool.finish(None);
    assert!(spool.read(4).ended);
}

#[test]
fn a_finish_error_reaches_the_reader() {
    let dir = tempfile::tempdir().unwrap();
    let mut spool = Spool::create(&spool_path(&dir), 8).unwrap();
    spool.finish(Some("engine failed".to_owned()));
    assert_eq!(spool.read(1).error.as_deref(), Some("engine failed"));
}

#[test]
fn overflow_beyond_the_ring_is_read_from_the_file_after_fill() {
    let dir = tempfile::tempdir().unwrap();
    let mut spool = Spool::create(&spool_path(&dir), 2).unwrap();
    spool.append(&[1, 0, 2, 0, 3, 0, 4, 0]).unwrap();
    assert_eq!(spool.read(4).pcm, [1, 0, 2, 0]);
    assert_eq!(spool.fill(), 2);
    assert_eq!(spool.read(4).pcm, [3, 0, 4, 0]);
}

#[test]
fn a_backward_seek_rereads_the_spooled_bytes() {
    let dir = tempfile::tempdir().unwrap();
    let mut spool = Spool::create(&spool_path(&dir), 8).unwrap();
    spool.append(&[1, 0, 2, 0, 3, 0]).unwrap();
    spool.read(3);
    spool.seek(1);
    assert_eq!(
        spool.read(3).pcm,
        Vec::<u8>::new(),
        "a seek clears the ring"
    );
    spool.fill();
    let read = spool.read(3);
    assert_eq!(read.pcm, [2, 0, 3, 0]);
    assert_eq!(read.position_frames, 3);
}

#[test]
fn append_refuses_a_half_sample() {
    let dir = tempfile::tempdir().unwrap();
    let mut spool = Spool::create(&spool_path(&dir), 8).unwrap();
    assert!(spool.append(&[1, 0, 2]).is_err());
}

#[test]
fn append_refuses_after_seal() {
    let dir = tempfile::tempdir().unwrap();
    let mut spool = Spool::create(&spool_path(&dir), 8).unwrap();
    spool.seal().unwrap();
    assert!(spool.append(&[1, 0]).is_err());
}

#[test]
fn a_python_written_wav_streams_its_frames_and_is_unchanged() {
    let before = fs::read(FIXTURE).unwrap();
    let mut spool = Spool::open_cached(Path::new(FIXTURE), 4).unwrap();
    let mut pcm = Vec::new();
    let mut ended = false;
    for _ in 0..8 {
        spool.fill();
        let read = spool.read(3);
        pcm.extend(read.pcm);
        ended = read.ended;
    }
    assert_eq!(pcm, fixture_pcm());
    assert!(ended, "a cached WAV ends after its last frame");
    assert_eq!(fs::read(FIXTURE).unwrap(), before);
}

#[test]
fn a_cached_wav_at_another_rate_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let mut bytes = fs::read(FIXTURE).unwrap();
    bytes[24..28].copy_from_slice(&16_000u32.to_le_bytes()); // RIFF fmt: sample rate
    let path = dir.path().join("other.wav");
    fs::write(&path, bytes).unwrap();
    assert!(Spool::open_cached(&path, 4).is_err());
}

#[test]
fn a_truncated_cached_wav_reports_an_error_not_a_complete_read() {
    let dir = tempfile::tempdir().unwrap();
    let bytes = fs::read(FIXTURE).unwrap();
    let path = dir.path().join("short.wav");
    fs::write(&path, &bytes[..bytes.len() - 4]).unwrap();
    let mut spool = Spool::open_cached(&path, 16).unwrap();
    spool.fill();
    let read = spool.read(16);
    assert!(read.error.is_some(), "{read:?}");
}
