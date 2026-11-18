// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small (in-process; an in-memory terminal buffer).
//! Oracles: the dashboard model (`tui_parity.rs`, tied to the Python
//! `SpeechTUI`) for what each region holds, and the Python layout for the
//! regions and labels: a header, the now-playing card (details, progress,
//! spoken text of at most 5 lines, meter; at most 12 rows), the queue and
//! history titles and column names, the status line and the footer with the
//! shown bindings. The Textual layout is not reproduced cell for cell; the
//! cells checked here are the content each region must hold.

#![allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    clippy::panic,
    clippy::string_slice,
    reason = "test code fails loudly"
)]

mod support;

use aitts_cli::tui::{Screen, draw};
use ratatui::Terminal;
use ratatui::backend::TestBackend;
use ratatui::buffer::Buffer;
use ratatui::style::Modifier;
use support::tui::{fixture, play, scenario};

fn render(screen: &Screen, width: u16, height: u16) -> Buffer {
    let mut terminal = Terminal::new(TestBackend::new(width, height)).unwrap();
    terminal.draw(|frame| draw(frame, screen)).unwrap();
    terminal.backend().buffer().clone()
}

fn lines(buffer: &Buffer) -> Vec<String> {
    let area = buffer.area;
    (0..area.height)
        .map(|y| {
            (0..area.width)
                .map(|x| buffer[(x, y)].symbol().to_owned())
                .collect()
        })
        .collect()
}

/// The first row at or after `from` that contains `text`.
fn row_of(lines: &[String], text: &str, from: usize) -> usize {
    match lines.iter().skip(from).position(|line| line.contains(text)) {
        Some(index) => index + from,
        None => panic!("{text:?} not shown after row {from}:\n{}", lines.join("\n")),
    }
}

fn screen(name: &str) -> Screen {
    play(&scenario(name)).0.screen()
}

#[test]
fn each_region_holds_its_content_in_python_order() {
    let screen = screen("held queue");
    let shown = lines(&render(&screen, 100, 35));
    let header = row_of(&shown, "AI-TTS", 0);
    let details = row_of(&shown, &screen.details, header);
    let meter = row_of(&shown, &screen.meter, details);
    let queue = row_of(&shown, "Queue · j/k select · dd cancel · J/K move", meter);
    let columns = row_of(&shown, "Priority", queue);
    for label in ["Voice", "State", "Text"] {
        assert!(shown[columns].contains(label), "{label} column");
    }
    let mut after = columns;
    for row in &screen.queue {
        let text: String = row[3].chars().take(20).collect();
        after = row_of(&shown, &text, after + 1);
        assert!(
            shown[after].contains(&row[0]) && shown[after].contains(&row[2]),
            "{row:?}"
        );
    }
    let history = row_of(
        &shown,
        "History · Tab switches tables · Enter replays",
        after,
    );
    let result = row_of(&shown, "Result", history);
    let replayed = row_of(&shown, &screen.history[0][2], result);
    let status = row_of(&shown, &screen.status, replayed);
    let footer = row_of(&shown, "Quit", status);
    for hint in [
        "Pause/resume",
        "Next chunk",
        "Previous chunk",
        "Restart",
        "Skip",
        "Replay history",
    ] {
        assert!(
            shown[footer].contains(hint),
            "footer lacks {hint}: {}",
            shown[footer]
        );
    }
}

#[test]
fn the_playing_card_shows_chunk_text_progress_and_meter() {
    let screen = screen("progress event");
    let shown = lines(&render(&screen, 100, 35));
    let details = row_of(&shown, &screen.details, 0);
    let spoken = row_of(&shown, &screen.spoken, details);
    row_of(&shown, &screen.meter, spoken);
    // 62000 of 2000 ms is past the end: the bar is full, as Textual clamps it.
    row_of(&shown, "100%", details);
}

#[test]
fn an_unknown_duration_shows_no_percentage() {
    let mut screen = screen("playing chunk");
    screen.progress.total = None;
    let shown = lines(&render(&screen, 100, 35)).join("\n");
    assert!(!shown.contains('%'), "{shown}");
}

#[test]
fn the_selected_row_of_the_focused_table_is_highlighted() {
    for (name, focused_text) in [("j and k select", 1), ("tab then dd does nothing", 0)] {
        let screen = screen(name);
        let buffer = render(&screen, 100, 35);
        let shown = lines(&buffer);
        let (table, cursor) = if screen.focused == "queue" {
            (&screen.queue, screen.queue_cursor)
        } else {
            (&screen.history, screen.history_cursor)
        };
        assert_eq!(cursor, focused_text, "{name}");
        let text: String = table[cursor][table[cursor].len() - 1]
            .chars()
            .take(20)
            .collect();
        let title = if screen.focused == "queue" {
            "Queue ·"
        } else {
            "History ·"
        };
        let row = row_of(&shown, &text, row_of(&shown, title, 0));
        let x = u16::try_from(
            shown[row]
                .find(&text)
                .map_or(0, |b| shown[row][..b].chars().count()),
        )
        .unwrap();
        let style = buffer[(x, u16::try_from(row).unwrap())].modifier;
        assert!(
            style.contains(Modifier::REVERSED),
            "{name}: row {row} not highlighted"
        );
    }
}

#[test]
fn long_clip_text_stays_inside_its_card_and_leaves_the_tables_visible() {
    let mut screen = screen("playing chunk");
    screen.spoken = "word ".repeat(2000);
    let shown = lines(&render(&screen, 100, 35));
    let details = row_of(&shown, &screen.details, 0);
    let queue = row_of(&shown, "Queue ·", details);
    assert!(
        queue - details <= 11,
        "the card takes {} rows",
        queue - details
    );
    let words = shown
        .iter()
        .filter(|line| line.contains("word word"))
        .count();
    assert!(words <= 5, "spoken text takes {words} rows");
    let history = row_of(&shown, "History ·", queue);
    assert!(
        history - queue >= 3,
        "the queue has {} rows",
        history - queue
    );
}

#[test]
fn forty_columns_keep_every_region_and_cut_lines_at_the_edge() {
    let screen = screen("held queue");
    let shown = lines(&render(&screen, 40, 24));
    let prefix: String = screen.details.chars().take(30).collect();
    row_of(&shown, &prefix, 0);
    for title in ["Queue ·", "History ·"] {
        row_of(&shown, title, 0);
    }
    assert!(shown.iter().all(|line| line.chars().count() == 40));
}

#[test]
fn no_scenario_puts_a_control_character_into_the_buffer_at_any_size() {
    for recorded in fixture()["scenarios"].as_array().unwrap() {
        let screen = play(recorded).0.screen();
        for (width, height) in [(100, 35), (80, 24), (40, 24), (20, 8), (1, 1), (0, 0)] {
            let buffer = render(&screen, width, height);
            let control = lines(&buffer).concat().chars().find(|c| c.is_control());
            assert_eq!(control, None, "{} at {width}x{height}", recorded["name"]);
        }
    }
}
