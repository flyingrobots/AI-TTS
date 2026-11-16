// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

//! Print one complete JSON Schema for use by other protocol implementations.
#![forbid(unsafe_code)]

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let schema = aitts_protocol::wire_schema();
    serde_json::to_writer_pretty(std::io::stdout().lock(), &schema)?;
    Ok(())
}
