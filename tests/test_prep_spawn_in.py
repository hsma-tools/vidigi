"""Tests for `spawn_in_from_arrival` (`generate_animation_df`) - see issue #199.

A genuinely new entity otherwise flies in from the plot's top-left corner the
first frame it is drawn (the same Plotly `text`-trace behaviour that
`step_snapshot_reveal_pop_in` addresses for reveals - see
`test_prep_overflow_reveal.py`). `spawn_in_from_arrival` is the arrival-side
mirror of the synthetic `depart` step: the entity is given a visible row at the
`event_position_df` `"arrival"` anchor one snapshot before its first real
position (so Plotly animates it moving from there), plus an invisible
placeholder-glyph phantom the snapshot before that (so the spawn row itself has
nothing to fly in from).
"""

import pandas as pd
import pytest

from vidigi.prep import generate_animation_df, reshape_for_animations
from vidigi.utils import PHANTOM_ICON, EventPosition, create_event_position_df

EVERY = 10


def _rows(*specs):
    """Build an event log from (time, entity_id, event_type, event) tuples."""
    return pd.DataFrame(
        [
            {"time": t, "entity_id": e, "event_type": et, "event": ev}
            for t, e, et, ev in specs
        ]
    )


@pytest.fixture
def spawn_log():
    """Four entities join one queue and leave 30 units later.

    Arrival times are chosen for their grid position (snapshots every 10 units,
    grid slot = time / 10):

    * entity 1 arrives at t=0  -> first drawn at grid slot 0 (present at window
      open, no earlier slot to spawn from)
    * entity 2 arrives at t=5  -> first drawn at grid slot 1 (only one earlier
      slot, not the two a spawn row + its phantom need)
    * entity 3 arrives at t=15 -> first drawn at grid slot 2 (exactly enough)
    * entity 4 arrives at t=45 -> first drawn at grid slot 5 (comfortably enough)
    """
    specs = []
    for entity_id, arrival_t in ((1, 0), (2, 5), (3, 15), (4, 45)):
        specs.append((arrival_t, entity_id, "arrival_departure", "arrival"))
        specs.append((arrival_t, entity_id, "queue", "waiting"))
        specs.append((arrival_t + 30, entity_id, "arrival_departure", "depart"))
    return _rows(*specs)


@pytest.fixture
def spawn_positions():
    return create_event_position_df(
        [
            EventPosition(event="arrival", x=15, y=300, label="Entrance"),
            EventPosition(event="waiting", x=400, y=275, label="Waiting"),
            EventPosition(event="depart", x=270, y=70, label="Exit"),
        ]
    )


@pytest.fixture
def no_arrival_positions():
    return create_event_position_df(
        [
            EventPosition(event="waiting", x=400, y=275, label="Waiting"),
            EventPosition(event="depart", x=270, y=70, label="Exit"),
        ]
    )


def _reshaped(log):
    return reshape_for_animations(
        log, every_x_time_units=EVERY, limit_duration=100, step_snapshot_max=5
    )


def _entity_rows(result, entity_id):
    return (
        result[result["entity_id"] == entity_id]
        .sort_values("snapshot_time")
        .reset_index(drop=True)
    )


# --------------------------------------------------------------------------- #
# Default on; `False` restores the pre-feature behaviour
# --------------------------------------------------------------------------- #


def test_default_spawns_in(spawn_log, spawn_positions):
    """`spawn_in_from_arrival` defaults to True, so an eligible arrival gets its
    synthetic spawn rows with no argument passed."""
    reshaped = _reshaped(spawn_log)
    result = generate_animation_df(
        reshaped, spawn_positions, step_snapshot_max=5, wrap_queues_at=None
    )
    rows = _entity_rows(result, 4.0)
    assert (rows["event"] == "arrival").any()
    assert rows["_phantom"].sum() == 1


def test_explicit_false_restores_pre_feature_behaviour(spawn_log, spawn_positions):
    reshaped = _reshaped(spawn_log)
    explicit_false = generate_animation_df(
        reshaped.copy(),
        spawn_positions,
        step_snapshot_max=5,
        wrap_queues_at=None,
        spawn_in_from_arrival=False,
    )
    # No synthetic rows, and the column the phantom machinery adds is absent
    # unless something actually asked for it.
    assert "_phantom" not in explicit_false.columns
    assert not (explicit_false["event"] == "arrival").any()

    default_on = generate_animation_df(
        reshaped.copy(), spawn_positions, step_snapshot_max=5, wrap_queues_at=None
    )
    # The default really did add rows the opt-out drops.
    assert len(default_on) > len(explicit_false)


def test_no_arrival_anchor_is_noop(spawn_log, no_arrival_positions):
    """With no `"arrival"` row in `event_position_df` there is no spawn point,
    so the default-on behaviour can do nothing - output must match opting out."""
    reshaped = _reshaped(spawn_log)
    off = generate_animation_df(
        reshaped.copy(),
        no_arrival_positions,
        step_snapshot_max=5,
        wrap_queues_at=None,
        spawn_in_from_arrival=False,
    )
    default_on = generate_animation_df(
        reshaped.copy(),
        no_arrival_positions,
        step_snapshot_max=5,
        wrap_queues_at=None,
    )
    # `default_on` gains an all-False `_phantom` column but no rows.
    assert default_on.drop(columns=["_phantom"], errors="ignore").equals(off)
    assert not default_on.get("_phantom", pd.Series(dtype=bool)).any()


# --------------------------------------------------------------------------- #
# Spawn-in behaviour
# --------------------------------------------------------------------------- #


def test_new_arrival_gets_spawn_row_then_phantom(spawn_log, spawn_positions):
    reshaped = _reshaped(spawn_log)
    result = generate_animation_df(
        reshaped,
        spawn_positions,
        step_snapshot_max=5,
        wrap_queues_at=None,
        spawn_in_from_arrival=True,
    )

    rows = _entity_rows(result, 4.0)
    first_real = rows[(~rows["_phantom"]) & (rows["event"] == "waiting")].iloc[0]
    real_icon = first_real["icon"]

    # Entity 4 arrives at t=45 -> first real row at snapshot 50 (grid slot 5).
    assert first_real["snapshot_time"] == 50

    # Exactly one phantom, one visible spawn row, both at the arrival anchor.
    spawn = rows[(rows["snapshot_time"] == 40) & (~rows["_phantom"])].iloc[0]
    phantom = rows[rows["_phantom"]].iloc[0]

    assert len(rows[rows["_phantom"]]) == 1
    assert phantom["snapshot_time"] == 30
    assert phantom["icon"] == PHANTOM_ICON
    assert (phantom["x_final"], phantom["y_final"]) == (15, 300)

    assert spawn["snapshot_time"] == 40
    assert spawn["icon"] == real_icon
    assert spawn["event"] == "arrival"
    assert spawn["event_type"] == "arrival_departure"
    assert spawn["label"] == "Entrance"
    assert (spawn["x_final"], spawn["y_final"]) == (15, 300)

    # The real first row is untouched - still one gap back from the queue anchor
    # (rank 1, left-building queue: 400 - 1 * 10).
    assert first_real["x_final"] == 390


def test_entity_present_when_window_opens_keeps_flyin(spawn_log, spawn_positions):
    """Entities at grid slots 0 and 1 have fewer than the two earlier slots a
    spawn row and its phantom need, so they are left to fly in."""
    reshaped = _reshaped(spawn_log)
    result = generate_animation_df(
        reshaped,
        spawn_positions,
        step_snapshot_max=5,
        wrap_queues_at=None,
        spawn_in_from_arrival=True,
    )

    for entity_id in (1.0, 2.0):
        rows = _entity_rows(result, entity_id)
        assert not rows["_phantom"].any()
        assert not (rows["event"] == "arrival").any()


def test_spawn_row_at_exactly_two_slots_in(spawn_log, spawn_positions):
    """Entity 3 arrives at t=15 -> first real row at grid slot 2, the minimum
    that still leaves room for the spawn row (slot 1) and its phantom (slot 0)."""
    reshaped = _reshaped(spawn_log)
    result = generate_animation_df(
        reshaped,
        spawn_positions,
        step_snapshot_max=5,
        wrap_queues_at=None,
        spawn_in_from_arrival=True,
    )

    rows = _entity_rows(result, 3.0)
    synthetic = rows[(rows["event"] == "arrival") | rows["_phantom"]]
    assert sorted(synthetic["snapshot_time"]) == [0, 10]
    assert list(synthetic.sort_values("snapshot_time")["_phantom"]) == [True, False]


def test_no_new_frames_created(spawn_log, spawn_positions):
    """Synthetic rows land on existing snapshot slots - the set of frame times
    is unchanged."""
    reshaped = _reshaped(spawn_log)
    off = generate_animation_df(
        reshaped.copy(),
        spawn_positions,
        step_snapshot_max=5,
        wrap_queues_at=None,
        spawn_in_from_arrival=False,
    )
    on = generate_animation_df(
        reshaped.copy(),
        spawn_positions,
        step_snapshot_max=5,
        wrap_queues_at=None,
        spawn_in_from_arrival=True,
    )
    assert set(on["snapshot_time"].dropna()) == set(off["snapshot_time"].dropna())


def test_no_entity_in_two_places_in_one_frame(spawn_log, spawn_positions):
    reshaped = _reshaped(spawn_log)
    result = generate_animation_df(
        reshaped,
        spawn_positions,
        step_snapshot_max=5,
        wrap_queues_at=None,
        spawn_in_from_arrival=True,
    )
    drawn = result[result["entity_id"].notna()]
    counts = drawn.groupby(["entity_id", "snapshot_time"]).size()
    assert (counts == 1).all()


# --------------------------------------------------------------------------- #
# Interaction with step_snapshot_reveal_pop_in
# --------------------------------------------------------------------------- #


@pytest.fixture
def reveal_and_arrival_positions():
    return create_event_position_df(
        [
            EventPosition(event="arrival", x=15, y=300, label="Entrance"),
            EventPosition(event="waiting", x=400, y=275, label="Waiting"),
            EventPosition(event="triage", x=250, y=175, label="Triage"),
            EventPosition(event="depart", x=270, y=70, label="Exit"),
        ]
    )


@pytest.fixture
def reveal_and_arrival_log():
    """Six entities queue on `waiting` from t=1..6 with `step_snapshot_max=3`, so
    ranks 4-6 are hidden. Entities 1-3 depart at t=50, revealing 4-6. A seventh
    entity arrives late, at t=35, into its own (empty) `triage` queue - a genuine
    new arrival, individually drawn, well inside the window."""
    specs = []
    for entity_id in range(1, 7):
        specs.append((entity_id, entity_id, "arrival_departure", "arrival"))
        specs.append((entity_id, entity_id, "queue", "waiting"))
    for entity_id in (1, 2, 3):
        specs.append((50, entity_id, "arrival_departure", "depart"))
    specs.append((35, 7, "arrival_departure", "arrival"))
    specs.append((35, 7, "queue", "triage"))
    for entity_id in (4, 5, 6, 7):
        specs.append((80, entity_id, "arrival_departure", "depart"))
    return _rows(*specs)


def test_spawn_and_pop_in_coexist(reveal_and_arrival_log, reveal_and_arrival_positions):
    reshaped = reshape_for_animations(
        reveal_and_arrival_log,
        every_x_time_units=EVERY,
        limit_duration=100,
        step_snapshot_max=3,
    )
    result = generate_animation_df(
        reshaped,
        reveal_and_arrival_positions,
        step_snapshot_max=3,
        wrap_queues_at=None,
        step_snapshot_reveal_pop_in=True,
        spawn_in_from_arrival=True,
    )

    # The late genuine arrival (entity 7) gets a spawn row + its phantom...
    entity_7 = _entity_rows(result, 7.0)
    assert (entity_7["event"] == "arrival").any()
    assert entity_7["_phantom"].sum() == 1

    # ...a revealed entity (entity 6 emerges when 1-3 leave at t=50) gets a
    # pop-in phantom at its queue position, not an arrival spawn row.
    entity_6 = _entity_rows(result, 6.0)
    assert not (entity_6["event"] == "arrival").any()
    phantoms_6 = entity_6[entity_6["_phantom"]]
    assert len(phantoms_6) == 1
    # Pop-in phantom sits at the queue anchor, not the arrival anchor.
    assert phantoms_6.iloc[0]["x_final"] != 15
