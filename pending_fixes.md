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

## 4. `reshape_for_animations`' own `rank` is wrong for a log that is not in time order

> **Corrected 2026-08-18.** An earlier version of this entry claimed the two rank
> computations agree and recommended deleting the one in `generate_animation_df`. That was
> wrong, and acting on it would have introduced a real defect. The probe used to "verify"
> it had row order and time order identical, so the two could not diverge. Recorded here
> rather than quietly rewritten, because the original claim was confidently stated.

**Where:** `reshape_for_animations` computes `rank` per event per snapshot; then
`generate_animation_df` immediately overwrites it with its own `groupby([event,
snapshot_time]).rank(method="first")`. The source carries a comment dated 29/09/2025
suggesting the duplication could be removed.

**The two do not agree.** `reshape_for_animations` ranks on `index` — the row's *position in
the event log file*. `generate_animation_df` ranks over the row order of the frame it
receives, which reshape has already sorted by `[time, index]`, so it reflects *join time*.
They coincide only when the log's row order happens to match its time order.

Reproduced with a log whose rows are grouped by entity rather than sorted by time — entity
2 listed first but joining at t=5, entity 10 listed second joining at t=1:

```
true join order by time : [10, 7, 2]
reshape rank order      : [2, 10, 7]   <- log row position, wrong
generate_animation_df   : [10, 7, 2]   <- join time, correct
```

**Consequence:** the recomputation in `generate_animation_df` is *masking* a defect in
`reshape_for_animations`, not duplicating it. Deleting it — as this entry previously
recommended — would push wrong queue order into every animation built from a log that is
not already time-sorted. Event logs assembled per-entity, or concatenated from per-entity
collectors, are a realistic way to hit this.

**Suggested fix:** correct the rank in `reshape_for_animations` to derive from join time
rather than file position, then the recomputation becomes genuinely redundant and can be
removed. Both halves should change together, with a test using a log whose row order
differs from its time order.

**Test coverage is currently insufficient.**
`tests/test_prep_positioning.py::test_queue_order_follows_join_time_not_entity_id` pins the
end-to-end property, but its fixture lists entities in join order, so it cannot see this
divergence. `tests/test_prep_reshape_semantics.py::test_rank_follows_order_of_joining_the_queue`
asserts reshape's rank *is* join order, which is only true for time-ordered logs — the test
name promises more than the assertion delivers. Both need a non-time-ordered case.

---

## 5. An empty snapshot window fails with an opaque `KeyError: 'entity_id'`

**Where:** `reshape_for_animations` in [src/vidigi/prep.py](src/vidigi/prep.py) — the final
`sort_values([entity_col_name, "snapshot_time"])`.

**Observed:** when no entity falls inside the requested window, every per-snapshot frame is
the placeholder row carrying only `snapshot_time`. The concatenated frame therefore has no
`entity_id` column, and the sort at the end fails:

```python
log = pd.DataFrame({
    "time": [100, 100, 145], "entity_id": [1, 1, 1],
    "event_type": ["arrival_departure", "queue", "arrival_departure"],
    "event": ["arrival", "waiting", "depart"]})
reshape_for_animations(log, every_x_time_units=10, limit_duration=50)
# KeyError: 'entity_id'
```

**Why it matters:** this is the same failure the v1.4.0 no-departures fix addressed, reached
by a different route, so the fix there did not cover it. The usual causes are benign and
easy to hit by accident — a `limit_duration` shorter than the model's warm-up, or filtering
to a replication whose events all fall outside the window. The error names an internal
column and gives no hint that the real problem is an empty time window.

**Why it is not urgent:** it is a crash, not silent corruption, so nobody ships a wrong
animation because of it. That is the only reason it sits here rather than being fixed.

**Suggested fix:** detect the empty result before the sort and raise a `ValueError` naming
`limit_duration`, the window requested, and the time range actually present in the log —
e.g. "no entities are present between t=0 and t=50; the log spans t=100 to t=145". An empty
animation is arguably also defensible, but an explicit error is more useful, since an empty
animation is almost never what the caller wanted.

**Not currently covered by any test.** Found while writing the multi-replication guard
tests, where a fixture shifted a second run's times beyond the requested window.

---

## 6. `VidigiStore`/`populate_store`/`VidigiPriorityStore` should require a `label` (2.0)

**Where:** `src/vidigi/resources.py` — `VidigiStore.__init__`/`.populate()`,
`populate_store()`, `VidigiPriorityStore.__init__`/`.populate()`.

**Current state (1.4.0):** each pool numbers its own units `1..capacity`
independently. An optional `label=` (added in 1.4.0) lets a modeller opt into a
collision-proof `unique_id_attribute`, and omitting it now emits a
`DeprecationWarning` — but it remains optional, so
`vidigi.analysis.resource_utilisation(by="resource")` can still silently pool two
different physical resources that share a number by default (mitigated, not
prevented, by a new overlap-detection warning added alongside this).

**Why deferred rather than forced now:** making `label` mandatory is breaking under
this repo's definition — every existing caller of the three populate-style
functions/methods would need to add one — and the plain numeric `id_attribute` is
still exactly correct for its original purpose (animation icon positioning via
`vidigi.prep`'s arithmetic); only the newer `by="resource"` analysis path is exposed
to the gap. This needs a deprecation period, not an immediate forced change.

**Planned for 2.0:** drop the `None` default, making `label` required on all three
call sites. Needs a `**BREAKING:**` HISTORY.md bullet and `### ⚠️ Breaking changes`
entry at that point, plus updating every example/test currently constructing these
without a label.

**Pinned by:** the 1.4.0 no-op/deprecation-warning tests in
`tests/test_resources_label.py` (asserting `label=None` still produces working,
unchanged resources plus a warning) — when `label` becomes mandatory at 2.0, those
tests are replaced by a missing-required-argument (`TypeError`) assertion instead.
