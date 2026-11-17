// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//! This module owns the set of named engines the daemon can select.

use std::collections::BTreeMap;

use crate::engine::Engine;

/// Named engines; one name maps to one engine.
#[derive(Default)]
pub struct Registry {
    engines: BTreeMap<String, Box<dyn Engine>>,
}

impl Registry {
    /// Add `engine` under its own name. Returns the engine back when the name is taken.
    ///
    /// # Errors
    /// The name is already registered.
    pub fn register(&mut self, engine: Box<dyn Engine>) -> Result<(), Box<dyn Engine>> {
        let name = engine.name().to_owned();
        if self.engines.contains_key(&name) {
            return Err(engine);
        }
        self.engines.insert(name, engine);
        Ok(())
    }

    /// The engine called `name`, if registered.
    pub fn engine_mut(&mut self, name: &str) -> Option<&mut (dyn Engine + 'static)> {
        self.engines.get_mut(name).map(AsMut::as_mut)
    }

    /// Registered names in sorted order.
    pub fn names(&self) -> impl Iterator<Item = &str> {
        self.engines.keys().map(String::as_str)
    }
}

#[cfg(test)]
mod tests {
    //! Size: small. Oracle: one name maps to one engine.
    use super::Registry;
    use crate::engine::{Engine, EngineError, SpeechRequest};

    struct Named(&'static str);
    impl Engine for Named {
        fn name(&self) -> &str {
            self.0
        }
        fn stream(
            &mut self,
            _: &SpeechRequest<'_>,
            _: &mut dyn FnMut(&[u8]),
        ) -> Result<(), EngineError> {
            Ok(())
        }
    }

    #[test]
    fn a_second_engine_with_a_taken_name_is_refused() {
        let mut registry = Registry::default();
        assert!(registry.register(Box::new(Named("kokoro"))).is_ok());
        assert!(registry.register(Box::new(Named("chatterbox"))).is_ok());
        assert!(registry.register(Box::new(Named("kokoro"))).is_err());
        assert_eq!(
            registry.names().collect::<Vec<_>>(),
            ["chatterbox", "kokoro"]
        );
        assert!(registry.engine_mut("kokoro").is_some());
        assert!(registry.engine_mut("missing").is_none());
    }
}
