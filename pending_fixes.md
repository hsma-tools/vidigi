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
