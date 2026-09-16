"""Tests for the missing-event-position warning (companion to issue #143).

`generate_animation_df` resolves each snapshot's coordinates by left-merging onto
`event_position_df` on the event name. An event with no matching row gets `NaN`
x/y - and a point with no coordinates can't be drawn, so Plotly drops it from that
frame instead of placing it somewhere sensible. The entity's icon just disappears,
then flies in from the top-left corner once a positioned event takes over again.

The naive check - "does every event name in the raw log have a row in
`event_position_df`" - would false-positive constantly: models routinely log an
event (`arrival`, a `resource_use_end` step) at the exact same instant as the very
next step, and only an entity's latest event at or before each snapshot is ever
selected for rendering, so such an event is never chosen and never needs a
position. `_warn_on_unpositioned_rendered_events` instead checks the merged,
per-snapshot frame *after* that selection has happened, so it only fires on an
event that was actually picked to represent some entity's state and had nothing
to show for it.

Unlike the duplicate/colliding-position warnings, this check only exists at
`generate_animation_df` - `create_event_position_df` has no access to the
reshaped log, so it structurally cannot know which events are ever actually
rendered.
"""

import warnings

import pandas as pd
import pytest

from vidigi.prep import generate_animation_df, reshape_for_animations

# --------------------------------------------------------------------------- #
# generate_animation_df - point of use
# --------------------------------------------------------------------------- #


def test_does_not_warn_on_an_event_always_superseded_by_its_successor(
    simple_queue_log, basic_event_position_df
):
    # `arrival` is logged at the same instant as `waiting` for every entity in this
    # fixture, so it is never an entity's most-recently-logged step at a rendered
    # snapshot and never needs a position. This is the whole point of checking the
    # post-merge frame rather than the raw log - see module docstring.
    reshaped = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    event_position_df = basic_event_position_df[
        basic_event_position_df["event"] != "arrival"
    ].copy()
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        generate_animation_df(reshaped, event_position_df)
    unpositioned_warnings = [
        str(w.message) for w in record if "no matching" in str(w.message)
    ]
    assert unpositioned_warnings == []


def test_warns_on_an_event_that_is_genuinely_rendered(
    simple_queue_log, basic_event_position_df
):
    # `depart` is added as a synthetic exit row for every entity and is always
    # genuinely rendered, unlike `arrival` above.
    reshaped = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    event_position_df = basic_event_position_df[
        basic_event_position_df["event"] != "depart"
    ].copy()
    with pytest.warns(UserWarning, match=r"no matching `event_position_df` row"):
        generate_animation_df(reshaped, event_position_df)


def test_missing_event_warning_names_the_event_with_its_row_and_entity_count(
    simple_queue_log, basic_event_position_df
):
    reshaped = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    event_position_df = basic_event_position_df[
        basic_event_position_df["event"] != "depart"
    ].copy()
    with pytest.warns(UserWarning) as record:
        generate_animation_df(reshaped, event_position_df)
    message = next(str(w.message) for w in record if "no matching" in str(w.message))
    # All three entities depart within the animation window, so this is exact,
    # not a sampled entry.
    assert "3 row(s) across 1 event(s)" in message
    assert "'depart' (3 entities)" in message


def test_clean_positions_do_not_warn(simple_queue_log, basic_event_position_df):
    reshaped = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        generate_animation_df(reshaped, basic_event_position_df)
    unpositioned_warnings = [
        str(w.message) for w in record if "no matching" in str(w.message)
    ]
    assert unpositioned_warnings == []


def test_dropping_two_events_produces_one_warning_not_two(
    simple_queue_log, basic_event_position_df
):
    reshaped = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    event_position_df = basic_event_position_df[
        ~basic_event_position_df["event"].isin(["depart", "waiting"])
    ].copy()
    with pytest.warns(UserWarning) as record:
        generate_animation_df(reshaped, event_position_df)
    unpositioned_warnings = [
        str(w.message) for w in record if "no matching" in str(w.message)
    ]
    assert len(unpositioned_warnings) == 1
    message = unpositioned_warnings[0]
    assert "12 row(s) across 2 event(s)" in message
    assert "'depart' (3 entities)" in message
    assert "'waiting' (3 entities)" in message


def test_hand_built_event_position_df_with_a_gap_still_warns(
    simple_queue_log,
):
    # Not built through `create_event_position_df` - a plain DataFrame, the way a
    # caller who skips the documented helper would pass one in.
    reshaped = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    event_position_df = pd.DataFrame(
        [
            {"event": "arrival", "x": 50, "y": 300, "label": "Arrival"},
            {"event": "waiting", "x": 400, "y": 275, "label": "Waiting"},
        ]
    )
    with pytest.warns(UserWarning, match=r"'depart' \(3 entities\)"):
        generate_animation_df(reshaped, event_position_df)


def test_step_snapshot_max_overflow_row_does_not_crash_or_double_count(
    overflow_queue_log, basic_event_position_df
):
    # The overflow "+ N more" row shares its `event` value with the rows it
    # summarises, so it is already covered by the general per-event count rather
    # than needing separate handling.
    reshaped = reshape_for_animations(
        overflow_queue_log,
        every_x_time_units=10,
        limit_duration=110,
        step_snapshot_max=5,
    )
    event_position_df = basic_event_position_df[
        basic_event_position_df["event"] != "waiting"
    ].copy()
    with pytest.warns(UserWarning) as record:
        generate_animation_df(reshaped, event_position_df, step_snapshot_max=5)
    unpositioned_warnings = [
        str(w.message) for w in record if "no matching" in str(w.message)
    ]
    assert len(unpositioned_warnings) == 1
    assert "'waiting' (8 entities)" in unpositioned_warnings[0]
