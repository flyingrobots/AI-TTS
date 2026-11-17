// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small (in-process; the socket path does not exist, so nothing connects).
//! Oracle: the exit-status contract. Any argument list ends in 0, 1 or 2 and
//! never panics.

#![allow(clippy::unwrap_used, reason = "test code fails loudly")]

mod support;

use proptest::prelude::*;

const WORDS: &[&str] = &[
    "say",
    "get",
    "wait",
    "list",
    "history",
    "settings",
    "set",
    "assign-voice",
    "model-setup",
    "clear",
    "cancel",
    "rewind",
    "status",
    "input",
    "playback",
    "kokoro",
    "--wait",
    "--timeout",
    "--speed",
    "--limit",
    "--set",
    "--release",
    "--earcon",
    "--format",
    "--to",
    "--before",
    "--preempt",
    "--priority",
    "--sensitivity",
    "--socket",
    "--help",
    "-h",
    "--version",
    "--",
    "-1",
    "nan",
    "inf",
    "1e999",
    "on",
    "off",
    "true",
    "=",
    "speed=x",
    "voice_languages=",
    "",
];

fn token() -> impl Strategy<Value = String> {
    prop_oneof![
        3 => proptest::sample::select(WORDS).prop_map(str::to_owned),
        1 => any::<String>(),
    ]
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(512))]
    #[test]
    fn random_argument_lists_exit_with_a_contract_status(argv in proptest::collection::vec(token(), 0..6)) {
        let dir = tempfile::tempdir().unwrap();
        let refs: Vec<&str> = argv.iter().map(String::as_str).collect();
        let outcome = support::run(&dir.path().join("absent.sock"), &refs);
        prop_assert!(outcome.status <= 2, "exit {} for {argv:?}", outcome.status);
    }
}
