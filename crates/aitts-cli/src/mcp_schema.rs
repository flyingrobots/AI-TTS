// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! This module checks a JSON value against one recorded tool schema and fills
//! its defaults, as the Python server's Pydantic models do for the keywords
//! those schemas use: `$ref`, `anyOf`, `const`, `enum`, `type`, `properties`,
//! `required`, `default`, `additionalProperties`, `items`, `minimum`,
//! `maximum`, `minLength` and the one `pattern` (utterance ids).

use serde_json::{Map, Value};

/// The value does not fit the schema.
#[derive(Debug)]
pub(crate) struct Mismatch;

type Checked = Result<Value, Mismatch>;

const UTTERANCE_ID: &str = "^utt_[0-9a-f]{32}$";

fn utterance_id(text: &str) -> bool {
    text.strip_prefix("utt_").is_some_and(|hex| {
        hex.len() == 32
            && hex
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    })
}

fn within(number: f64, schema: &Value) -> bool {
    let low = schema.get("minimum").and_then(Value::as_f64);
    let high = schema.get("maximum").and_then(Value::as_f64);
    low.is_none_or(|low| number >= low) && high.is_none_or(|high| number <= high)
}

fn string(value: &Value, schema: &Value) -> Checked {
    let text = value.as_str().ok_or(Mismatch)?;
    let shortest = schema.get("minLength").and_then(Value::as_u64).unwrap_or(0);
    let long_enough = u64::try_from(text.chars().count()).is_ok_and(|n| n >= shortest);
    let pattern_ok = match schema.get("pattern").and_then(Value::as_str) {
        None => true,
        Some(UTTERANCE_ID) => utterance_id(text),
        // A pattern this port does not know cannot be checked, so it is refused.
        Some(_) => false,
    };
    (long_enough && pattern_ok)
        .then(|| value.clone())
        .ok_or(Mismatch)
}

fn integer(value: &Value, schema: &Value) -> Checked {
    let number = value
        .as_f64()
        .filter(|_| !value.is_boolean())
        .ok_or(Mismatch)?;
    if !within(number, schema) {
        return Err(Mismatch);
    }
    if value.is_i64() || value.is_u64() {
        return Ok(value.clone());
    }
    // Pydantic accepts a float with no fraction for an integer field.
    let whole = (number.fract() == 0.0)
        .then(|| format!("{number:.0}"))
        .ok_or(Mismatch)?;
    serde_json::from_str(&whole).map_err(|_| Mismatch)
}

fn number(value: &Value, schema: &Value) -> Checked {
    let number = value.as_f64().ok_or(Mismatch)?;
    // Pydantic dumps a float field as a float, so an integer becomes 2.0.
    let float = serde_json::Number::from_f64(number).ok_or(Mismatch)?;
    within(number, schema)
        .then_some(Value::Number(float))
        .ok_or(Mismatch)
}

fn object(value: &Value, schema: &Value, defs: &Value) -> Checked {
    let given = value.as_object().ok_or(Mismatch)?;
    let mut out = Map::new();
    if let Some(properties) = schema.get("properties").and_then(Value::as_object) {
        let required = schema.get("required").and_then(Value::as_array);
        for (name, property) in properties {
            if let Some(item) = given.get(name) {
                out.insert(name.clone(), conform(item, property, defs)?);
            } else if let Some(default) = property.get("default") {
                out.insert(name.clone(), default.clone());
            } else if required.is_some_and(|r| r.iter().any(|n| n == name)) {
                return Err(Mismatch);
            }
        }
        if given.keys().any(|name| !properties.contains_key(name))
            && schema.get("additionalProperties") == Some(&Value::Bool(false))
        {
            return Err(Mismatch);
        }
        return Ok(Value::Object(out));
    }
    match schema.get("additionalProperties") {
        Some(Value::Bool(false)) if !given.is_empty() => Err(Mismatch),
        Some(values @ Value::Object(_)) => {
            for (name, item) in given {
                out.insert(name.clone(), conform(item, values, defs)?);
            }
            Ok(Value::Object(out))
        }
        _ => Ok(value.clone()),
    }
}

/// `value` checked against `schema`, with defaults filled. `defs` holds the
/// tool schema's `$defs`.
pub(crate) fn conform(value: &Value, schema: &Value, defs: &Value) -> Checked {
    if let Some(reference) = schema.get("$ref").and_then(Value::as_str) {
        let name = reference.strip_prefix("#/$defs/").ok_or(Mismatch)?;
        return conform(value, defs.get(name).ok_or(Mismatch)?, defs);
    }
    if let Some(options) = schema.get("anyOf").and_then(Value::as_array) {
        return options
            .iter()
            .find_map(|option| conform(value, option, defs).ok())
            .ok_or(Mismatch);
    }
    if schema
        .get("const")
        .is_some_and(|constant| constant != value)
    {
        return Err(Mismatch);
    }
    if schema
        .get("enum")
        .and_then(Value::as_array)
        .is_some_and(|choices| !choices.contains(value))
    {
        return Err(Mismatch);
    }
    match schema.get("type").and_then(Value::as_str) {
        Some("null") => value.is_null().then_some(Value::Null).ok_or(Mismatch),
        Some("boolean") => value.is_boolean().then(|| value.clone()).ok_or(Mismatch),
        Some("integer") => integer(value, schema),
        Some("number") if !value.is_boolean() => number(value, schema),
        Some("string") => string(value, schema),
        Some("array") => {
            let items = schema.get("items").unwrap_or(&Value::Null);
            let checked: Result<Vec<Value>, Mismatch> = value
                .as_array()
                .ok_or(Mismatch)?
                .iter()
                .map(|item| {
                    if items.is_null() {
                        Ok(item.clone())
                    } else {
                        conform(item, items, defs)
                    }
                })
                .collect();
            checked.map(Value::Array)
        }
        Some("object") => object(value, schema, defs),
        Some(_) => Err(Mismatch),
        None => Ok(value.clone()),
    }
}
