//! Deal with several changes in events, batching them together.
//!
//! Preferably, changes should be kept to a minimum.
//! Sometimes, it’s needed to change the list of events, because parsing can be
//! messy, and it helps to expose a cleaner interface of events to the compiler
//! and other users.
//! It can also help to merge many adjacent similar events.
//! And, in other cases, it’s needed to parse subcontent: pass some events
//! through another tokenizer and inject the result.

use crate::event::Event;
use crate::{limits::Budget, message::Message};
use alloc::{vec, vec::Vec};

/// Shift `previous` and `next` links according to `jumps`.
///
/// This fixes links in case there are events removed or added between them.
fn shift_links(
    events: &mut [Event],
    jumps: &[(usize, usize, usize)],
    budget: Option<&Budget>,
) -> Result<(), Message> {
    let mut jump_index = 0;
    let mut index = 0;
    let mut add = 0;
    let mut rm = 0;

    while index < events.len() {
        if let Some(budget) = budget {
            budget.tick()?;
        }
        let rm_curr = rm;

        while jump_index < jumps.len() && jumps[jump_index].0 <= index {
            if let Some(budget) = budget {
                budget.tick()?;
            }
            add = jumps[jump_index].2;
            rm = jumps[jump_index].1;
            jump_index += 1;
        }

        // Ignore items that will be removed.
        if rm > rm_curr {
            index += rm - rm_curr;
        } else {
            if let Some(link) = &events[index].link {
                if let Some(next) = link.next {
                    events[next].link.as_mut().unwrap().previous = Some(index + add - rm);

                    while jump_index < jumps.len() && jumps[jump_index].0 <= next {
                        if let Some(budget) = budget {
                            budget.tick()?;
                        }
                        add = jumps[jump_index].2;
                        rm = jumps[jump_index].1;
                        jump_index += 1;
                    }

                    events[index].link.as_mut().unwrap().next = Some(next + add - rm);
                    index = next;
                    continue;
                }
            }

            index += 1;
        }
    }
    Ok(())
}

/// Tracks a bunch of edits.
#[derive(Debug)]
pub struct EditMap<'a> {
    pub(crate) budget: Option<&'a Budget>,
    /// Record of changes.
    map: Vec<(usize, usize, Vec<Event>)>,
}

impl<'a> EditMap<'a> {
    /// Create a new edit map.
    pub fn new(budget: Option<&'a Budget>) -> EditMap<'a> {
        EditMap {
            budget,
            map: vec![],
        }
    }
    /// Create an edit: a remove and/or add at a certain place.
    pub fn add(&mut self, index: usize, remove: usize, add: Vec<Event>) -> Result<(), Message> {
        add_impl(self, index, remove, add, false)
    }
    /// Create an edit: but insert `add` before existing additions.
    pub fn add_before(
        &mut self,
        index: usize,
        remove: usize,
        add: Vec<Event>,
    ) -> Result<(), Message> {
        add_impl(self, index, remove, add, true)
    }
    pub fn add_new<const N: usize>(
        &mut self,
        index: usize,
        remove: usize,
        create: impl FnOnce() -> [Event; N],
    ) -> Result<(), Message> {
        if let Some(budget) = self.budget {
            budget.events(N)?;
        }
        self.add(index, remove, Vec::from(create()))
    }
    pub fn add_new_before<const N: usize>(
        &mut self,
        index: usize,
        remove: usize,
        create: impl FnOnce() -> [Event; N],
    ) -> Result<(), Message> {
        if let Some(budget) = self.budget {
            budget.events(N)?;
        }
        self.add_before(index, remove, Vec::from(create()))
    }

    /// Done, change the events.
    pub fn consume(&mut self, events: &mut Vec<Event>) -> Result<(), Message> {
        if let Some(budget) = self.budget {
            budget.spend(
                self.map
                    .len()
                    .saturating_mul(self.map.len().saturating_add(1).ilog2() as usize + 1),
            )?;
        }
        self.map
            .sort_unstable_by(|a, b| a.0.partial_cmp(&b.0).unwrap());

        if self.map.is_empty() {
            return Ok(());
        }

        // Calculate jumps: where items in the current list move to.
        let mut jumps = Vec::with_capacity(self.map.len());
        let mut index = 0;
        let mut add_acc = 0;
        let mut remove_acc = 0;
        while index < self.map.len() {
            if let Some(budget) = self.budget {
                budget.tick()?;
            }
            let (at, remove, add) = &self.map[index];
            remove_acc += remove;
            add_acc += add.len();
            jumps.push((*at, remove_acc, add_acc));
            index += 1;
        }

        shift_links(events, &jumps, self.budget)?;

        let len_before = events.len();
        let mut index = self.map.len();
        let mut vecs = Vec::with_capacity(index * 2 + 1);
        while index > 0 {
            if let Some(budget) = self.budget {
                budget.tick()?;
            }
            index -= 1;
            if let Some(budget) = self.budget {
                budget.spend(
                    events
                        .len()
                        .saturating_sub(self.map[index].0 + self.map[index].1),
                )?;
                budget.spend(self.map[index].2.len())?;
            }
            vecs.push(events.split_off(self.map[index].0 + self.map[index].1));
            vecs.push(self.map[index].2.split_off(0));
            events.truncate(self.map[index].0);
        }
        if let Some(budget) = self.budget {
            budget.spend(events.len())?;
        }
        vecs.push(events.split_off(0));

        events.reserve(len_before + add_acc - remove_acc);

        while let Some(mut slice) = vecs.pop() {
            if let Some(budget) = self.budget {
                budget.tick()?;
            }
            if let Some(budget) = self.budget {
                budget.spend(slice.len())?;
            }
            events.append(&mut slice);
        }

        self.map.truncate(0);
        Ok(())
    }
}

/// Create an edit.
fn add_impl(
    edit_map: &mut EditMap,
    at: usize,
    remove: usize,
    mut add: Vec<Event>,
    before: bool,
) -> Result<(), Message> {
    let mut index = 0;

    if remove == 0 && add.is_empty() {
        return Ok(());
    }

    while index < edit_map.map.len() {
        if let Some(budget) = edit_map.budget {
            budget.tick()?;
        }
        if edit_map.map[index].0 == at {
            edit_map.map[index].1 += remove;

            if before {
                if let Some(budget) = edit_map.budget {
                    budget.spend(edit_map.map[index].2.len())?;
                }
                add.append(&mut edit_map.map[index].2);
                edit_map.map[index].2 = add;
            } else {
                if let Some(budget) = edit_map.budget {
                    budget.spend(add.len())?;
                }
                edit_map.map[index].2.append(&mut add);
            }

            return Ok(());
        }

        index += 1;
    }

    if let Some(budget) = edit_map.budget {
        budget.events(1)?;
    }
    edit_map.map.push((at, remove, add));
    Ok(())
}
