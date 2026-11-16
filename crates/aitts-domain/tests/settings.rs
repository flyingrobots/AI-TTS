// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Size: small. Oracle: settings.py inclusive speed limits, offered rates, and canonical integers.

use aitts_domain::settings::{
    Bytes, InvalidSetting, PlaybackRate, ResumePolicy, Speed, Value, boolean, catalog_name,
    languages,
};

#[test]
fn numeric_kinds_limits_and_nonfinite_values_are_checked() {
    for value in [
        Value::Number(0.5),
        Value::Number(2.0),
        Value::Integer(1),
        Value::Integer(2),
    ] {
        assert!(Speed::parse(value).is_ok(), "{value:?}");
    }
    for value in [
        Value::Number(0.499),
        Value::Number(2.001),
        Value::Number(f64::NAN),
        Value::Number(f64::INFINITY),
        Value::Boolean(true),
        Value::Text("1"),
        Value::Integer(i128::MAX),
    ] {
        assert_eq!(Speed::parse(value), Err(InvalidSetting::Speed), "{value:?}");
    }
    for rate in [0.5, 0.75, 1.0, 1.5, 2.0, 3.0] {
        assert_eq!(
            PlaybackRate::parse(Value::Number(rate)).map(PlaybackRate::multiplier),
            Ok(rate)
        );
    }
    for value in [
        Value::Integer(0),
        Value::Number(1.25),
        Value::Boolean(true),
        Value::Text("1"),
        Value::Number(f64::NAN),
        Value::Number(f64::INFINITY),
    ] {
        assert_eq!(
            PlaybackRate::parse(value),
            Err(InvalidSetting::PlaybackRate)
        );
    }
}

#[test]
fn cache_bytes_preserve_canonical_whole_numbers_and_refuse_overflow() {
    for (input, expected) in [
        (Value::Integer(0), 0),
        (Value::Integer(12), 12),
        (Value::Text(" 42\n"), 42),
        (Value::Text("18446744073709551615"), u64::MAX),
    ] {
        assert_eq!(Bytes::parse(input), Ok(Bytes(expected)));
    }
    for input in [
        Value::Integer(-1),
        Value::Integer(i128::MAX),
        Value::Text("18446744073709551616"),
        Value::Text("01"),
        Value::Text("+1"),
        Value::Text("-0"),
        Value::Text("1.0"),
        Value::Text("1e6"),
        Value::Text("١"),
        Value::Text(""),
        Value::Boolean(false),
        Value::Number(1.0),
    ] {
        assert_eq!(
            Bytes::parse(input),
            Err(InvalidSetting::CacheLimit),
            "{input:?}"
        );
    }
}

#[test]
fn toggles_resume_names_and_languages_use_their_own_value_kinds() {
    for value in [false, true] {
        assert_eq!(boolean(Value::Boolean(value)), Ok(value));
    }
    for value in [Value::Integer(1), Value::Number(0.0), Value::Text("true")] {
        assert_eq!(boolean(value), Err(InvalidSetting::Boolean));
    }
    assert_eq!(
        ResumePolicy::parse(Value::Text("manual")),
        Ok(ResumePolicy::Manual)
    );
    assert_eq!(
        ResumePolicy::parse(Value::Text("when_idle")),
        Ok(ResumePolicy::WhenIdle)
    );
    assert_eq!(
        ResumePolicy::parse(Value::Text("automatic")),
        Err(InvalidSetting::ResumePolicy)
    );
    assert_eq!(catalog_name(Value::Text("af_a"), &["af_a"]), Ok("af_a"));
    assert_eq!(
        catalog_name(Value::Text("missing"), &["af_a"]),
        Err(InvalidSetting::UnknownName)
    );
    assert_eq!(
        languages(&["zh", "en", "en"], &["zf_a", "af_b"]),
        Ok(vec!["en", "zh"])
    );
    for selection in [&[][..], &["unknown"][..], &["es"][..]] {
        assert_eq!(
            languages(selection, &["af_a"]),
            Err(InvalidSetting::Languages)
        );
    }
    assert_eq!(languages(&["en"], &["alice"]), Ok(vec!["en"]));
}
