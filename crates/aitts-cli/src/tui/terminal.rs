// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the real terminal: raw mode, the alternate screen, key
//! names, and starting the dashboard on a daemon socket.
#![allow(clippy::todo, reason = "RED stub")]

use super::Screen;
use super::run::Session;
use ratatui::Viewport;
use ratatui::crossterm::event::KeyEvent;
use std::io::{self, Write};
use std::path::Path;

/// Turns raw mode on (`true`) or off; [`raw_mode`] on a real terminal.
pub type RawMode = fn(bool) -> io::Result<()>;

/// Raw mode of the process's terminal.
///
/// # Errors
/// The terminal refused.
pub fn raw_mode(on: bool) -> io::Result<()> {
    let _ = on;
    todo!()
}

/// A [`Session`] that writes to `W` through crossterm.
pub struct TerminalSession<W: Write> {
    _out: Option<W>,
}

impl<W: Write> TerminalSession<W> {
    /// A session on `out`, with `raw` for raw mode and `viewport` for its area.
    ///
    /// # Errors
    /// The terminal size could not be read.
    pub fn new(out: W, raw: RawMode, viewport: Viewport) -> io::Result<Self> {
        let _ = (raw, viewport);
        Ok(Self { _out: Some(out) })
    }

    /// The writer, for tests that read what was written.
    pub fn writer(&self) -> &W {
        todo!()
    }
}

impl<W: Write> Session for TerminalSession<W> {
    fn enter(&mut self) -> io::Result<()> {
        todo!()
    }
    fn draw(&mut self, _screen: &Screen) -> io::Result<()> {
        todo!()
    }
    fn leave(&mut self) -> io::Result<()> {
        todo!()
    }
}

/// The dashboard model's name for a key, or `None` for a key it ignores.
/// Ctrl+C is `q`.
pub fn key_name(_event: KeyEvent) -> Option<String> {
    todo!()
}

/// Run the dashboard on the process's terminal against `socket`.
///
/// # Errors
/// The terminal failed.
pub fn start(_socket: &Path) -> io::Result<()> {
    todo!()
}
