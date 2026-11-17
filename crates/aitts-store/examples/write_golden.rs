// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! Write `tests/fixtures/rust-written.db`, which the Python suite opens.
//!
//! Run: `cargo run -p aitts-store --example write_golden`.

#[path = "../tests/support/golden_ops.rs"]
mod golden_ops;

use std::cell::Cell;
use std::path::Path;

use aitts_store::{Clock, Store};

struct SteppingClock(Cell<f64>);

impl Clock for SteppingClock {
    fn now(&self) -> f64 {
        self.0.set(self.0.get() + 1.0);
        self.0.get()
    }
}

fn main() -> aitts_store::Result<()> {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/rust-written.db");
    if path.exists() {
        std::fs::remove_file(&path)
            .map_err(|_| aitts_store::Error::Invalid("cannot replace fixture"))?;
    }
    let store = Store::open(&path, SteppingClock(Cell::new(1_000.0)))?;
    golden_ops::write(&store)?;
    store.close()
}
