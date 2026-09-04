"""Tests for `hidden_run_before` (`reshape_for_animations`) and
`step_snapshot_reveal_pop_in` (`generate_animation_df`) - see issue #143.

Without these, an entity that was present in the system but hidden behind
`step_snapshot_max` animates in from the top-left of the plot the instant it
becomes individually visible again, exactly as if it had just arrived. See
`generate_animation_df`'s `step_snapshot_reveal_pop_in` docstring for the
mechanism (an invisible phantom row one snapshot before the reveal) and why a
single lead frame is sufficient regardless of `frame_duration`/
`frame_transition_duration` (verified against a real browser DOM, not just
Python - see the issue's linked spike).
"""

import pandas as pd
import pytest

from vidigi.prep import generate_animation_df, reshape_for_animations

ZWSP = "​"


def _rows(*specs):
    """Build an event log from (time, entity_id, event_type, event) tuples."""
    return pd.DataFrame(
        [
            {
                "time": time,
                "entity_id": entity_id,
                "event_type": event_type,
                "event": event,
            }
            for time, entity_id, event_type, event in specs
        ]
    )


@pytest.fixture
def reveal_queue_log():
    """Eight entities join one queue at t=1..8 (so ranks 1..8 by join order).

    With `step_snapshot_max=5`, ranks 1-5 are drawn individually, rank 6 becomes
    the "+ N more" boundary row, and ranks 7-8 are dropped entirely.

    Entities 1-3 depart at t=20, which shifts the remaining entities' ranks down
    by 3: entity 4 -> rank 1, ..., entity 6 -> rank 3, entity 7 -> rank 4, entity
    8 -> rank 5. Entities 7 and 8 were previously dropped entirely, so this is a
    genuine reveal for both. Entity 6 sat at exactly the boundary rank
    (step_snapshot_max + 1 = 6) the whole time before that, so it is a control
    case: its own id survives every snapshot (under the overflow-row role,
    swapped by `generate_animation_df` later), so it must show *no* reveal.

    The remaining entities depart at t=35 so the run terminates cleanly.
    """
    specs = []
    for entity_id in range(1, 9):
        specs.append((entity_id, entity_id, "arrival_departure", "arrival"))
        specs.append((entity_id, entity_id, "queue", "waiting"))
    for entity_id in (1, 2, 3):
        specs.append((20, entity_id, "arrival_departure", "depart"))
    for entity_id in (4, 5, 6, 7, 8):
        specs.append((35, entity_id, "arrival_departure", "depart"))
    return _rows(*specs)


@pytest.fixture
def reveal_positions():
    from vidigi.utils import EventPosition, create_event_position_df

    return create_event_position_df(
        [
            EventPosition(event="arrival", x=50, y=300, label="Arrival"),
            EventPosition(event="waiting", x=400, y=275, label="Waiting"),
            EventPosition(event="depart", x=270, y=70, label="Exit"),
        ]
    )


def _series_for(result, entity_id, column="hidden_run_before"):
    rows = result[result["entity_id"] == entity_id].sort_values("snapshot_time")
    return list(zip(rows["snapshot_time"], rows[column]))


# --------------------------------------------------------------------------- #
# hidden_run_before
# --------------------------------------------------------------------------- #


def test_hidden_run_before_zero_for_genuine_arrival(reveal_queue_log):
    """A brand new arrival's first row is never treated as a reveal."""
    result = reshape_for_animations(
        reveal_queue_log,
        every_x_time_units=1,
        limit_duration=40,
        step_snapshot_max=5,
    )
    result = result[result["event_type"] != "exit"]

    # Entity 1 arrives at t=1 and departs at t=20; its whole surviving series is
    # continuous (never capped), so every row is 0 - the whole series, not a
    # sample, since a bug that only mis-set one row would pass a spot check.
    series = _series_for(result, 1.0)
    assert series == [(t, 0) for t, _ in series]
    assert len(series) > 0


def test_hidden_run_before_marks_exact_reveal_gap(reveal_queue_log):
    """Entity 8 was hidden by the cap from its arrival (t=8) until it is
    individually drawn again at t=20 - a gap of exactly 12 snapshots."""
    result = reshape_for_animations(
        reveal_queue_log,
        every_x_time_units=1,
        limit_duration=40,
        step_snapshot_max=5,
    )
    result = result[result["event_type"] != "exit"]

    series = _series_for(result, 8.0)
    # First surviving row is the reveal itself, at t=20, with hidden_run_before
    # == 12 (snapshots t=8..t=19 inclusive). Every row after that is ordinary
    # continuous movement, so 0. Asserting the whole series, not just the first
    # value, so a bug that also touched later rows would be caught.
    expected = [(20.0, 12)] + [(t, 0) for t in range(21, 36)]
    assert series == expected


def test_boundary_role_entity_hidden_run_before_zero_while_boundary(
    reveal_queue_log,
):
    """While an entity sits at exactly rank == step_snapshot_max + 1 (the
    overflow/boundary role, t=6..19 for entity 6 here), it must never look
    like a reveal - the boundary row already has its own stable-id fix for
    the label it's playing, and this only concerns the entity's *own* id."""
    result = reshape_for_animations(
        reveal_queue_log,
        every_x_time_units=1,
        limit_duration=40,
        step_snapshot_max=5,
    )
    result = result[result["event_type"] != "exit"]

    series = _series_for(result, 6.0)
    boundary_period = [(t, v) for t, v in series if t < 20]
    assert boundary_period == [(t, 0) for t, _ in boundary_period]
    assert len(boundary_period) == 14  # t=6..19


def test_boundary_role_entity_becoming_individual_is_a_reveal(reveal_queue_log):
    """A boundary-role entity's *own* id is never actually rendered while it
    plays that role - `generate_animation_df` relabels the row to a stable
    synthetic overflow id before drawing it. So when entity 6 later becomes
    individually visible (rank 3, once entities 1-3 depart at t=20), its own
    icon is rendered for the first time, exactly like any other reveal - this
    must be detected as a gap despite the row itself having "survived"
    throughout in `full_entity_df`."""
    result = reshape_for_animations(
        reveal_queue_log,
        every_x_time_units=1,
        limit_duration=40,
        step_snapshot_max=5,
    )
    result = result[result["event_type"] != "exit"]

    series = _series_for(result, 6.0)
    # Boundary role from arrival (t=6) through t=19 - 14 snapshots - then
    # individually visible from t=20.
    expected = [(t, 0) for t in range(6, 20)] + [(20.0, 14)] + [
        (t, 0) for t in range(21, 36)
    ]
    assert series == expected


def test_exit_row_hidden_run_before_is_zero(reveal_queue_log):
    """A departure right after a reveal must not carry the reveal's gap
    forward onto the synthetic exit row - there is no real gap between the
    entity's last real row and its exit pseudo-frame."""
    result = reshape_for_animations(
        reveal_queue_log,
        every_x_time_units=1,
        limit_duration=40,
        step_snapshot_max=5,
    )
    exit_row = result[
        (result["entity_id"] == 8.0) & (result["event_type"] == "exit")
    ]
    assert len(exit_row) == 1
    assert exit_row.iloc[0]["hidden_run_before"] == 0


# --------------------------------------------------------------------------- #
# step_snapshot_reveal_pop_in
# --------------------------------------------------------------------------- #


def test_flag_off_is_a_byte_identical_noop(reveal_queue_log, reveal_positions):
    reshaped = reshape_for_animations(
        reveal_queue_log,
        every_x_time_units=1,
        limit_duration=40,
        step_snapshot_max=5,
    )
    omitted = generate_animation_df(
        reshaped, reveal_positions, step_snapshot_max=5, wrap_queues_at=None
    )
    explicit_false = generate_animation_df(
        reshaped,
        reveal_positions,
        step_snapshot_max=5,
        wrap_queues_at=None,
        step_snapshot_reveal_pop_in=False,
    )
    assert omitted.equals(explicit_false)
    assert "_phantom" not in omitted.columns


def test_reveal_gets_exactly_one_phantom_row_before_it(
    reveal_queue_log, reveal_positions
):
    reshaped = reshape_for_animations(
        reveal_queue_log,
        every_x_time_units=1,
        limit_duration=40,
        step_snapshot_max=5,
    )
    result = generate_animation_df(
        reshaped,
        reveal_positions,
        step_snapshot_max=5,
        wrap_queues_at=None,
        step_snapshot_reveal_pop_in=True,
    )

    phantoms = result[result["_phantom"]]
    entity_8_phantoms = phantoms[phantoms["entity_id"] == 8.0]
    assert len(entity_8_phantoms) == 1

    phantom_row = entity_8_phantoms.iloc[0]
    reveal_row = result[
        (result["entity_id"] == 8.0)
        & (result["snapshot_time"] == 20.0)
        & (~result["_phantom"])
    ].iloc[0]

    # One grid step (every_x_time_units=1) before the reveal.
    assert phantom_row["snapshot_time"] == 19.0
    assert phantom_row["icon"] == ZWSP
    # Same destination the entity will actually occupy - the whole point being
    # that there is nothing left for Plotly to interpolate at the reveal frame.
    assert phantom_row["x_final"] == reveal_row["x_final"]
    assert phantom_row["y_final"] == reveal_row["y_final"]


def test_boundary_role_entity_becoming_individual_also_gets_a_phantom(
    reveal_queue_log, reveal_positions
):
    """Entity 6's own icon is never actually rendered while it plays the
    boundary/overflow role (see the `reshape_for_animations` test of the same
    name), so its later transition to individually-drawn at t=20 must be
    treated as a reveal here too, not just at the `hidden_run_before` level."""
    reshaped = reshape_for_animations(
        reveal_queue_log,
        every_x_time_units=1,
        limit_duration=40,
        step_snapshot_max=5,
    )
    result = generate_animation_df(
        reshaped,
        reveal_positions,
        step_snapshot_max=5,
        wrap_queues_at=None,
        step_snapshot_reveal_pop_in=True,
    )

    phantoms = result[result["_phantom"]]
    entity_6_phantoms = phantoms[phantoms["entity_id"] == 6.0]
    assert len(entity_6_phantoms) == 1
    assert entity_6_phantoms.iloc[0]["snapshot_time"] == 19.0
    assert entity_6_phantoms.iloc[0]["icon"] == ZWSP


def test_genuine_arrivals_get_no_phantom(reveal_queue_log, reveal_positions):
    reshaped = reshape_for_animations(
        reveal_queue_log,
        every_x_time_units=1,
        limit_duration=40,
        step_snapshot_max=5,
    )
    result = generate_animation_df(
        reshaped,
        reveal_positions,
        step_snapshot_max=5,
        wrap_queues_at=None,
        step_snapshot_reveal_pop_in=True,
    )

    entity_1_rows = result[result["entity_id"] == 1.0]
    assert not entity_1_rows["_phantom"].any()


def test_overflow_rows_never_get_a_phantom(reveal_queue_log, reveal_positions):
    """The '+ N more' row already has its own stable-id fix; it must not also
    be treated as a phantom-eligible reveal."""
    reshaped = reshape_for_animations(
        reveal_queue_log,
        every_x_time_units=1,
        limit_duration=40,
        step_snapshot_max=5,
    )
    result = generate_animation_df(
        reshaped,
        reveal_positions,
        step_snapshot_max=5,
        wrap_queues_at=None,
        step_snapshot_reveal_pop_in=True,
    )

    overflow_rows = result[result["additional"].notna()]
    assert len(overflow_rows) > 0
    assert not overflow_rows["_phantom"].any()


@pytest.fixture
def reveal_into_boundary_log():
    """Like `reveal_queue_log`, but only entities 1-2 depart at t=20 (not 1-3).

    Ranks then shift down by 2 instead of 3: entity 8 (previously fully
    dropped at rank 8) lands exactly on rank 6 == step_snapshot_max + 1 - the
    boundary row itself - rather than becoming individually visible. Its own
    id has `hidden_run_before >= 1` (it was genuinely hidden) *and* becomes an
    overflow row (`additional` not null) on the very same row - the one case
    that actually exercises the overflow exclusion in the phantom mask, since
    every other fixture here only ever has one of those two conditions true on
    a given row.
    """
    specs = []
    for entity_id in range(1, 9):
        specs.append((entity_id, entity_id, "arrival_departure", "arrival"))
        specs.append((entity_id, entity_id, "queue", "waiting"))
    for entity_id in (1, 2):
        specs.append((20, entity_id, "arrival_departure", "depart"))
    for entity_id in (3, 4, 5, 6, 7, 8):
        specs.append((35, entity_id, "arrival_departure", "depart"))
    return _rows(*specs)


def test_entity_landing_on_the_boundary_row_gets_no_phantom(
    reveal_into_boundary_log, reveal_positions
):
    reshaped = reshape_for_animations(
        reveal_into_boundary_log,
        every_x_time_units=1,
        limit_duration=40,
        step_snapshot_max=5,
    )
    result = generate_animation_df(
        reshaped,
        reveal_positions,
        step_snapshot_max=5,
        wrap_queues_at=None,
        step_snapshot_reveal_pop_in=True,
    )

    entity_8_at_reveal = result[
        (result["entity_id"] == 8.0) & (result["snapshot_time"] == 20.0)
    ]
    assert len(entity_8_at_reveal) == 0, (
        "entity 8's own id should not appear at t=20 at all - it becomes the "
        "boundary row, relabelled to the synthetic overflow id"
    )

    entity_8_phantoms = result[
        (result["entity_id"] == 8.0) & (result["_phantom"])
    ]
    assert len(entity_8_phantoms) == 0


def test_no_entity_occupies_two_positions_in_one_frame_with_phantoms(
    reveal_queue_log, reveal_positions
):
    """A phantom row must land in a *different* frame from the entity's real
    row for that snapshot, never the same one - the same invariant checked
    (without phantoms) in test_prep_positioning.py."""
    reshaped = reshape_for_animations(
        reveal_queue_log,
        every_x_time_units=1,
        limit_duration=40,
        step_snapshot_max=5,
    )
    result = generate_animation_df(
        reshaped,
        reveal_positions,
        step_snapshot_max=5,
        wrap_queues_at=None,
        step_snapshot_reveal_pop_in=True,
    )
    tracked = result[result["entity_id"].notnull()]

    duplicates = tracked.groupby(["snapshot_time", "entity_id"]).size()
    offenders = duplicates[duplicates > 1]
    assert offenders.empty, (
        f"Entities drawn in more than one position in a single frame:\n{offenders}"
    )
