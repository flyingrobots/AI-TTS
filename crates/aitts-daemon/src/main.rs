// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! `ai-ttsd`: serve the AI-TTS socket until SIGTERM, SIGINT, or SIGHUP.
//!
//! It reads `AI_TTS_HOME` (default `~/Library/Application Support/ai-tts`) and
//! `AI_TTS_SOCKET` (default `<home>/ai-tts.sock`), as the Python daemon does.

#![forbid(unsafe_code)]

use std::path::PathBuf;
use std::process::ExitCode;
use std::time::Duration;

use aitts_daemon::{Config, EngineView, StopOutcome};
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
            name: "kokoro".to_owned(),
            voices: Vec::new(),
            is_local: true,
            state: ModelState::Cold,
        },
    })
}

fn main() -> ExitCode {
    let Some(config) = config() else {
        eprintln!("ai-ttsd: set AI_TTS_HOME or HOME");
        return ExitCode::FAILURE;
    };
    if let Some(parent) = config.socket.parent()
        && let Err(error) = std::fs::create_dir_all(parent)
    {
        eprintln!("ai-ttsd: cannot create {}: {error}", parent.display());
        return ExitCode::FAILURE;
    }
    let mut signals = match Signals::new([SIGTERM, SIGINT, SIGHUP]) {
        Ok(signals) => signals,
        Err(error) => {
            eprintln!("ai-ttsd: cannot install signal handlers: {error}");
            return ExitCode::FAILURE;
        }
    };
    let daemon = match aitts_daemon::start(config) {
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
