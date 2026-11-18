// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! `ai-ttsd`: serve the AI-TTS socket until SIGTERM, SIGINT, or SIGHUP.
//!
//! It reads `AI_TTS_HOME` (default `~/Library/Application Support/ai-tts`) and
//! `AI_TTS_SOCKET` (default `<home>/ai-tts.sock`), as the Python daemon does.
//!
//! It speaks with Kokoro: the runtime installed by model setup under
//! `<home>/model-runtimes`, or, when none is installed, an engine that fails
//! each clip with the model-setup instruction. Audio goes to a discarding sink:
//! this binary has no audio device yet.

#![forbid(unsafe_code)]

use std::fs::DirBuilder;
use std::os::unix::fs::DirBuilderExt;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::Duration;

use aitts_daemon::driver::{DiscardingSink, Synthesis};
use aitts_daemon::{Config, EngineView, StopOutcome};
use aitts_engine::engine::Engine;
use aitts_engine::installed::{self, NotInstalled, voices};
use aitts_engine::registry::Registry;
use aitts_engine::worker::{WorkerLaunch, WorkerSupervisor};
use aitts_protocol::vocabulary::ModelState;
use signal_hook::consts::{SIGHUP, SIGINT, SIGTERM};
use signal_hook::iterator::Signals;

/// How long a stop may take before the process exits anyway.
const STOP_LIMIT: Duration = Duration::from_secs(3);

fn home() -> Option<PathBuf> {
    if let Some(home) = std::env::var_os("AI_TTS_HOME").filter(|home| !home.is_empty()) {
        return Some(PathBuf::from(home));
    }
    std::env::var_os("HOME")
        .map(|home| PathBuf::from(home).join("Library/Application Support/ai-tts"))
}

fn config() -> Option<Config> {
    let home = home()?;
    let socket = std::env::var_os("AI_TTS_SOCKET")
        .filter(|socket| !socket.is_empty())
        .map_or_else(|| home.join("ai-tts.sock"), PathBuf::from);
    Some(Config {
        socket,
        database: home.join("ai-tts.db"),
        cache_dir: home.join("cache"),
        engine: EngineView {
            name: MODEL.to_owned(),
            voices: voices(MODEL)
                .iter()
                .map(|voice| (*voice).to_owned())
                .collect(),
            is_local: true,
            state: ModelState::Cold,
        },
    })
}

/// The model this binary speaks with.
const MODEL: &str = "kokoro";

/// How long the worker may take to answer before it is stopped.
const WORKER_TIMEOUT: Duration = Duration::from_secs(120);

/// Frames each spool's read ring holds: one second at 24 kHz.
const SPOOL_FRAMES: usize = 24_000;

fn synthesis(home: &Path, spool_dir: PathBuf) -> Synthesis {
    let engine: Box<dyn Engine> = match installed::runtime(home, MODEL) {
        Some(root) => Box::new(WorkerSupervisor::new(
            MODEL,
            WorkerLaunch::python_runtime(MODEL, &root),
            WORKER_TIMEOUT,
        )),
        None => Box::new(NotInstalled::new(MODEL)),
    };
    let mut engines = Registry::default();
    // The registry is empty, so the only name cannot be taken.
    let _registered = engines.register(engine);
    Synthesis {
        engines,
        spool_dir,
        capacity_frames: SPOOL_FRAMES,
        sink: Box::new(DiscardingSink),
        retry_after: Duration::from_millis(50),
        on_idle: None,
    }
}

fn main() -> ExitCode {
    let Some(config) = config() else {
        eprintln!("ai-ttsd: set AI_TTS_HOME or HOME");
        return ExitCode::FAILURE;
    };
    let Some(home) = home() else {
        eprintln!("ai-ttsd: set AI_TTS_HOME or HOME");
        return ExitCode::FAILURE;
    };
    let spool_dir = home.join("spool");
    let parents = [
        config.database.parent(),
        config.socket.parent(),
        Some(spool_dir.as_path()),
    ];
    for directory in parents.into_iter().flatten() {
        if let Err(error) = DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(directory)
        {
            eprintln!("ai-ttsd: cannot create {}: {error}", directory.display());
            return ExitCode::FAILURE;
        }
    }
    let mut signals = match Signals::new([SIGTERM, SIGINT, SIGHUP]) {
        Ok(signals) => signals,
        Err(error) => {
            eprintln!("ai-ttsd: cannot install signal handlers: {error}");
            return ExitCode::FAILURE;
        }
    };
    let daemon = match aitts_daemon::start_with(config, synthesis(&home, spool_dir)) {
        Ok(daemon) => daemon,
        Err(error) => {
            eprintln!("ai-ttsd: {error}");
            return ExitCode::FAILURE;
        }
    };
    let _signal = signals.forever().next();
    match daemon.stop(STOP_LIMIT) {
        StopOutcome::Clean => ExitCode::SUCCESS,
        StopOutcome::TimedOut => {
            eprintln!("ai-ttsd: stop passed its time limit; exiting");
            ExitCode::SUCCESS
        }
    }
}
