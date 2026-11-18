// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module draws a [`Screen`] into a terminal frame, in the Python
//! dashboard's layout: header, now-playing card, queue, history, status line
//! and footer. Text is drawn as given; [`Screen`] has already made control
//! characters visible.

use super::Screen;
use ratatui::Frame;
use ratatui::layout::{Alignment, Constraint, Layout, Rect};
use ratatui::style::{Modifier, Style};
use ratatui::text::Line;
use ratatui::widgets::{
    Block, BorderType, Borders, Gauge, Paragraph, Row, Table, TableState, Wrap,
};

/// The card's spoken text shows at most this many lines, as `#spoken-text`.
const SPOKEN_LINES: u16 = 5;
/// The bindings the Python footer shows.
const FOOTER: &str = "space Pause/resume  n Next chunk  p Previous chunk  r Restart  s Skip  enter Replay history  q Quit";
const QUEUE_TITLE: &str = "Queue · j/k select · dd cancel · J/K move";
const HISTORY_TITLE: &str = "History · Tab switches tables · Enter replays";

/// Lines `text` takes when wrapped at `width`, at least one.
fn wrapped_lines(text: &str, width: u16) -> u16 {
    let width = usize::from(width.max(1));
    let lines: usize = text
        .split('\n')
        .map(|line| line.chars().count().div_ceil(width).max(1))
        .sum();
    u16::try_from(lines).unwrap_or(u16::MAX)
}

fn card(frame: &mut Frame<'_>, area: Rect, screen: &Screen) {
    let block = Block::default()
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded);
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let spoken = wrapped_lines(&screen.spoken, inner.width).min(SPOKEN_LINES);
    let [details, progress, text, meter] = Layout::vertical([
        Constraint::Length(1),
        Constraint::Length(1),
        Constraint::Length(spoken),
        Constraint::Length(1),
    ])
    .areas(inner);
    frame.render_widget(Paragraph::new(screen.details.as_str()), details);
    match screen.progress.total.filter(|total| *total > 0.0) {
        Some(total) => {
            let ratio = (screen.progress.progress / total).clamp(0.0, 1.0);
            frame.render_widget(Gauge::default().ratio(ratio), progress);
        }
        // An unknown total has no percentage, as Textual's indeterminate bar.
        None => frame.render_widget(
            Paragraph::new("─".repeat(usize::from(progress.width))),
            progress,
        ),
    }
    frame.render_widget(
        Paragraph::new(screen.spoken.as_str()).wrap(Wrap { trim: false }),
        text,
    );
    frame.render_widget(Paragraph::new(screen.meter.as_str()), meter);
}

fn table(
    frame: &mut Frame<'_>,
    area: Rect,
    columns: &[(&str, Constraint)],
    rows: &[Vec<String>],
    cursor: usize,
    focused: bool,
) {
    let header = Row::new(columns.iter().map(|(name, _)| *name))
        .style(Style::default().add_modifier(Modifier::BOLD));
    let body = rows
        .iter()
        .map(|cells| Row::new(cells.iter().map(String::as_str)));
    let highlight = if focused {
        Style::default().add_modifier(Modifier::REVERSED)
    } else {
        Style::default()
    };
    let widget = Table::new(body, columns.iter().map(|(_, width)| *width))
        .header(header)
        .row_highlight_style(highlight);
    let mut state = TableState::default().with_selected((!rows.is_empty()).then_some(cursor));
    frame.render_stateful_widget(widget, area, &mut state);
}

/// Draw `screen` over the whole frame.
pub fn draw(frame: &mut Frame<'_>, screen: &Screen) {
    let area = frame.area();
    let inner_width = area.width.saturating_sub(2);
    let card_height =
        (2 + 1 + 1 + wrapped_lines(&screen.spoken, inner_width).min(SPOKEN_LINES) + 1).min(12);
    let status_height = wrapped_lines(&screen.status, area.width).min(3);
    let [
        header,
        now,
        queue_title,
        queue,
        history_title,
        history,
        status,
        footer,
    ] = Layout::vertical([
        Constraint::Length(1),
        Constraint::Length(card_height),
        Constraint::Length(1),
        Constraint::Min(3),
        Constraint::Length(1),
        Constraint::Min(3),
        Constraint::Length(status_height),
        Constraint::Length(1),
    ])
    .areas(area);
    frame.render_widget(
        Paragraph::new("AI-TTS")
            .alignment(Alignment::Center)
            .style(Style::default().add_modifier(Modifier::BOLD)),
        header,
    );
    card(frame, now, screen);
    let bold = Style::default().add_modifier(Modifier::BOLD);
    frame.render_widget(Paragraph::new(Line::styled(QUEUE_TITLE, bold)), queue_title);
    table(
        frame,
        queue,
        &[
            ("Priority", Constraint::Length(9)),
            ("Voice", Constraint::Length(10)),
            ("State", Constraint::Length(13)),
            ("Text", Constraint::Fill(1)),
        ],
        &screen.queue,
        screen.queue_cursor,
        screen.focused == "queue",
    );
    frame.render_widget(
        Paragraph::new(Line::styled(HISTORY_TITLE, bold)),
        history_title,
    );
    table(
        frame,
        history,
        &[
            ("Voice", Constraint::Length(10)),
            ("Result", Constraint::Length(10)),
            ("Text", Constraint::Fill(1)),
        ],
        &screen.history,
        screen.history_cursor,
        screen.focused == "history",
    );
    frame.render_widget(
        Paragraph::new(screen.status.as_str()).wrap(Wrap { trim: false }),
        status,
    );
    frame.render_widget(Paragraph::new(FOOTER), footer);
}
