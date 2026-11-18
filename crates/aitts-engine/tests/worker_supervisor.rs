// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: medium (real subprocesses, owned temporary files). Oracle: the worker
//! protocol version 2 of `src/aitts/model_worker.py` (issue #126) and the
//! supervisor contract of issue #133. The fake worker in `fixtures/` speaks that
//! protocol with a scripted behavior; its known stream is each text byte twice.

#![allow(clippy::unwrap_used, reason = "test code fails loudly")]
#![allow(clippy::expect_used, reason = "test code fails loudly")]

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::time::{Duration, Instant};

use aitts_engine::catalog::WORKER_MODELS;
use aitts_engine::engine::{Engine, EngineError, SpeechRequest};
use aitts_engine::worker::{WorkerLaunch, WorkerState, WorkerSupervisor};
use nix::sys::signal::kill;
use nix::unistd::Pid;

const TEXT: &str = "hello world";

/// A runtime root whose `venv/bin/python` runs the fake worker.
fn runtime(mode: &str) -> tempfile::TempDir {
    let root = tempfile::tempdir().unwrap();
    let bin = root.path().join("venv/bin");
    fs::create_dir_all(&bin).unwrap();
    let fake = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/fake_worker.py");
    let python = bin.join("python");
    fs::write(
        &python,
        format!("#!/bin/sh\nexec python3 '{}' \"$@\"\n", fake.display()),
    )
    .unwrap();
    fs::set_permissions(&python, fs::Permissions::from_mode(0o755)).unwrap();
    set_mode(root.path(), mode);
    root
}

fn set_mode(root: &Path, mode: &str) {
    fs::write(root.join("mode"), mode).unwrap();
}

fn supervisor(model: &str, root: &Path, timeout: Duration) -> WorkerSupervisor {
    WorkerSupervisor::new(model, WorkerLaunch::python_runtime(model, root), timeout)
}

fn speak(worker: &mut WorkerSupervisor) -> (Result<(), EngineError>, Vec<u8>) {
    let mut clip = Vec::new();
    let request = SpeechRequest {
        text: TEXT,
        voice: "default",
        speed: 1.0,
    };
    let result = worker.stream(&request, &mut |pcm| clip.extend_from_slice(pcm));
    (result, clip)
}

fn known_stream() -> Vec<u8> {
    TEXT.repeat(2).into_bytes()
}

/// True when `pid` is gone; waits briefly because an orphan is reaped by init.
fn gone(pid: i32) -> bool {
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if kill(Pid::from_raw(pid), None).is_err() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    false
}

#[test]
fn each_python_worker_starts_and_streams_its_known_audio() {
    for model in WORKER_MODELS {
        let root = runtime("golden");
        let mut worker = supervisor(model, root.path(), Duration::from_secs(10));
        let (result, clip) = speak(&mut worker);
        assert!(result.is_ok(), "{model}: {result:?}");
        assert_eq!(clip, known_stream(), "{model}");
        assert_eq!(worker.state(), WorkerState::Ready);
        // One process served both requests.
        let pid = worker.process_id();
        assert!(speak(&mut worker).0.is_ok());
        assert_eq!(worker.process_id(), pid);
        let started = fs::read_to_string(root.path().join("started")).unwrap();
        assert_eq!(started, format!("{model}\n"));
    }
}

#[test]
fn a_worker_that_exits_at_start_is_failed_until_restarted() {
    let root = runtime("exit_at_start");
    let mut worker = supervisor("kokoro", root.path(), Duration::from_secs(10));
    assert!(matches!(
        speak(&mut worker).0,
        Err(EngineError::WorkerExited)
    ));
    assert_eq!(worker.state(), WorkerState::Failed);
    set_mode(root.path(), "golden");
    // Failed stays failed: a request does not silently respawn it.
    assert!(matches!(
        speak(&mut worker).0,
        Err(EngineError::WorkerExited)
    ));
    assert!(worker.restart().is_ok());
    let (result, clip) = speak(&mut worker);
    assert!(result.is_ok());
    assert_eq!(clip, known_stream());
}

#[test]
fn a_silent_worker_is_stopped_with_its_children() {
    let root = runtime("hang");
    let mut worker = supervisor("kokoro", root.path(), Duration::from_millis(500));
    assert!(worker.restart().is_ok());
    let pid = i32::try_from(worker.process_id().unwrap()).unwrap();
    assert!(matches!(speak(&mut worker).0, Err(EngineError::Timeout)));
    assert_eq!(worker.state(), WorkerState::Failed);
    assert_eq!(worker.process_id(), None);
    let child: i32 = fs::read_to_string(root.path().join("child.pid"))
        .unwrap()
        .parse()
        .unwrap();
    assert!(gone(pid), "worker {pid} still runs");
    assert!(gone(child), "worker child {child} still runs");
}

#[test]
fn audio_on_the_control_pipe_is_an_invalid_response() {
    let root = runtime("wrong_pipe");
    let mut worker = supervisor("kokoro", root.path(), Duration::from_secs(10));
    let (result, clip) = speak(&mut worker);
    assert!(
        matches!(result, Err(EngineError::InvalidResponse(_))),
        "{result:?}"
    );
    assert_eq!(clip, Vec::<u8>::new());
    assert_eq!(worker.state(), WorkerState::Failed);
}

#[test]
fn a_worker_of_another_protocol_version_is_refused() {
    let root = runtime("old_protocol");
    let mut worker = supervisor("kokoro", root.path(), Duration::from_secs(10));
    assert!(matches!(speak(&mut worker).0, Err(EngineError::Protocol)));
    assert_eq!(worker.state(), WorkerState::Failed);
}

#[test]
fn random_frame_boundaries_and_exits_leave_no_process_and_no_partial_clip() {
    for seed in 0..24_u32 {
        let exits = seed % 2 == 1;
        let root = runtime(&format!(
            "random {seed} {}",
            if exits { "exit" } else { "complete" }
        ));
        let mut worker = supervisor("kokoro", root.path(), Duration::from_secs(10));
        assert!(worker.restart().is_ok(), "seed {seed}");
        let pid = i32::try_from(worker.process_id().unwrap()).unwrap();
        let (result, clip) = speak(&mut worker);
        if exits {
            assert!(
                matches!(result, Err(EngineError::WorkerExited)),
                "seed {seed}: {result:?}"
            );
            // The failed worker is retired and reaped, so the next clip cannot read its audio.
            assert_eq!(worker.state(), WorkerState::Failed, "seed {seed}");
            assert_eq!(worker.process_id(), None, "seed {seed}");
            assert!(gone(pid), "seed {seed}: worker {pid} still runs");
        } else {
            // Success always carries the whole clip.
            assert!(result.is_ok(), "seed {seed}: {result:?}");
            assert_eq!(clip, known_stream(), "seed {seed}");
            worker.stop();
            assert!(gone(pid), "seed {seed}: stopped worker {pid} still runs");
        }
    }
}

#[test]
fn recover_restarts_a_failed_worker_for_the_next_request() {
    let root = runtime("exit_at_start");
    let mut worker = supervisor("kokoro", root.path(), Duration::from_secs(10));
    assert!(matches!(
        speak(&mut worker).0,
        Err(EngineError::WorkerExited)
    ));
    set_mode(root.path(), "golden");
    assert!(
        worker.recover().is_ok(),
        "recover refused a startable worker"
    );
    assert_eq!(speak(&mut worker).1, known_stream());
}
