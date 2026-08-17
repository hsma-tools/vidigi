"""Geometry tests for ``generate_animation_df``.

This function decides where every entity is drawn in every frame, and had no
dedicated coverage. Errors here are the "entity rendered in the wrong place"
class of bug, which is invisible to shape and column assertions.

Positions are asserted as literals derived from the documented rules:

* a queue's anchor is the ``x``/``y`` given in ``event_position_df``
* entities step back from that anchor by ``gap_between_entities`` per rank
* on wrapping, the row index advances and ``y`` grows by
  ``gap_between_queue_rows``
"""

import numpy as np
import pandas as pd
import pytest

from vidigi.prep import (
    ascii_queue_icon,
    generate_animation_df,
    reshape_for_animations,
    _event_to_icon_id,
)


def positions_at(result, snapshot_time, event):
    """(rank -> (x_final, y_final)) for one event at one snapshot."""
    rows = result[
        (result["snapshot_time"] == snapshot_time) & (result["event"] == event)
    ]
    return {
        row["rank"]: (row["x_final"], row["y_final"]) for _, row in rows.iterrows()
    }


@pytest.fixture
def overflow_positions(overflow_queue_log, basic_event_position_df):
    """Twelve entities queued at the 'waiting' anchor (x=400, y=275)."""

    def _build(**kwargs):
        params = dict(
            wrap_queues_at=5,
            gap_between_entities=10,
            gap_between_queue_rows=30,
            step_snapshot_max=60,
        )
        params.update(kwargs)
        reshaped = reshape_for_animations(
            overflow_queue_log,
            every_x_time_units=10,
            limit_duration=30,
            step_snapshot_max=params["step_snapshot_max"],
        )
        return generate_animation_df(
            reshaped, basic_event_position_df, **params
        )

    return _build


# --------------------------------------------------------------------------- #
# Queue geometry
# --------------------------------------------------------------------------- #


def test_queue_steps_back_from_anchor_by_gap(overflow_positions):
    """Rank 1 sits at the anchor; each later rank is one gap further back."""
    result = overflow_positions(wrap_queues_at=5, gap_between_entities=10)
    positions = positions_at(result, 20, "waiting")

    assert positions[1.0] == (400.0, 275.0)
    assert positions[2.0] == (390.0, 275.0)
    assert positions[3.0] == (380.0, 275.0)
    assert positions[5.0] == (360.0, 275.0)


def test_queue_wraps_to_new_row(overflow_positions):
    """Rank 6 with wrap_queues_at=5 starts a new row below the first."""
    result = overflow_positions(
        wrap_queues_at=5, gap_between_entities=10, gap_between_queue_rows=30
    )
    positions = positions_at(result, 20, "waiting")

    # Back to the anchor's x, one row lower.
    assert positions[6.0] == (400.0, 305.0)
    assert positions[10.0] == (360.0, 305.0)
    # And a third row.
    assert positions[11.0] == (400.0, 335.0)


def test_gap_between_entities_scales_spacing(overflow_positions):
    """Doubling the gap doubles the distance between adjacent ranks."""
    result = overflow_positions(wrap_queues_at=5, gap_between_entities=20)
    positions = positions_at(result, 20, "waiting")

    assert positions[1.0][0] == 400.0
    assert positions[2.0][0] == 380.0
    assert positions[3.0][0] == 360.0


def test_wrap_queues_at_none_produces_single_row(overflow_positions):
    """`None` means "never wrap", as documented.

    Regression test: this raised TypeError from `step_snapshot_max %
    wrap_queues_at` before the None guard 80 lines further down was ever
    reached, and again from the overflow offset's `wrap_queues_at / 2`.
    """
    result = overflow_positions(wrap_queues_at=None, gap_between_entities=10)
    positions = positions_at(result, 20, "waiting")

    # Every entity on one row, so a single y value throughout.
    assert {y for _, y in positions.values()} == {275.0}
    # Strictly decreasing x, one gap apart, with no wrap offset applied.
    assert positions[1.0][0] == 390.0
    assert positions[7.0][0] == 330.0


def test_queue_order_follows_join_time_not_entity_id(basic_event_position_df):
    """Queue position is arrival order, even when entity IDs are unsorted.

    generate_animation_df recomputes `rank` over the row order it receives,
    discarding the one reshape_for_animations derived from arrival order. The
    two agree only because that row order happens to be arrival order. This
    pins the property end to end so a future reordering cannot silently shuffle
    every queue. See pending_fixes.md entry 4.
    """
    # Entity 10 joins first, then 2, then 7 - deliberately not id order.
    specs = []
    for entity_id, join_time in [(10, 1), (2, 2), (7, 3)]:
        specs += [
            (join_time, entity_id, "arrival_departure", "arrival"),
            (join_time, entity_id, "queue", "waiting"),
            (100, entity_id, "arrival_departure", "depart"),
        ]
    log = pd.DataFrame(
        [
            {"time": t, "entity_id": e, "event_type": et, "event": ev}
            for t, e, et, ev in specs
        ]
    )

    reshaped = reshape_for_animations(log, every_x_time_units=10, limit_duration=30)
    result = generate_animation_df(reshaped, basic_event_position_df)
    queue = result[
        (result["snapshot_time"] == 20) & (result["event"] == "waiting")
    ].sort_values("rank")

    assert queue["entity_id"].tolist() == [10.0, 2.0, 7.0]
    # Front of the queue is the largest x, so x must decrease with join order.
    assert queue["x_final"].is_monotonic_decreasing


def test_queue_row_assignment_is_monotonic(overflow_positions):
    """y never decreases as rank increases - the queue grows one way only."""
    result = overflow_positions(wrap_queues_at=5)
    rows = result[
        (result["snapshot_time"] == 20) & (result["event"] == "waiting")
    ].sort_values("rank")

    assert rows["y_final"].is_monotonic_increasing


# --------------------------------------------------------------------------- #
# Resource geometry
# --------------------------------------------------------------------------- #


def test_resource_position_derives_from_resource_id(
    resource_log, basic_event_position_df
):
    """Resource use is placed by resource_id, not by queue rank.

    This is what keeps an entity pinned to the same cubicle for the whole of
    its stay rather than shuffling along as others arrive and leave.
    """
    reshaped = reshape_for_animations(
        resource_log, every_x_time_units=10, limit_duration=50
    )
    result = generate_animation_df(
        reshaped,
        basic_event_position_df,
        wrap_resources_at=20,
        gap_between_resources=10,
    )
    treated = result[result["event"] == "treatment_begins"]

    by_resource = {
        row["resource_id"]: (row["x_final"], row["y_final"])
        for _, row in treated.iterrows()
    }

    # Anchor for treatment_begins is x=400, y=175.
    assert by_resource[1.0] == (400.0, 175.0)
    assert by_resource[2.0] == (390.0, 175.0)


def test_entity_stays_at_same_resource_position_across_snapshots(
    resource_log, basic_event_position_df
):
    """An entity occupying a resource does not drift between frames."""
    reshaped = reshape_for_animations(
        resource_log, every_x_time_units=10, limit_duration=50
    )
    result = generate_animation_df(reshaped, basic_event_position_df)

    entity_1 = result[
        (result["entity_id"] == 1) & (result["event"] == "treatment_begins")
    ]

    assert entity_1["x_final"].nunique() == 1
    assert entity_1["y_final"].nunique() == 1


def test_wrap_resources_at_none_produces_single_row(
    resource_log, basic_event_position_df
):
    """Resources also honour `None` as "never wrap"."""
    reshaped = reshape_for_animations(
        resource_log, every_x_time_units=10, limit_duration=50
    )
    result = generate_animation_df(
        reshaped,
        basic_event_position_df,
        wrap_resources_at=None,
        gap_between_resources=10,
    )
    treated = result[result["event"] == "treatment_begins"]

    assert treated["y_final"].nunique() == 1


# --------------------------------------------------------------------------- #
# Exit and other event types
# --------------------------------------------------------------------------- #


def test_exit_steps_sit_at_their_anchor(simple_queue_log, basic_event_position_df):
    """Exit steps use the raw event position, with no rank offset."""
    reshaped = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    result = generate_animation_df(reshaped, basic_event_position_df)
    exits = result[result["event_type"] == "exit"]

    assert not exits.empty
    # 'depart' is anchored at x=270, y=70.
    assert set(exits["x_final"]) == {270.0}
    assert set(exits["y_final"]) == {70.0}


def test_unknown_event_types_fall_back_to_anchor(basic_event_position_df):
    """A custom event type is placed at its anchor rather than being dropped."""
    log = pd.DataFrame(
        {
            "time": [0, 5, 20],
            "entity_id": [1, 1, 1],
            "event_type": ["arrival_departure", "custom_type", "arrival_departure"],
            "event": ["arrival", "waiting", "depart"],
        }
    )
    reshaped = reshape_for_animations(log, every_x_time_units=10, limit_duration=30)
    result = generate_animation_df(reshaped, basic_event_position_df)

    custom = result[result["event_type"] == "custom_type"]

    assert not custom.empty
    assert set(custom["x_final"]) == {400.0}
    assert set(custom["y_final"]) == {275.0}


# --------------------------------------------------------------------------- #
# The single-position invariant
# --------------------------------------------------------------------------- #


def test_no_entity_occupies_two_positions_in_one_frame(
    resource_log, basic_event_position_df
):
    """The animation assumes one entity is in one place per frame.

    This is the check flagged as a TODO twice in prep.py. Two rows for one
    entity in one frame would render the same icon in two places at once.
    """
    reshaped = reshape_for_animations(
        resource_log, every_x_time_units=10, limit_duration=50
    )
    result = generate_animation_df(reshaped, basic_event_position_df)
    tracked = result[result["entity_id"].notnull()]

    duplicates = tracked.groupby(["snapshot_time", "entity_id"]).size()
    offenders = duplicates[duplicates > 1]

    assert offenders.empty, (
        f"Entities drawn in more than one position in a single frame:\n{offenders}"
    )


def test_empty_snapshots_survive_positioning(
    simple_queue_log, basic_event_position_df
):
    """Placeholder rows for empty frames must not be dropped by the merges."""
    reshaped = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    result = generate_animation_df(reshaped, basic_event_position_df)

    assert set(result["snapshot_time"].unique()) == {0, 10, 20, 30, 40, 50}


# --------------------------------------------------------------------------- #
# Icon assignment
# --------------------------------------------------------------------------- #


def test_each_entity_keeps_one_icon_throughout(
    simple_queue_log, basic_event_position_df
):
    """An entity's icon is stable across frames, so it can be followed by eye."""
    reshaped = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    result = generate_animation_df(reshaped, basic_event_position_df)
    tracked = result[result["entity_id"].notnull()]

    icons_per_entity = tracked.groupby("entity_id")["icon"].nunique()

    assert (icons_per_entity == 1).all()


def test_custom_entity_icon_list_is_used_and_cycles(
    overflow_queue_log, basic_event_position_df
):
    """A short custom list wraps around rather than running out."""
    reshaped = reshape_for_animations(
        overflow_queue_log, every_x_time_units=10, limit_duration=30
    )
    result = generate_animation_df(
        reshaped, basic_event_position_df, custom_entity_icon_list=["A", "B", "C"]
    )
    tracked = result[result["entity_id"].notnull()]

    assert set(tracked["icon"]) <= {"A", "B", "C"}

    # 12 entities over a 3 icon list, assigned in sorted entity order, so the
    # list is walked in order and then repeats from the start.
    assigned = {
        entity_id: group["icon"].iloc[0]
        for entity_id, group in tracked.groupby("entity_id")
    }
    assert [assigned[float(i)] for i in range(1, 13)] == list("ABC") * 4


def test_custom_entity_icon_list_is_not_mutated(
    simple_queue_log, basic_event_position_df
):
    """The caller's list must survive the call unchanged."""
    icons = ["A", "B", "C"]
    reshaped = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )

    generate_animation_df(
        reshaped, basic_event_position_df, custom_entity_icon_list=icons
    )

    assert icons == ["A", "B", "C"]


# --------------------------------------------------------------------------- #
# Overflow placeholder
# --------------------------------------------------------------------------- #


def test_overflow_row_gets_stable_synthetic_entity_id(overflow_positions):
    """The '+ x more' label keeps one id per event across every frame.

    Without this the label counts as a new entity each frame and plotly
    animates it flying in from off-screen.
    """
    result = overflow_positions(step_snapshot_max=5, wrap_queues_at=5)
    overflow = result[result["additional"].notna()]

    assert overflow["entity_id"].nunique() == 1
    assert overflow["entity_id"].iloc[0] == _event_to_icon_id("waiting")


def test_overflow_icon_reads_as_a_count(overflow_positions):
    """By default the placeholder renders as '+ n more' text."""
    result = overflow_positions(step_snapshot_max=5, wrap_queues_at=5)
    overflow = result[result["additional"].notna()]

    assert overflow["icon"].str.contains("more").all()


def test_overflow_row_is_offset_within_its_row(overflow_positions):
    """The label is nudged towards the middle of the row it sits on."""
    result = overflow_positions(
        step_snapshot_max=5, wrap_queues_at=5, gap_between_entities=10
    )
    positions = positions_at(result, 20, "waiting")

    # Rank 6 would sit at x=400 on the wrapped row; the offset moves it back by
    # gap_between_entities * (wrap_queues_at / 2) = 10 * 2.5 = 25.
    assert positions[6.0] == (375.0, 305.0)


def test_step_snapshot_limit_gauges_render_a_bar(overflow_positions):
    """The gauge option replaces the text label with a bar."""
    result = overflow_positions(
        step_snapshot_max=5, wrap_queues_at=5, step_snapshot_limit_gauges=True
    )
    overflow = result[result["additional"].notna()]

    assert overflow["icon"].str.contains("█").any()


# --------------------------------------------------------------------------- #
# ascii_queue_icon
# --------------------------------------------------------------------------- #


def test_ascii_queue_icon_fills_proportionally():
    """Half the max count fills half the bar."""
    icon = ascii_queue_icon(icon="x", count=5, max_count=10, bar_length=10)

    assert icon.startswith("[" + "█" * 5 + "░" * 5 + "]")
    assert icon.endswith("+ 5 more")


def test_ascii_queue_icon_full_and_empty():
    assert ascii_queue_icon(icon="x", count=10, max_count=10, bar_length=4).startswith(
        "[████]"
    )
    assert ascii_queue_icon(icon="x", count=0, max_count=10, bar_length=4).startswith(
        "[░░░░]"
    )


def test_ascii_queue_icon_handles_zero_max_without_dividing_by_zero():
    assert ascii_queue_icon(icon="x", count=0, max_count=0, bar_length=4) == "░░░░"


def test_ascii_queue_icon_returns_empty_for_nan_count():
    assert ascii_queue_icon(icon="x", count=np.nan, max_count=10) == ""


def test_ascii_queue_icon_count_only():
    assert ascii_queue_icon(icon="x", count=7, max_count=10, count_only=True) == "7"


# --------------------------------------------------------------------------- #
# Deprecated parameter
# --------------------------------------------------------------------------- #


def test_minimize_output_df_warns_and_is_inert(
    simple_queue_log, basic_event_position_df
):
    """The parameter never worked; passing it now says so explicitly.

    Regression test: the implementing loop called .drop() without assigning the
    result, so the documented behaviour was a silent no-op.
    """
    reshaped = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )

    with pytest.warns(DeprecationWarning, match="never had any effect"):
        minimized = generate_animation_df(
            reshaped, basic_event_position_df, minimize_output_df=True
        )

    default = generate_animation_df(reshaped, basic_event_position_df)

    # Passing it changes nothing about the output.
    pd.testing.assert_frame_equal(minimized, default)


def test_no_deprecation_warning_when_parameter_not_passed(
    simple_queue_log, basic_event_position_df, recwarn
):
    """Users on the default must not be nagged about a parameter they never used."""
    reshaped = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )

    generate_animation_df(reshaped, basic_event_position_df)

    assert [w for w in recwarn if issubclass(w.category, DeprecationWarning)] == []
