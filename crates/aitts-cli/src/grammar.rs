// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module owns the argument grammar. It mirrors `aitts.cli._build_parser`:
//! the same subcommands, options, choices and positional arity. Long options
//! accept unique prefixes and may repeat (the last wins), as in argparse.

use clap::{Arg, ArgAction, Command, value_parser};

const QUEUES: [&str; 2] = ["input", "playback"];
const ON_OFF: [&str; 2] = ["on", "off"];

fn command(name: &'static str, about: &'static str) -> Command {
    Command::new(name)
        .about(about)
        .infer_long_args(true)
        .args_override_self(true)
}

fn value(name: &'static str) -> Arg {
    Arg::new(name).long(name)
}

fn float(name: &'static str) -> Arg {
    value(name)
        .allow_negative_numbers(true)
        .value_parser(value_parser!(f64))
}

fn flag(name: &'static str) -> Arg {
    value(name).action(ArgAction::SetTrue)
}

fn positional(name: &'static str) -> Arg {
    Arg::new(name).required(true)
}

fn say() -> Command {
    command(
        "say",
        "queue text to be spoken, even while playback is paused",
    )
    .arg(positional("text"))
    .arg(
        value("format")
            .value_parser(["plain_text", "markdown"])
            .default_value("plain_text"),
    )
    .arg(value("voice"))
    .arg(value("engine"))
    .arg(float("speed"))
    .arg(value("sensitivity").value_parser(["public", "internal", "confidential"]))
    .arg(value("priority").value_parser(["normal", "urgent", "preempt"]))
    .arg(flag("preempt"))
    .arg(value("source"))
    .arg(flag("wait"))
    .arg(float("timeout"))
}

fn settings() -> Command {
    command("settings", "read or change settings")
        .arg(Arg::new("action").value_parser(["set"]))
        .arg(Arg::new("key"))
        .arg(Arg::new("value"))
        .arg(value("engine"))
        .arg(value("earcon").value_parser(ON_OFF))
        .arg(value("ducking").value_parser(ON_OFF))
        .arg(value("set").action(ArgAction::Append))
}

const PLAIN: [(&str, &str); 15] = [
    ("cancel-model-setup", "cancel the active local model setup"),
    (
        "purge-cache",
        "remove cached audio not needed by current or queued speech",
    ),
    ("pause", "send 'pause' to the daemon"),
    ("resume", "send 'resume' to the daemon"),
    ("skip", "send 'skip' to the daemon"),
    ("status", "send 'status' to the daemon"),
    ("voices", "send 'voices' to the daemon"),
    ("metrics", "send 'metrics' to the daemon"),
    ("engines", "send 'engines' to the daemon"),
    (
        "next-chunk",
        "give up the current chunk of a document and play the next one",
    ),
    (
        "prev-chunk",
        "replay the previous chunk of the current document",
    ),
    (
        "resume-when-idle",
        "release the playback hold once nothing is using the microphone",
    ),
    ("voice-map", "show which voice each speaking client holds"),
    (
        "get",
        "read one utterance by id without waiting for playback",
    ),
    ("cancel", "cancel an utterance that is not playing"),
];

/// The complete `ai-tts` command grammar.
pub(crate) fn grammar() -> Command {
    let plain = PLAIN.iter().map(|(name, about)| {
        let sub = command(name, about);
        if matches!(*name, "get" | "cancel") {
            sub.arg(positional("id"))
        } else {
            sub
        }
    });
    command(
        "ai-tts",
        "Send text to the AI-TTS daemon and control playback.",
    )
    .version(env!("CARGO_PKG_VERSION"))
    .subcommand_required(true)
    .arg(value("socket").value_parser(value_parser!(std::path::PathBuf)))
    .subcommands(plain)
    .subcommand(
        command(
            "model-setup",
            "download and prepare a supported local speech model",
        )
        .arg(positional("name").value_parser(["kokoro", "kokoro-mlx", "chatterbox"])),
    )
    .subcommand(say())
    .subcommand(
        command("wait", "block until an utterance finishes")
            .arg(positional("id"))
            .arg(float("timeout")),
    )
    .subcommand(command("list", "show a queue").arg(positional("queue").value_parser(QUEUES)))
    .subcommand(
        command("history", "show what has been said")
            .arg(
                value("limit")
                    .allow_negative_numbers(true)
                    .value_parser(value_parser!(i64))
                    .default_value("20"),
            )
            .arg(value("before")),
    )
    .subcommand(command("rewind", "restart the current utterance, or replay one").arg(value("to")))
    .subcommand(
        command("clear", "drain a named queue").arg(positional("queue").value_parser(QUEUES)),
    )
    .subcommand(
        command("assign-voice", "assign a voice to one client")
            .arg(positional("source"))
            .arg(Arg::new("voice"))
            .arg(flag("release")),
    )
    .subcommand(settings())
}
