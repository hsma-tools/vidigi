# Pending fixes

Known behaviours that look wrong but have **not** been changed, because fixing them would
alter output for callers who change nothing. Each needs an explicit decision before it is
touched. Where current behaviour is pinned by a test, that test is named so the assertion
can be updated alongside the fix.

---

## 1. `+ x more` overflow label may undercount by one

**Where:** `reshape_for_animations` in [src/vidigi/prep.py](src/vidigi/prep.py) — the
`additional` column, computed as `max - rank` on the boundary row.

**Observed:** with `step_snapshot_max=5` and 12 entities queued at one event:

- ranks 1–5 render as individual entity icons
- rank 6 is replaced by the overflow label
- ranks 7–12 are dropped entirely

So **seven** entities are not individually drawn, but the label reads `+ 6 more`.
`additional` is `12 - 6 = 6`, which omits the boundary row that the label itself replaced.

**Why it is ambiguous:** "6 more" is defensible if read as "6 more *after this one*", where
the label's own position stands in for the sixth entity. It is wrong if read as "6 entities
are hidden", which is the more natural reading and what most users will assume.

**Impact of changing it:** the caption changes on every animation that overflows a step.
Breaking under the project definition (results change with no caller change), so it needs a
`**BREAKING:**` HISTORY.md bullet and a `### ⚠️ Breaking changes` entry.

**Pinned by:**
`tests/test_prep_reshape_semantics.py::test_only_boundary_row_carries_additional_count`
asserts `additional == 6.0` with a comment recording the ambiguity. Update that assertion
if the arithmetic changes.

**Suggested fix if adopted:** `additional = max - rank + 1` on the boundary row, so the
count includes the entity whose slot the label occupies.

---

## 2. `limit_duration` overshoots by one snapshot interval

**Where:** `reshape_for_animations` in [src/vidigi/prep.py](src/vidigi/prep.py) — the
snapshot loop, `for time_unit in range(limit_duration + every_x_time_units)`.

**Observed:** with `limit_duration=45` and `every_x_time_units=10`, snapshots are generated
at 0, 10, 20, 30, 40 **and 50**. The final snapshot sits past the stated limit.

**Why it is ambiguous:** the comment above the loop says the intent is to cover everything
"up to AND INCLUDING the full duration we've passed as the limit", so overshooting to the
next interval boundary may well be deliberate — it guarantees the last partial interval is
represented rather than truncated. But it contradicts the docstring, which describes
`limit_duration` as "the maximum duration to consider", and the exit-step filter on the
same function *does* clamp strictly (`snapshot_time <= limit_duration`). The two halves of
the function therefore disagree about what the limit means.

**Note the interaction with fix #3 below:** `animate_activity_log` defaults
`limit_duration` to the log's maximum event time, so by default every animation renders one
frame beyond the last event. That frame is empty of real activity apart from exit steps.

**Impact of changing it:** every animation loses (or gains) a trailing frame, and
`TrialLogger.plot_queue_size` shifts its x-axis extent. Breaking.

**Pinned by:** `tests/test_prep_reshape_semantics.py::test_limit_duration_none_uses_max_time_in_log`
compares the `None` path against an explicit `limit_duration=45`, so it is insensitive to
the overshoot itself. No test currently asserts the overshoot directly — add one if the
behaviour is confirmed as intended.

**Decision needed:** either clamp the loop to `limit_duration` and document that the final
partial interval is dropped, or keep the overshoot and correct the docstring to say the
animation runs to the first interval boundary at or after `limit_duration`.

---

## 3. Queue sits one gap further forward when wrapping is enabled

**Where:** `generate_animation_df` in [src/vidigi/prep.py](src/vidigi/prep.py) — the queue
x-position calculation.

**Observed:** with an anchor of `x=400` and `gap_between_entities=10`, the entity at rank 1
is drawn at:

- `x = 400` when `wrap_queues_at=5`
- `x = 390` when `wrap_queues_at=None`

So turning wrapping off shifts the entire queue back by one full gap.

**Cause:** the base calculation is `x - rank * gap`, which puts rank 1 one gap behind the
anchor. The wrapping branch then adds `+ gap_between_entities` as part of its row offset,
which incidentally cancels that out. The unwrapped path has no equivalent, so the
compensation is only applied in one of the two modes.

**Why it is ambiguous:** it is not obvious which position is intended. Sitting rank 1
exactly on the anchor (wrapped behaviour) reads as the more deliberate choice, and matches
how `event_position_df` coordinates are documented as "the bottom-right corner of the queue
or resource". But the unwrapped path may equally be the reference and the wrapping branch's
`+ gap` may be an artefact of the row arithmetic.

**Impact of changing it:** every queue position shifts by `gap_between_entities` in
whichever mode is corrected. Visually small but affects every animation using that mode,
and background images aligned against current positions would need nudging. Breaking.

**Pinned by:** `tests/test_prep_positioning.py::test_queue_steps_back_from_anchor_by_gap`
(wrapped, rank 1 at 400) and `::test_wrap_queues_at_none_produces_single_row` (unwrapped,
rank 1 at 390). Both encode current behaviour; update whichever changes.

---

## 4. `rank` is computed twice, and the two computations agree (no action needed yet)

**Where:** `reshape_for_animations` computes `rank` per event per snapshot; then
`generate_animation_df` immediately overwrites it with its own `groupby([event,
snapshot_time]).rank(method="first")`. The source carries a comment dated 29/09/2025
noting the duplication and suggesting removal, but flagging that the two methods differ
"very slightly".

**Verified:** the two agree, including in the case most likely to break them — entity IDs
that are *not* in arrival order. With entities 10, 2 and 7 joining a queue in that order,
both computations rank them 10, 2, 7 (arrival order) rather than 2, 7, 10 (id order).

The reason is that `reshape_for_animations` sorts by `[time, index]` before
`groupby(entity).tail(1)`, and `tail` returns rows in their original frame order rather
than group order. That ordering then survives the final `sort_values(["snapshot_time",
event])` because pandas sorts are stable. So the row order the second computation ranks
over is already arrival order.

**Recorded because:** this is a latent fragility rather than a live defect. The second
computation's correctness depends entirely on an incidental property of the first — the
stability of an unrelated sort. Any future change to how `reshape_for_animations` orders
its output would silently reorder every queue in every animation, with no test in
`reshape_for_animations` itself able to catch it.

**Suggested action:** delete the recomputation in `generate_animation_df` and rely on the
rank `reshape_for_animations` already produces, which is derived explicitly from arrival
order rather than from row order. Low risk given the two are verified equal, but it is a
behaviour-preserving change that should still be made deliberately rather than in passing.

**Covered by:** `tests/test_prep_reshape_semantics.py::test_rank_follows_order_of_joining_the_queue`
and `::test_queue_closes_up_when_an_entity_leaves` assert the rank from
`reshape_for_animations`. Neither currently uses out-of-order entity IDs — add such a case
alongside any change here.
