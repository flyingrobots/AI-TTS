//! Data occurs in the [string][] and [text][] content types.
//!
//! It can include anything (except for line endings) and stops at certain
//! characters.
//!
//! [string]: crate::construct::string
//! [text]: crate::construct::text

use crate::event::{Kind, Name};
use crate::state::{Name as StateName, State};
use crate::subtokenize::Subresult;
use crate::tokenizer::Tokenizer;

/// At beginning of data.
///
/// ```markdown
/// > | abc
///     ^
/// ```
pub fn start(tokenizer: &mut Tokenizer) -> State {
    // Make sure to eat the first `markers`.
    if let Some(byte) = tokenizer.current {
        if tokenizer.tokenize_state.markers.contains(&byte) {
            state_try!(tokenizer.enter(Name::Data));
            tokenizer.consume();
            return State::Next(StateName::DataInside);
        }
    }

    State::Retry(StateName::DataAtBreak)
}

/// Before something.
///
/// ```markdown
/// > | abc
///     ^
/// ```
pub fn at_break(tokenizer: &mut Tokenizer) -> State {
    if let Some(byte) = tokenizer.current {
        if !tokenizer.tokenize_state.markers.contains(&byte) {
            if byte == b'\n' {
                state_try!(tokenizer.enter(Name::LineEnding));
                tokenizer.consume();
                state_try!(tokenizer.exit(Name::LineEnding));
                return State::Next(StateName::DataAtBreak);
            }
            state_try!(tokenizer.enter(Name::Data));
            return State::Retry(StateName::DataInside);
        }
    }

    State::Ok
}

/// In data.
///
/// ```markdown
/// > | abc
///     ^^^
/// ```
pub fn inside(tokenizer: &mut Tokenizer) -> State {
    if let Some(byte) = tokenizer.current {
        if byte != b'\n' && !tokenizer.tokenize_state.markers.contains(&byte) {
            tokenizer.consume();
            return State::Next(StateName::DataInside);
        }
    }

    state_try!(tokenizer.exit(Name::Data));
    State::Retry(StateName::DataAtBreak)
}

/// Merge adjacent data events.
pub fn resolve(tokenizer: &mut Tokenizer) -> Result<Option<Subresult>, crate::message::Message> {
    let mut index = 0;

    // Loop through events and merge adjacent data events.
    while index < tokenizer.events.len() {
        if let Some(budget) = tokenizer.parse_state.budget {
            budget.tick()?;
        }
        let event = &tokenizer.events[index];

        if event.kind == Kind::Enter && event.name == Name::Data {
            // Move to exit.
            index += 1;

            let mut exit_index = index;

            // Find the farthest `data` event exit event.
            while exit_index + 1 < tokenizer.events.len()
                && tokenizer.events[exit_index + 1].name == Name::Data
            {
                if let Some(budget) = tokenizer.parse_state.budget {
                    budget.tick()?;
                }
                exit_index += 2;
            }

            if exit_index > index {
                tokenizer.map.add_new(index, exit_index - index, || [])?;
                // Change positional info.
                tokenizer.events[index].point = tokenizer.events[exit_index].point.clone();
                // Move to the end.
                index = exit_index;
            }
        }

        index += 1;
    }

    tokenizer.map.consume(&mut tokenizer.events)?;
    Ok(None)
}
