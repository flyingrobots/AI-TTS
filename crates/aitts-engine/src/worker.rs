// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! This module owns one Python model worker process and its two pipes.
//!
//! Protocol version 2: the worker's first control line names its version.
//! Control replies are JSON lines on its standard output. Audio is
//! length-prefixed frames (4-byte big-endian length, then PCM) on descriptor 3;
//! an empty frame ends a stream. The worker leads its own process group, so a
//! stop reaches its children too. The leader stays unreaped until the group
//! signal is sent, so its group identifier cannot be reused first (issue #105).

use std::ffi::OsString;
use std::io::{BufRead, BufReader, Read, Write};
use std::os::fd::OwnedFd;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{Receiver, RecvTimeoutError, sync_channel};
use std::thread;
use std::time::Duration;

use command_fds::{CommandFdExt, FdMapping};
use nix::errno::Errno;
use nix::sys::signal::{Signal, killpg};
use nix::unistd::Pid;

use crate::catalog::WORKER_PROTOCOL_VERSION;
use crate::engine::{Engine, EngineError, SpeechRequest};

/// One audio frame carries at most this many bytes.
pub const FRAME_LIMIT: usize = 512 * 1024;
const LINE_LIMIT: u64 = 512 * 1024;
const AUDIO_FD: i32 = 3;

/// The program, arguments and environment that start one worker. The audio
/// descriptor number is appended as the last argument.
#[derive(Debug, Clone)]
pub struct WorkerLaunch {
    program: PathBuf,
    args: Vec<OsString>,
    env: Vec<(OsString, OsString)>,
}

impl WorkerLaunch {
    /// Any program that speaks the worker protocol.
    pub fn new(program: impl Into<PathBuf>, args: Vec<OsString>) -> Self {
        Self {
            program: program.into(),
            args,
            env: Vec::new(),
        }
    }

    /// The installed runtime of `model` under `root`, offline, as the Python daemon starts it.
    pub fn python_runtime(model: &str, root: &Path) -> Self {
        let args = ["-m", "aitts.model_worker", "serve", model].map(OsString::from);
        let mut launch = Self::new(root.join("venv/bin/python"), args.into());
        launch.args.push(root.as_os_str().to_owned());
        launch
            .env
            .push(("PYTHONPATH".into(), root.join("adapter").into_os_string()));
        for (key, value) in [
            ("HF_HUB_OFFLINE", "1"),
            ("TRANSFORMERS_OFFLINE", "1"),
            ("HF_HUB_DISABLE_TELEMETRY", "1"),
            ("TOKENIZERS_PARALLELISM", "false"),
        ] {
            launch.env.push((key.into(), value.into()));
        }
        launch
    }

    pub fn program(&self) -> &Path {
        &self.program
    }

    pub fn args(&self) -> &[OsString] {
        &self.args
    }
}

/// What the supervisor knows about its worker.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkerState {
    /// No process; the next request starts one.
    Stopped,
    /// A process passed the handshake.
    Ready,
    /// The worker failed and was stopped; only [`WorkerSupervisor::restart`] starts it again.
    Failed,
}

enum Audio {
    Frame(Vec<u8>),
    Oversized,
}

struct RunningWorker {
    child: Child,
    stdin: ChildStdin,
    control: Receiver<Vec<u8>>,
    audio: Receiver<Audio>,
}

/// Runs one model worker and streams audio from it.
pub struct WorkerSupervisor {
    name: String,
    launch: WorkerLaunch,
    response_timeout: Duration,
    worker: Option<RunningWorker>,
    state: WorkerState,
}

impl WorkerSupervisor {
    /// A supervisor that starts `launch` on first use and stops a worker that is
    /// silent for longer than `response_timeout`.
    pub fn new(name: impl Into<String>, launch: WorkerLaunch, response_timeout: Duration) -> Self {
        Self {
            name: name.into(),
            launch,
            response_timeout,
            worker: None,
            state: WorkerState::Stopped,
        }
    }

    pub fn state(&self) -> WorkerState {
        self.state
    }

    /// The worker's process (and process group) identifier, while it runs.
    pub fn process_id(&self) -> Option<u32> {
        self.worker.as_ref().map(|w| w.child.id())
    }

    /// Stop any worker, start a new one, and load its model.
    ///
    /// # Errors
    /// The new worker failed to start, handshake or warm up; it is stopped.
    pub fn restart(&mut self) -> Result<(), EngineError> {
        self.stop();
        self.start()?;
        let warmup = self
            .send(&serde_json::json!({"op": "warmup"}))
            .and_then(|()| self.reply());
        warmup.map_err(|error| self.fail(error))
    }

    /// Stop the worker and every process in its group.
    pub fn stop(&mut self) {
        if let Some(worker) = self.worker.take() {
            stop_group(worker);
        }
        self.state = WorkerState::Stopped;
    }

    fn fail(&mut self, error: EngineError) -> EngineError {
        self.stop();
        self.state = WorkerState::Failed;
        error
    }

    fn start(&mut self) -> Result<(), EngineError> {
        let (audio_read, audio_write) = std::io::pipe()?;
        let mut command = Command::new(&self.launch.program);
        command
            .args(&self.launch.args)
            .arg(AUDIO_FD.to_string())
            .envs(self.launch.env.iter().map(|(k, v)| (k, v)))
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .process_group(0);
        let mapping = FdMapping {
            parent_fd: OwnedFd::from(audio_write),
            child_fd: AUDIO_FD,
        };
        command
            .fd_mappings(vec![mapping])
            .map_err(|_| EngineError::Refused("audio descriptor collides"))?;
        let spawned = command.spawn();
        // The command holds our write end; only the worker may keep it, so its exit is an EOF.
        drop(command);
        let mut child = spawned.map_err(|error| self.fail(error.into()))?;
        let (Some(stdin), Some(stdout)) = (child.stdin.take(), child.stdout.take()) else {
            stop_child(child);
            return Err(self.fail(EngineError::WorkerExited));
        };
        self.worker = Some(RunningWorker {
            child,
            stdin,
            control: spawn_control_reader(stdout),
            audio: spawn_audio_reader(audio_read),
        });
        let handshake = self.handshake();
        handshake.map_err(|error| self.fail(error))?;
        self.state = WorkerState::Ready;
        Ok(())
    }

    fn handshake(&mut self) -> Result<(), EngineError> {
        let line = self.receive_line()?;
        let message: serde_json::Value =
            serde_json::from_slice(&line).map_err(|_| EngineError::Protocol)?;
        match message.get("protocol").and_then(serde_json::Value::as_u64) {
            Some(WORKER_PROTOCOL_VERSION) => Ok(()),
            _ => Err(EngineError::Protocol),
        }
    }

    fn running(&mut self) -> Result<&mut RunningWorker, EngineError> {
        self.worker.as_mut().ok_or(EngineError::WorkerExited)
    }

    fn send(&mut self, request: &serde_json::Value) -> Result<(), EngineError> {
        let mut line = request.to_string().into_bytes();
        line.push(b'\n');
        let stdin = &mut self.running()?.stdin;
        stdin
            .write_all(&line)
            .and_then(|()| stdin.flush())
            .map_err(|_| EngineError::WorkerExited)
    }

    fn receive_line(&mut self) -> Result<Vec<u8>, EngineError> {
        let timeout = self.response_timeout;
        receive(&self.running()?.control, timeout)
    }

    fn reply(&mut self) -> Result<(), EngineError> {
        let line = self.receive_line()?;
        let reply: serde_json::Value = serde_json::from_slice(&line)
            .map_err(|_| EngineError::InvalidResponse("control line is not JSON"))?;
        match reply.get("ok") {
            Some(serde_json::Value::Bool(true)) => Ok(()),
            _ => Err(EngineError::ModelFailed),
        }
    }

    fn stream_frames(
        &mut self,
        request: &SpeechRequest<'_>,
        sink: &mut dyn FnMut(&[u8]),
    ) -> Result<(), EngineError> {
        let op = serde_json::json!({
            "op": "stream", "text": request.text, "voice": request.voice, "speed": request.speed,
        });
        self.send(&op)?;
        let timeout = self.response_timeout;
        loop {
            match receive(&self.running()?.audio, timeout)? {
                Audio::Oversized => {
                    return Err(EngineError::InvalidResponse("audio frame over limit"));
                }
                Audio::Frame(pcm) if pcm.is_empty() => break,
                Audio::Frame(pcm) if pcm.len() % 2 != 0 => {
                    return Err(EngineError::InvalidResponse("PCM frame splits a sample"));
                }
                Audio::Frame(pcm) => sink(&pcm),
            }
        }
        self.reply()
    }
}

impl Engine for WorkerSupervisor {
    fn name(&self) -> &str {
        &self.name
    }

    /// Restart a failed worker; a ready or stopped worker is left as it is.
    fn recover(&mut self) -> Result<(), EngineError> {
        match self.state {
            WorkerState::Failed => self.restart(),
            WorkerState::Ready | WorkerState::Stopped => Ok(()),
        }
    }

    fn stream(
        &mut self,
        request: &SpeechRequest<'_>,
        sink: &mut dyn FnMut(&[u8]),
    ) -> Result<(), EngineError> {
        match self.state {
            WorkerState::Failed => return Err(EngineError::WorkerExited),
            WorkerState::Stopped => self.start()?,
            WorkerState::Ready => {}
        }
        // Any failure retires the worker, so the next clip cannot read stale audio.
        self.stream_frames(request, sink)
            .map_err(|error| self.fail(error))
    }
}

impl Drop for WorkerSupervisor {
    fn drop(&mut self) {
        self.stop();
    }
}

fn receive<T>(channel: &Receiver<T>, timeout: Duration) -> Result<T, EngineError> {
    channel.recv_timeout(timeout).map_err(|error| match error {
        RecvTimeoutError::Timeout => EngineError::Timeout,
        RecvTimeoutError::Disconnected => EngineError::WorkerExited,
    })
}

fn spawn_control_reader(stdout: impl Read + Send + 'static) -> Receiver<Vec<u8>> {
    let (sender, receiver) = sync_channel(4);
    thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        loop {
            let mut line = Vec::new();
            // A line without its newline is EOF or over the limit; both end the channel.
            match (&mut reader).take(LINE_LIMIT).read_until(b'\n', &mut line) {
                Ok(_) if line.pop() == Some(b'\n') => {
                    if sender.send(line).is_err() {
                        return;
                    }
                }
                _ => return,
            }
        }
    });
    receiver
}

fn spawn_audio_reader(mut audio: impl Read + Send + 'static) -> Receiver<Audio> {
    let (sender, receiver) = sync_channel(8);
    thread::spawn(move || {
        loop {
            let mut prefix = [0_u8; 4];
            if audio.read_exact(&mut prefix).is_err() {
                return;
            }
            let length = usize::try_from(u32::from_be_bytes(prefix)).unwrap_or(usize::MAX);
            if length > FRAME_LIMIT {
                drop(sender.send(Audio::Oversized));
                return;
            }
            let mut pcm = vec![0_u8; length];
            if audio.read_exact(&mut pcm).is_err() || sender.send(Audio::Frame(pcm)).is_err() {
                return;
            }
        }
    });
    receiver
}

fn stop_group(worker: RunningWorker) {
    let RunningWorker {
        child,
        stdin,
        control,
        audio,
    } = worker;
    drop((stdin, control, audio));
    stop_child(child);
}

fn stop_child(mut child: Child) {
    // The leader is unreaped here, so its group identifier still names our group.
    let signalled = i32::try_from(child.id())
        .map_err(|_| Errno::EINVAL)
        .and_then(|pid| killpg(Pid::from_raw(pid), Signal::SIGKILL));
    // ESRCH: the group is gone. EPERM on Darwin: only zombies remain (issue #105).
    if !matches!(signalled, Ok(()) | Err(Errno::ESRCH | Errno::EPERM)) {
        drop(child.kill());
    }
    drop(child.wait());
}
