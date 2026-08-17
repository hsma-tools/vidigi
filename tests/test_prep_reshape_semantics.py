"""Value-level tests for ``reshape_for_animations``.

The existing ``test_reshape_for_animations.py`` covers shapes, column presence
and sort order. These tests assert the *contents* of each snapshot: who is
present, which event they are shown at, and in what queue order. Errors in this
function are the "entity shown in the wrong place" class of animation bug, which
shape assertions cannot detect.
"""

import numpy as np
import pandas as pd
import pytest

from vidigi.prep import reshape_for_animations


def entities_at(result, snapshot_time):
    """Entity IDs present at a snapshot, ignoring the empty-snapshot filler rows."""
    rows = result[result["snapshot_time"] == snapshot_time]
    return set(rows["entity_id"].dropna().astype(int))


def event_at(result, snapshot_time, entity_id):
    """The single event an entity is shown at for a given snapshot."""
    rows = result[
        (result["snapshot_time"] == snapshot_time)
        & (result["entity_id"] == entity_id)
    ]
    assert len(rows) == 1, (
        f"Entity {entity_id} should appear exactly once at snapshot "
        f"{snapshot_time}, found {len(rows)} rows"
    )
    return rows.iloc[0]["event"]


# --------------------------------------------------------------------------- #
# Snapshot membership
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "snapshot_time, expected_entities",
    [
        (0, {1}),
        (10, {1, 2}),
        (20, {1, 2, 3}),
        (30, {2, 3}),
        (40, {3}),
        (50, set()),
    ],
)
def test_snapshot_membership_is_exact(
    simple_queue_log, snapshot_time, expected_entities
):
    """An entity is present from its arrival snapshot up to its departure snapshot.

    Entity 1 arrives at 0 and departs at 25, so it is present at 0, 10 and 20 but
    not at 30. Entity 3 arrives at 12 and departs at 45, so it first appears at
    snapshot 20.
    """
    result = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    # Exclude the exit rows, which are added after the departure snapshot.
    result = result[result["event_type"] != "exit"]

    assert entities_at(result, snapshot_time) == expected_entities


def test_entity_absent_before_arrival(simple_queue_log):
    """Entity 3 arrives at t=12 and so must not appear at snapshot 10."""
    result = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )

    assert 3 not in entities_at(result, 10)
    assert 3 in entities_at(result, 20)


# --------------------------------------------------------------------------- #
# Which event an entity is shown at
# --------------------------------------------------------------------------- #


def test_most_recent_event_wins(resource_log):
    """An entity is shown at its latest event at or before the snapshot time.

    Entity 1 queues at t=0, starts treatment at t=10 and finishes at t=30, so it
    is 'waiting' at snapshot 0 and 'treatment_begins' at snapshot 20.
    """
    result = reshape_for_animations(
        resource_log, every_x_time_units=10, limit_duration=50
    )

    assert event_at(result, 0, 1) == "waiting"
    assert event_at(result, 20, 1) == "treatment_begins"


def test_event_at_exact_boundary_is_included(resource_log):
    """An event at exactly the snapshot time counts as having happened.

    Entity 1 starts treatment at t=10, so at snapshot 10 it is already being
    treated rather than still waiting.
    """
    result = reshape_for_animations(
        resource_log, every_x_time_units=10, limit_duration=50
    )

    assert event_at(result, 10, 1) == "treatment_begins"


def test_entity_appears_at_only_one_event_per_snapshot(resource_log):
    """The animation assumes an entity occupies a single position at a time."""
    result = reshape_for_animations(
        resource_log, every_x_time_units=10, limit_duration=50
    )
    tracked = result[result["entity_id"].notnull()]

    duplicates = tracked.groupby(["snapshot_time", "entity_id"]).size()
    offenders = duplicates[duplicates > 1]

    assert offenders.empty, (
        f"Entities appearing in more than one place at a single snapshot:\n{offenders}"
    )


# --------------------------------------------------------------------------- #
# Queue ordering
# --------------------------------------------------------------------------- #


def test_rank_follows_order_of_joining_the_queue(simple_queue_log):
    """Rank is the visual queue position: first to join the event is rank 1."""
    result = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    snapshot = result[
        (result["snapshot_time"] == 20) & (result["event"] == "waiting")
    ]

    ranks = dict(zip(snapshot["entity_id"], snapshot["rank"]))

    assert ranks == {1.0: 1.0, 2.0: 2.0, 3.0: 3.0}


def test_queue_closes_up_when_an_entity_leaves(simple_queue_log):
    """Entity 1 departs at t=25, so entity 2 becomes rank 1 at snapshot 30."""
    result = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    snapshot = result[
        (result["snapshot_time"] == 30) & (result["event"] == "waiting")
    ]

    ranks = dict(zip(snapshot["entity_id"], snapshot["rank"]))

    assert ranks == {2.0: 1.0, 3.0: 2.0}


# --------------------------------------------------------------------------- #
# Empty snapshots and exit steps
# --------------------------------------------------------------------------- #


def test_empty_snapshots_are_preserved(simple_queue_log):
    """Snapshots with nobody present keep a placeholder row.

    Without this the animation timeline would skip those frames, making the
    simulation appear to jump forwards in time.
    """
    result = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )

    expected_snapshots = {0, 10, 20, 30, 40, 50}
    assert set(result["snapshot_time"].unique()) == expected_snapshots

    # Nobody is in the system at 50 - entity 3 departs at 45 - so that snapshot
    # exists only as a placeholder row alongside entity 3's exit step.
    assert entities_at(result[result["event_type"] != "exit"], 50) == set()
    assert result["snapshot_time"].isin([50]).any()


def test_exit_step_added_one_interval_after_last_appearance(simple_queue_log):
    """Every entity gets a visible 'depart' step rather than vanishing."""
    result = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=50
    )
    exits = result[result["event_type"] == "exit"]

    assert set(exits["event"]) == {"depart"}
    # Entity 1 is last seen at snapshot 20, entity 2 at 30, entity 3 at 40.
    assert dict(zip(exits["entity_id"], exits["snapshot_time"])) == {
        1.0: 30,
        2.0: 40,
        3.0: 50,
    }


def test_exit_step_suppressed_beyond_limit_duration(simple_queue_log):
    """An exit step that would fall past the run end is dropped, not clamped."""
    result = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=40
    )
    exits = result[result["event_type"] == "exit"]

    # Entity 3 is last seen at snapshot 40, so its exit at 50 is beyond the limit.
    assert 3.0 not in set(exits["entity_id"])
    assert result["snapshot_time"].max() <= 40


# --------------------------------------------------------------------------- #
# step_snapshot_max
# --------------------------------------------------------------------------- #


def test_step_snapshot_max_caps_displayed_entities(overflow_queue_log):
    """Ranks above the cap are dropped, leaving one boundary row to stand in."""
    result = reshape_for_animations(
        overflow_queue_log,
        every_x_time_units=10,
        limit_duration=30,
        step_snapshot_max=5,
    )
    snapshot = result[
        (result["snapshot_time"] == 20) & (result["event"] == "waiting")
    ]

    # 12 entities are queued, but only ranks 1-6 survive: 1-5 are displayed and
    # rank 6 becomes the "+ x more" placeholder.
    assert sorted(snapshot["rank"]) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert set(snapshot["entity_id"]) == {1.0, 2.0, 3.0, 4.0, 5.0, 6.0}


def test_only_boundary_row_carries_additional_count(overflow_queue_log):
    """`additional` marks the single row that is rendered as the overflow label."""
    result = reshape_for_animations(
        overflow_queue_log,
        every_x_time_units=10,
        limit_duration=30,
        step_snapshot_max=5,
    )
    snapshot = result[
        (result["snapshot_time"] == 20) & (result["event"] == "waiting")
    ]
    with_additional = snapshot[snapshot["additional"].notna()]

    assert len(with_additional) == 1
    assert with_additional.iloc[0]["rank"] == 6.0

    # NOTE: `additional` is computed as (max rank - boundary rank) = 12 - 6 = 6,
    # so the label reads "+ 6 more" while ranks 6-12 (seven entities) are not
    # individually drawn. This pins current behaviour; whether the intended
    # reading is "6 more after this one" or a genuine off-by-one is an open
    # question and deliberately not changed here.
    assert with_additional.iloc[0]["additional"] == 6.0


def test_resource_use_events_are_not_capped(resource_log):
    """Resource use is excluded from the snapshot cap.

    Resource positions are driven by resource_id rather than queue order, so
    capping them would blank out occupied resources.
    """
    result = reshape_for_animations(
        resource_log,
        every_x_time_units=10,
        limit_duration=50,
        step_snapshot_max=1,
    )
    treated = result[result["event"] == "treatment_begins"]

    # Both entities are treated even though step_snapshot_max is 1.
    assert set(treated["entity_id"]) == {1.0, 2.0}
    # No row was turned into an overflow placeholder. The column is dropped
    # entirely when nothing anywhere in the log was capped.
    if "additional" in result.columns:
        assert treated["additional"].isna().all()


# --------------------------------------------------------------------------- #
# Custom column names
# --------------------------------------------------------------------------- #


def test_custom_event_type_column_used_for_exit_rows(simple_queue_log):
    """Exit rows must be written to the caller's event type column.

    Regression test: these rows previously went to a literal "event_type"
    column, so a log using a custom name ended up with two type columns and NaN
    event types on every exit row.
    """
    renamed = simple_queue_log.rename(columns={"event_type": "category"})

    result = reshape_for_animations(
        renamed, event_type_col_name="category", every_x_time_units=10, limit_duration=50
    )

    assert "event_type" not in result.columns
    assert "exit" in set(result["category"].dropna())
    assert result.loc[result["event"] == "depart", "category"].notna().all()


def test_all_custom_column_names_together():
    """The four column name arguments work in combination."""
    df = pd.DataFrame(
        {
            "t": [0, 0, 20, 5, 5, 25],
            "patient": [1, 1, 1, 2, 2, 2],
            "category": [
                "arrival_departure",
                "queue",
                "arrival_departure",
                "arrival_departure",
                "queue",
                "arrival_departure",
            ],
            "action": ["arrival", "waiting", "depart", "arrival", "waiting", "depart"],
        }
    )

    result = reshape_for_animations(
        df,
        time_col_name="t",
        entity_col_name="patient",
        event_type_col_name="category",
        event_col_name="action",
        every_x_time_units=10,
        limit_duration=30,
    )

    assert {"t", "patient", "category", "action"} <= set(result.columns)
    assert set(result["patient"].dropna()) == {1.0, 2.0}
    assert "exit" in set(result["category"].dropna())


# --------------------------------------------------------------------------- #
# Degenerate and edge-case logs
# --------------------------------------------------------------------------- #


def test_log_with_no_departures_still_animates(no_departure_log):
    """A run where nobody has left yet should animate, not crash.

    Regression test: with no 'depart' events the pivoted log had no depart
    column, every snapshot was silently emptied, and the function then died with
    an opaque KeyError on 'entity_id'.
    """
    result = reshape_for_animations(
        no_departure_log, every_x_time_units=10, limit_duration=30
    )

    assert set(result["entity_id"].dropna()) == {1.0, 2.0}
    # Both entities are still present at the final snapshot.
    assert entities_at(result[result["event_type"] != "exit"], 30) == {1, 2}


def test_log_with_no_arrivals_raises_informative_error(simple_queue_log):
    """Without arrivals there is no way to tell who is in the system."""
    queue_only = simple_queue_log[
        simple_queue_log["event_type"] != "arrival_departure"
    ]

    with pytest.raises(ValueError, match="No 'arrival' events"):
        reshape_for_animations(queue_only, every_x_time_units=10, limit_duration=30)


def test_limit_duration_none_uses_max_time_in_log(simple_queue_log):
    """`None` falls back to the last event time, with a warning.

    Regression test: `None` was rejected by the integer-coercion decorator
    before the function's own handling could run, and that handling would itself
    have raised a KeyError by reading a column consumed by the pivot.
    """
    # Latest event in the log is entity 3 departing at t=45, so the limit
    # resolves to 45 and the warning says so.
    with pytest.warns(UserWarning, match="has been set to 45"):
        result = reshape_for_animations(simple_queue_log, every_x_time_units=10,
                                        limit_duration=None)

    explicit = reshape_for_animations(
        simple_queue_log, every_x_time_units=10, limit_duration=45
    )
    pd.testing.assert_frame_equal(result, explicit)
    assert set(result["entity_id"].dropna()) == {1.0, 2.0, 3.0}


def test_single_entity_log(simple_queue_log):
    """A log with one entity is a valid, if minimal, animation."""
    one = simple_queue_log[simple_queue_log["entity_id"] == 1]

    result = reshape_for_animations(one, every_x_time_units=10, limit_duration=50)

    assert set(result["entity_id"].dropna()) == {1.0}
    assert "exit" in set(result["event_type"].dropna())


def test_non_integer_every_x_time_units_warns_and_rounds(simple_queue_log):
    """Float intervals are rounded rather than silently producing odd snapshots."""
    with pytest.warns(UserWarning, match="every_x_time_units"):
        result = reshape_for_animations(
            simple_queue_log, every_x_time_units=10.4, limit_duration=50
        )

    assert set(result["snapshot_time"].unique()) == {0, 10, 20, 30, 40, 50}
