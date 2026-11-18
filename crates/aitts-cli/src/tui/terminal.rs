// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the real terminal: raw mode, the alternate screen, key
//! names, and starting the dashboard on a daemon socket.

use super::run::{Input, Session, SocketCommands, run, watch};
use super::{Screen, draw};
use ratatui::backend::CrosstermBackend;
use ratatui::crossterm::cursor::{Hide, Show};
use ratatui::crossterm::event::{self, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers};
use ratatui::crossterm::execute;
use ratatui::crossterm::terminal::{
    EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode,
};
use ratatui::{Terminal, TerminalOptions, Viewport};
use std::io::{self, Write};
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::channel;
use std::time::{Duration, Instant};

/// Turns raw mode on (`true`) or off; [`raw_mode`] on a real terminal.
pub type RawMode = fn(bool) -> io::Result<()>;

/// After a failed connection the dashboard tries again after this long, as Python.
const RETRY: Duration = Duration::from_secs(1);

/// Raw mode of the process's terminal.
///
/// # Errors
/// The terminal refused.
pub fn raw_mode(on: bool) -> io::Result<()> {
    if on {
        enable_raw_mode()
    } else {
        disable_raw_mode()
    }
}

/// A [`Session`] that writes to `W` through crossterm.
pub struct TerminalSession<W: Write> {
    terminal: Terminal<CrosstermBackend<W>>,
    raw: RawMode,
}

impl<W: Write> TerminalSession<W> {
    /// A session on `out`, with `raw` for raw mode and `viewport` for its area.
    ///
    /// # Errors
    /// The terminal size could not be read.
    pub fn new(out: W, raw: RawMode, viewport: Viewport) -> io::Result<Self> {
        let terminal =
            Terminal::with_options(CrosstermBackend::new(out), TerminalOptions { viewport })?;
        Ok(Self { terminal, raw })
    }
}

impl<W: Write> Session for TerminalSession<W> {
    fn enter(&mut self) -> io::Result<()> {
        (self.raw)(true)?;
        execute!(self.terminal.backend_mut(), EnterAlternateScreen, Hide)
    }

    fn draw(&mut self, screen: &Screen) -> io::Result<()> {
        self.terminal.draw(|frame| draw(frame, screen)).map(|_| ())
    }

    fn leave(&mut self) -> io::Result<()> {
        // Leave the screen even when raw mode cannot be switched off, and the reverse.
        let screen = execute!(self.terminal.backend_mut(), LeaveAlternateScreen, Show);
        let raw = (self.raw)(false);
        screen.and(raw)
    }
}

/// The dashboard model's name for a key, or `None` for a key it ignores.
/// Ctrl+C is `q`.
pub fn key_name(event: KeyEvent) -> Option<String> {
    let control = event.modifiers.contains(KeyModifiers::CONTROL);
    match event.code {
        KeyCode::Char('c') if control => Some("q".to_owned()),
        _ if control => None,
        KeyCode::Char(' ') => Some("space".to_owned()),
        KeyCode::Char(character) => Some(character.to_string()),
        KeyCode::Enter => Some("enter".to_owned()),
        KeyCode::Tab => Some("tab".to_owned()),
        _ => None,
    }
}

/// Run the dashboard on the process's terminal against `socket`.
///
/// # Errors
/// The terminal failed.
pub fn start(socket: &Path) -> io::Result<()> {
    let mut session = TerminalSession::new(io::stdout(), raw_mode, Viewport::Fullscreen)?;
    let (inputs, received) = channel();
    let stop = AtomicBool::new(false);
    let started = Instant::now();
    let keys = inputs.clone();
    // The key reader blocks in `read`; it ends with the process.
    std::thread::spawn(move || {
        while let Ok(event) = event::read() {
            if let Event::Key(key) = event
                && key.kind == KeyEventKind::Press
                && let Some(name) = key_name(key)
                && keys.send(Input::Key(name)).is_err()
            {
                return;
            }
        }
    });
    std::thread::scope(|scope| {
        scope.spawn(|| watch(socket, &inputs, &stop, &|| std::thread::sleep(RETRY)));
        let mut commands = SocketCommands { socket };
        let outcome = run(&mut session, &received, &mut commands, &|| {
            started.elapsed().as_secs_f64()
        });
        stop.store(true, Ordering::SeqCst);
        outcome
    })
}
