// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small (in-process; the socket path does not exist, so nothing connects).
//! Oracle: the exit-status contract. Any argument list ends in 0, 1 or 2 and
//! never panics.

#![allow(clippy::unwrap_used, reason = "test code fails loudly")]

mod support;

use proptest::prelude::*;

const COMMANDS: &[&str] = &[
    "say",
    "get",
    "wait",
    "list",
    "history",
    "settings",
    "assign-voice",
    "model-setup",
    "clear",
    "cancel",
    "rewind",
    "status",
    "--socket",
    "--help",
    "--version",
    "bogus",
];
const OPTIONS: &[&str] = &[
    "--speed",
    "--timeout",
    "--limit",
    "--set",
    "--earcon",
    "--format",
    "--to",
    "--before",
    "--priority",
    "--release",
    "--preempt",
    "--wait",
    "-h",
    "--",
];
const VALUES: &[&str] = &[
    "-1",
    "nan",
    "inf",
    "1e999",
    "speed=nan",
    "on",
    "true",
    "input",
    "set",
    "x",
    "",
];

/// An option followed by a value, a bare value, or any string.
fn element() -> impl Strategy<Value = Vec<String>> {
    let pick =
        |words: &'static [&'static str]| proptest::sample::select(words).prop_map(str::to_owned);
    prop_oneof![
        4 => (pick(OPTIONS), pick(VALUES)).prop_map(|(option, value)| vec![option, value]),
        2 => pick(VALUES).prop_map(|value| vec![value]),
        1 => any::<String>().prop_map(|value| vec![value]),
    ]
}

fn argv() -> impl Strategy<Value = Vec<String>> {
    // `say hi` and `settings` carry the number and setting conversions, so they are weighted up.
    let command = prop_oneof![
        2 => Just(vec!["say".to_owned(), "hi".to_owned()]),
        2 => Just(vec!["settings".to_owned()]),
        3 => proptest::sample::select(COMMANDS).prop_map(|command| vec![command.to_owned()]),
    ];
    (command, proptest::collection::vec(element(), 0..5)).prop_map(|(command, rest)| {
        command
            .into_iter()
            .chain(rest.into_iter().flatten())
            .collect()
    })
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(2048))]
    #[test]
    fn random_argument_lists_exit_with_a_contract_status(argv in argv()) {
        let dir = tempfile::tempdir().unwrap();
        let refs: Vec<&str> = argv.iter().map(String::as_str).collect();
        let outcome = support::run(&dir.path().join("absent.sock"), &refs);
        prop_assert!(outcome.status <= 2, "exit {} for {argv:?}", outcome.status);
    }
}
