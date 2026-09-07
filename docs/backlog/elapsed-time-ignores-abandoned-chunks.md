# Elapsed time ignores abandoned chunks

**Consequence.** Skip forward through two chunks of a three-chunk document and
the progress bar reads 0:00 while the third chunk is audibly playing.

**Why.** `Store.completed_segment_duration_ms` sums `duration_ms` for children
in `Played` only. A chunk left `Skipped` contributes nothing, even though the
playhead has moved past it.
`PlaybackController.current_position_ms` builds the live document position from
that sum, so the bar reports "heard" where the user reads "position".

**Why it is still here.** The honest fix is to distinguish *heard* from
*behind the playhead*, which changes shared progress semantics and
`_finish_segment_playback` — not a side effect of adding a transport button.
Doing it carelessly would make a partly-skipped document report a duration it
never spoke, which is the same class of lie in the other direction.

It predates the next/previous-chunk controls, but those controls make it easy
to hit on purpose rather than only through a whole-entry Skip, so it is more
visible than it was.

**Pinned.** The current behaviour is asserted by
`tests/test_segment_navigation.py::test_stepping_back_over_an_abandoned_chunk_does_not_credit_it_as_heard`,
so a fix has to be deliberate and cannot arrive by accident.

**Where.** `src/aitts/store.py` (`completed_segment_duration_ms`),
`src/aitts/playback.py` (`current_position_ms`, `_finish_segment_playback`).
