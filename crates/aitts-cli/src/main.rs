// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! The `ai-tts` binary. `daemon` and `tui` are Python programs: they are handed,
//! with the same arguments, to the `ai-tts-py` installed beside this binary.

use aitts_cli::{EXIT_DAEMON_ERROR, Environment, hands_off, run};
use std::ffi::OsString;
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::{Command, ExitCode};

/// `ai-tts-py` next to this binary, else on `PATH`.
fn python_cli() -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|dir| dir.join("ai-tts-py")))
        .filter(|path| path.is_file())
        .unwrap_or_else(|| PathBuf::from("ai-tts-py"))
}

fn main() -> ExitCode {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    if hands_off(&args) {
        let program = python_cli();
        // `exec` returns only when it fails.
        let error = Command::new(&program).args(&args).exec();
        let mut err = std::io::stderr().lock();
        let _ = std::io::Write::write_fmt(
            &mut err,
            format_args!(
                "ai-tts: cannot run {}: {error}. Reinstall with: make install\n",
                program.display()
            ),
        );
        return ExitCode::from(EXIT_DAEMON_ERROR);
    }
    let env = Environment {
        socket: std::env::var_os("AI_TTS_SOCKET"),
        home: std::env::var_os("AI_TTS_HOME"),
        user_home: std::env::home_dir(),
    };
    let status = run(
        args,
        &env,
        &mut std::io::stdout().lock(),
        &mut std::io::stderr().lock(),
    );
    ExitCode::from(status)
}
