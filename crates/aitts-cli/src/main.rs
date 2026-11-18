// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The `ai-tts` binary.

use aitts_cli::{Environment, run};
use std::process::ExitCode;

fn main() -> ExitCode {
    let env = Environment {
        socket: std::env::var_os("AI_TTS_SOCKET"),
        home: std::env::var_os("AI_TTS_HOME"),
        user_home: std::env::home_dir(),
    };
    let status = run(
        std::env::args_os().skip(1),
        &env,
        &mut std::io::stdout().lock(),
        &mut std::io::stderr().lock(),
    );
    ExitCode::from(status)
}
