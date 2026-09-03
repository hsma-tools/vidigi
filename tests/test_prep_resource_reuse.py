"""Positioning when one resource unit is released and re-acquired by later entities.

``generate_animation_df`` places a ``resource_use`` row purely by arithmetic on its
``resource_id`` (no join, no per-entity state), so a unit that entity 1 holds and then
entity 3 (and later entity 4) holds must land every time at the same spot. There was no
value-level test pinning this - the ``resource_log`` fixture only ever gives an id to one
entity.

The second test pins the interaction with the presence window from the healthy side: a
``resource_use`` that post-dates the entity's ``queue`` row keeps it drawn at the resource
for the expected snapshots. The malformed mirror of this - a ``depart`` that *precedes* the
``resource_use`` row, which is what a ``with store.request(...):`` block that forgets
``yield req`` produces - is what made entities skip straight to the exit in
``examples/feat_synchronised_traces``; ``test_resources_context_manager_guard.py`` covers
stopping that at the source, and the last test here pins the downstream symptom.
"""

import pandas as pd
import pytest

from vidigi.prep import generate_animation_df, reshape_for_animations
from vidigi.utils import EventPosition, create_event_position_df


def _rows(*specs):
    return pd.DataFrame(
        [
            {"time": t, "entity_id": e, "event_type": et, "event": ev}
            for t, e, et, ev in specs
        ]
    )


@pytest.fixture
def event_positions():
    return create_event_position_df(
        [
            EventPosition(event="arrival", x=50, y=300, label="Arrival"),
            EventPosition(event="waiting", x=400, y=275, label="Waiting"),
            EventPosition(
                event="treatment_begins",
                x=400,
                y=175,
                label="Being Treated",
                resource="n_cubicles",
            ),
            EventPosition(event="depart", x=270, y=70, label="Exit"),
        ]
    )


@pytest.fixture
def sequential_reuse_log():
    """Two units. Entity 1 -> unit 1 (0-20), entity 3 -> unit 1 (20-40), entity 4 -> unit 1
    (40-55); entity 2 holds unit 2 throughout. Unit 1 is reused twice."""
    log = _rows(
        (0, 1, "arrival_departure", "arrival"),
        (0, 1, "queue", "waiting"),
        (5, 1, "resource_use", "treatment_begins"),
        (20, 1, "resource_use_end", "treatment_ends"),
        (20, 1, "arrival_departure", "depart"),
        (0, 2, "arrival_departure", "arrival"),
        (0, 2, "queue", "waiting"),
        (5, 2, "resource_use", "treatment_begins"),
        (45, 2, "resource_use_end", "treatment_ends"),
        (45, 2, "arrival_departure", "depart"),
        (2, 3, "arrival_departure", "arrival"),
        (2, 3, "queue", "waiting"),
        (20, 3, "resource_use", "treatment_begins"),
        (40, 3, "resource_use_end", "treatment_ends"),
        (40, 3, "arrival_departure", "depart"),
        (3, 4, "arrival_departure", "arrival"),
        (3, 4, "queue", "waiting"),
        (40, 4, "resource_use", "treatment_begins"),
        (55, 4, "resource_use_end", "treatment_ends"),
        (55, 4, "arrival_departure", "depart"),
    )
    log["resource_id"] = [
        None, None, 1, 1, None,
        None, None, 2, 2, None,
        None, None, 1, 1, None,
        None, None, 1, 1, None,
    ]
    return log


def test_reused_unit_places_every_holder_at_the_same_slot(
    sequential_reuse_log, event_positions
):
    reshaped = reshape_for_animations(
        sequential_reuse_log, every_x_time_units=5, limit_duration=60
    )
    result = generate_animation_df(reshaped, event_positions)

    treated = result[result["event"] == "treatment_begins"]

    # No holder is ever left without a drawable position.
    assert not treated["x_final"].isna().any()
    assert not treated["y_final"].isna().any()

    # The whole mapping, not a sampled pair: unit 1 is the same slot for entities 1, 3 and 4;
    # unit 2 its own slot for entity 2. Anchor for treatment_begins is (400, 175);
    # gap_between_resources=10, wrap on -> unit 1 -> (400, 175), unit 2 -> (390, 175).
    slot_by_entity = {
        int(row["entity_id"]): (row["resource_id"], row["x_final"], row["y_final"])
        for _, row in treated.drop_duplicates("entity_id").iterrows()
    }
    assert slot_by_entity == {
        1: (1.0, 400.0, 175.0),
        2: (2.0, 390.0, 175.0),
        3: (1.0, 400.0, 175.0),
        4: (1.0, 400.0, 175.0),
    }

    # And it does not drift frame to frame for any of them.
    for entity_id in (1, 2, 3, 4):
        held = treated[treated["entity_id"] == entity_id]
        assert held["x_final"].nunique() == 1
        assert held["y_final"].nunique() == 1


def test_no_entity_sits_at_the_exit_anchor_while_in_service(
    sequential_reuse_log, event_positions
):
    reshaped = reshape_for_animations(
        sequential_reuse_log, every_x_time_units=5, limit_duration=60
    )
    result = generate_animation_df(reshaped, event_positions)

    in_service = result[result["event"] == "treatment_begins"]
    # (270, 70) is the 'depart' anchor - a treatment row landing there would be the
    # "skips straight to the exit" bug.
    assert not ((in_service["x_final"] == 270.0) & (in_service["y_final"] == 70.0)).any()


def test_resource_use_after_the_queue_row_keeps_the_entity_at_the_resource(
    sequential_reuse_log, event_positions
):
    """Healthy ordering: entity 3 queues at t=2, is granted unit 1 at t=20, ends at t=40.
    It must be shown at ``treatment_begins`` for every snapshot in between."""
    reshaped = reshape_for_animations(
        sequential_reuse_log, every_x_time_units=5, limit_duration=60
    )
    result = generate_animation_df(reshaped, event_positions)

    entity_3 = result[result["entity_id"] == 3]
    treated_at = sorted(
        entity_3[entity_3["event"] == "treatment_begins"]["snapshot_time"].tolist()
    )
    assert treated_at == [20, 25, 30, 35]
    # ... and it is 'waiting', not already gone, before it is granted the unit.
    waiting_at = sorted(
        entity_3[entity_3["event"] == "waiting"]["snapshot_time"].tolist()
    )
    assert waiting_at == [5, 10, 15]


def test_depart_before_resource_use_hides_the_treatment_snapshots(event_positions):
    """Pinned current behaviour (not a verified ideal): if ``depart`` is logged *before* the
    ``resource_use`` row - what a ``with store.request(...):`` block missing ``yield req``
    produces - the entity's presence window ends at the departure, so every treatment
    snapshot falls outside it and the entity is only ever drawn waiting, then exiting.
    Fixing the misuse is done in the store (see
    ``test_resources_context_manager_guard.py``); if the pipeline is ever changed to also
    tolerate such logs, update this assertion.
    """
    log = _rows(
        (0, 1, "arrival_departure", "arrival"),
        (0, 1, "queue", "waiting"),
        (5, 1, "resource_use", "treatment_begins"),
        (30, 1, "resource_use_end", "treatment_ends"),
        (30, 1, "arrival_departure", "depart"),
        (2, 2, "arrival_departure", "arrival"),
        (2, 2, "queue", "waiting"),
        (10, 2, "arrival_departure", "depart"),  # departs before its resource_use
        (20, 2, "resource_use", "treatment_begins"),  # phantom, post-departure
    )
    log["resource_id"] = [None, None, 1, 1, None, None, None, None, 1]

    reshaped = reshape_for_animations(log, every_x_time_units=5, limit_duration=40)
    result = generate_animation_df(reshaped, event_positions)

    entity_2 = result[result["entity_id"] == 2]
    assert set(entity_2["event"]) <= {"waiting", "depart"}
    assert "treatment_begins" not in set(entity_2["event"])
