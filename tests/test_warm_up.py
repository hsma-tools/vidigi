"""Tests for discarding a warm-up period via ``warm_up``.

Removing a warm-up period is routine in a DES study, and the obvious way to do
it to an event log - ``log[log["time"] >= warm_up]`` - quietly breaks the
animation. Presence at each snapshot is derived from arrival and departure rows,
so truncating the log strips the arrival row of everyone already in the system
and those entities disappear from every frame. The queue that a steady-state
animation is meant to show is exactly the queue that gets deleted.

``warm_up`` trims the animation window instead, leaving the history intact.
These tests pin both halves: that the parameter shows what truncation hid, and
that truncation itself now says so.
"""

import warnings

import pandas as pd
import pytest

from vidigi.animation import animate_activity_log
from vidigi.prep import reshape_for_animations


def _waiting_at(reshaped, snapshot_time):
    at_time = reshaped[
        (reshaped["snapshot_time"] == snapshot_time) & (reshaped["event"] == "waiting")
    ]
    return sorted(at_time["entity_id"].dropna().astype(int).tolist())


# --------------------------------------------------------------------------- #
# The behaviour warm_up exists for
# --------------------------------------------------------------------------- #


def test_warm_up_keeps_entities_that_arrived_before_the_window(warm_up_log):
    """The whole point: entities already queuing must still be drawn.

    Entities 1-5 joined the queue during the warm-up and have not departed.
    They are part of the queue at snapshot 120 and must be shown as such.
    """
    reshaped = reshape_for_animations(
        warm_up_log, every_x_time_units=10, limit_duration=200, warm_up=100
    )

    # There is genuinely a window - without this the assertions below still pass
    # if warm_up is ignored altogether.
    assert reshaped["snapshot_time"].min() == 100

    assert _waiting_at(reshaped, 100) == [1, 2, 3, 4, 5]
    assert _waiting_at(reshaped, 120) == [1, 2, 3, 4, 5, 6, 7]


def test_truncating_the_log_by_time_loses_those_entities(warm_up_log):
    """The trap, pinned so the contrast above cannot quietly stop being true.

    This is not desired behaviour - it is the behaviour `warm_up` exists to let
    users avoid, and it is why truncating now warns.
    """
    truncated = warm_up_log[warm_up_log["time"] >= 100]

    with pytest.warns(UserWarning, match="no 'arrival' event"):
        reshaped = reshape_for_animations(
            truncated, every_x_time_units=10, limit_duration=200
        )

    assert _waiting_at(reshaped, 120) == [6, 7]


def test_warm_up_excludes_entities_that_left_during_it(warm_up_log):
    """Entity 8 arrives at t=10 and departs at t=50, so has no business in the
    window at all - the window really starts later, rather than just relabelling."""
    reshaped = reshape_for_animations(
        warm_up_log, every_x_time_units=10, limit_duration=200, warm_up=100
    )

    assert 8 not in set(reshaped["entity_id"].dropna().astype(int))


def test_warm_up_anchors_the_snapshot_grid(warm_up_log):
    """Snapshots start exactly on the boundary, not at the next interval.

    The trailing 220 is past `limit_duration`, which looks wrong but is the
    pre-existing overshoot recorded in `pending_fixes.md` #2 - the loop runs to
    `limit_duration + every_x_time_units`. It happens identically at warm_up=0
    (0, 30 ... 210 for the same limit), so it is inherited here rather than
    introduced. This assertion encodes a deferred decision, not a verified
    expectation; update it alongside any fix to #2.
    """
    reshaped = reshape_for_animations(
        warm_up_log, every_x_time_units=30, limit_duration=200, warm_up=100
    )

    assert sorted(reshaped["snapshot_time"].unique()) == [100, 130, 160, 190, 220]


# --------------------------------------------------------------------------- #
# snapshot_alignment
#
# Two ways to place the grid, both correct. The default puts the first frame on
# the boundary; "run_start" keeps the frame times a caller would have got with no
# warm-up, which is what the longstanding workaround of filtering the reshaped
# frame by snapshot_time produced.
# --------------------------------------------------------------------------- #


def test_run_start_alignment_keeps_the_grid_running_from_zero(warm_up_log):
    reshaped = reshape_for_animations(
        warm_up_log,
        every_x_time_units=30,
        limit_duration=200,
        warm_up=100,
        snapshot_alignment="run_start",
    )

    # The grid is 0, 30, 60 ... with everything before the warm-up dropped, so it
    # starts at 120 rather than at 100. See test_warm_up_anchors_the_snapshot_grid
    # for the default, which gives 100, 130, 160 ... instead.
    assert sorted(reshaped["snapshot_time"].unique()) == [120, 150, 180, 210]


def test_both_alignments_show_the_same_entities(warm_up_log):
    """Alignment moves the frame times, never who is in them.

    This is the property that matters: whichever grid is chosen, the entities
    that were queuing before the boundary are still drawn.
    """
    anchored = reshape_for_animations(
        warm_up_log, every_x_time_units=10, limit_duration=200, warm_up=100
    )
    from_run_start = reshape_for_animations(
        warm_up_log,
        every_x_time_units=10,
        limit_duration=200,
        warm_up=100,
        snapshot_alignment="run_start",
    )

    assert _waiting_at(anchored, 120) == [1, 2, 3, 4, 5, 6, 7]
    assert _waiting_at(from_run_start, 120) == [1, 2, 3, 4, 5, 6, 7]


def test_alignments_agree_when_warm_up_is_a_multiple_of_the_interval(warm_up_log):
    """The documented case in which the choice does not matter."""
    kwargs = dict(every_x_time_units=30, limit_duration=200, warm_up=90)

    anchored = reshape_for_animations(warm_up_log, **kwargs)
    from_run_start = reshape_for_animations(
        warm_up_log, snapshot_alignment="run_start", **kwargs
    )

    assert sorted(anchored["snapshot_time"].unique()) == [90, 120, 150, 180, 210]
    assert anchored.equals(from_run_start)


def test_alignment_is_irrelevant_without_a_warm_up(warm_up_log):
    kwargs = dict(every_x_time_units=30, limit_duration=200)

    assert reshape_for_animations(warm_up_log, **kwargs).equals(
        reshape_for_animations(warm_up_log, snapshot_alignment="run_start", **kwargs)
    )


def test_invalid_snapshot_alignment_raises(warm_up_log):
    """The `SnapshotAlignment` annotation is a hint for editors and type checkers,
    not a runtime constraint, so the explicit check still has to be there."""
    with pytest.raises(ValueError, match="Invalid snapshot_alignment"):
        reshape_for_animations(
            warm_up_log,
            every_x_time_units=10,
            limit_duration=200,
            warm_up=100,
            snapshot_alignment="from_zero",
        )


# --------------------------------------------------------------------------- #
# Existing callers must be unaffected
# --------------------------------------------------------------------------- #


def test_warm_up_zero_is_identical_to_omitting_it(warm_up_log):
    """The default must be a true no-op, not merely a similar result."""
    default = reshape_for_animations(
        warm_up_log, every_x_time_units=10, limit_duration=200
    )
    explicit = reshape_for_animations(
        warm_up_log, every_x_time_units=10, limit_duration=200, warm_up=0
    )

    assert default.equals(explicit)


def test_no_warning_for_a_log_where_everyone_arrives(simple_queue_log):
    """The warning must not fire on an ordinary, untruncated log.

    A warning that cries wolf gets filtered out along with the real one.
    """
    with warnings.catch_warnings(record=True) as raised:
        warnings.simplefilter("always")
        reshape_for_animations(
            simple_queue_log, every_x_time_units=10, limit_duration=50
        )

    assert not [w for w in raised if "no 'arrival' event" in str(w.message)]


def test_warning_counts_every_entity_without_an_arrival(warm_up_log):
    truncated = warm_up_log[warm_up_log["time"] >= 100]

    with pytest.warns(UserWarning) as raised:
        reshape_for_animations(truncated, every_x_time_units=10, limit_duration=200)

    message = str(raised[0].message)
    assert "5 entities" in message
    # Named individually so the user can go and look at them.
    assert "1, 2, 3, 4, 5" in message
    assert "warm_up" in message


def test_entity_with_only_non_arrival_events_is_reported(warm_up_log):
    """The signature is 'no arrival row', not 'no arrival_departure rows'.

    An entity still in the system at the end of a truncated log has no depart
    row either, so it is absent from the pivot entirely rather than present with
    a null arrival. Both shapes must be caught.
    """
    log = pd.DataFrame(
        [
            (110, 1, "arrival_departure", "arrival"),
            (110, 1, "queue", "waiting"),
            (150, 2, "queue", "waiting"),  # no arrival, no depart
        ],
        columns=["time", "entity_id", "event_type", "event"],
    )

    with pytest.warns(UserWarning, match="1 entities"):
        reshape_for_animations(log, every_x_time_units=10, limit_duration=200)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def test_warm_up_after_limit_duration_raises(warm_up_log):
    with pytest.raises(ValueError, match="animation window is empty"):
        reshape_for_animations(
            warm_up_log, every_x_time_units=10, limit_duration=100, warm_up=200
        )


def test_negative_warm_up_raises(warm_up_log):
    with pytest.raises(ValueError, match="must not be negative"):
        reshape_for_animations(
            warm_up_log, every_x_time_units=10, limit_duration=200, warm_up=-10
        )


def test_warm_up_accepts_a_float_that_is_a_whole_number(warm_up_log):
    """Consistent with the other time arguments, which coerce rather than reject."""
    with pytest.warns(UserWarning, match="rounding to nearest integer"):
        coerced = reshape_for_animations(
            warm_up_log, every_x_time_units=10, limit_duration=200, warm_up=100.0
        )
    integer = reshape_for_animations(
        warm_up_log, every_x_time_units=10, limit_duration=200, warm_up=100
    )

    assert coerced.equals(integer)


# --------------------------------------------------------------------------- #
# End to end
# --------------------------------------------------------------------------- #


def test_animate_activity_log_passes_warm_up_through(
    warm_up_log, basic_event_position_df
):
    """The parameter is useless if the top-level entry point drops it."""
    fig = animate_activity_log(
        warm_up_log,
        basic_event_position_df,
        every_x_time_units=10,
        limit_duration=200,
        warm_up=100,
    )

    assert [frame.name for frame in fig.frames][:3] == ["100", "110", "120"]

    without = animate_activity_log(
        warm_up_log,
        basic_event_position_df,
        every_x_time_units=10,
        limit_duration=200,
    )

    assert [frame.name for frame in without.frames][:3] == ["0", "10", "20"]


def test_animate_activity_log_passes_snapshot_alignment_through(
    warm_up_log, basic_event_position_df
):
    fig = animate_activity_log(
        warm_up_log,
        basic_event_position_df,
        every_x_time_units=30,
        limit_duration=200,
        warm_up=100,
        snapshot_alignment="run_start",
    )

    assert [frame.name for frame in fig.frames] == ["120", "150", "180", "210"]
