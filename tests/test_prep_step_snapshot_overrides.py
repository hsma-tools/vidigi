"""Per-event ``step_snapshot_max`` via ``step_snapshot_max_overrides``.

``step_snapshot_max`` caps how many entity icons are drawn per event per snapshot.
``step_snapshot_max_overrides`` lets one or more named events use a different cap
while every other event falls back to the scalar. The row-shedding itself happens
in ``reshape_for_animations``; ``generate_animation_df`` only consumes the caps to
place the ``+ n more`` overflow label.
"""

import numpy as np
import pandas as pd
import pytest

from vidigi.prep import generate_animation_df, reshape_for_animations
from vidigi.utils import EventPosition, create_event_position_df


def _two_queue_log(n_waiting=12, n_triage=8):
    """Entities in two separate queues, all present together at snapshot 20.

    ``waiting`` ids are 1..n_waiting, ``triage`` ids are 101..100+n_triage. Every
    entity arrives at t=1 and departs at t=101, so all are present at snapshot 20.
    """
    rows = []
    for entity_id in range(1, n_waiting + 1):
        rows.append((1, entity_id, "arrival_departure", "arrival"))
        rows.append((1, entity_id, "queue", "waiting"))
        rows.append((101, entity_id, "arrival_departure", "depart"))
    for entity_id in range(101, 101 + n_triage):
        rows.append((1, entity_id, "arrival_departure", "arrival"))
        rows.append((1, entity_id, "queue", "triage"))
        rows.append((101, entity_id, "arrival_departure", "depart"))
    return pd.DataFrame(
        [
            {"time": t, "entity_id": i, "event_type": et, "event": ev}
            for t, i, et, ev in rows
        ]
    )


@pytest.fixture
def two_queue_log():
    return _two_queue_log()


@pytest.fixture
def two_queue_positions():
    return create_event_position_df(
        [
            EventPosition(event="arrival", x=50, y=300, label="Arrival"),
            EventPosition(event="waiting", x=400, y=275, label="Waiting"),
            EventPosition(event="triage", x=400, y=175, label="Triage"),
            EventPosition(event="depart", x=270, y=70, label="Exit"),
        ]
    )


def _rank_map(reshaped, snapshot_time, event):
    """(entity_id -> rank) for one event at one snapshot."""
    rows = reshaped[
        (reshaped["snapshot_time"] == snapshot_time) & (reshaped["event"] == event)
    ]
    return {row["entity_id"]: row["rank"] for _, row in rows.iterrows()}


def _boundary_row(reshaped, snapshot_time, event):
    """(rank, additional) for the single overflow boundary row, or None."""
    rows = reshaped[
        (reshaped["snapshot_time"] == snapshot_time)
        & (reshaped["event"] == event)
        & (reshaped["additional"].notna())
    ]
    if rows.empty:
        return None
    assert len(rows) == 1
    return (rows["rank"].iloc[0], rows["additional"].iloc[0])


# --------------------------------------------------------------------------- #
# reshape_for_animations - the actual capping
# --------------------------------------------------------------------------- #


def test_each_event_capped_independently(two_queue_log):
    """With ``{"waiting": 8}`` and scalar 5, ``waiting`` keeps 8 icons + a
    boundary row and ``triage`` keeps 5 + a boundary row - asserted as the
    whole surviving mapping for both events, not sampled rows."""
    reshaped = reshape_for_animations(
        two_queue_log,
        every_x_time_units=10,
        limit_duration=30,
        step_snapshot_max=5,
        step_snapshot_max_overrides={"waiting": 8},
    )

    # waiting: ranks 1..8 individually, plus rank 9 (the boundary row, whose
    # entity id 9 survives here - it is relabelled later in generate_animation_df).
    assert _rank_map(reshaped, 20, "waiting") == {
        1.0: 1.0,
        2.0: 2.0,
        3.0: 3.0,
        4.0: 4.0,
        5.0: 5.0,
        6.0: 6.0,
        7.0: 7.0,
        8.0: 8.0,
        9.0: 9.0,
    }
    # Boundary row at rank 9 carries additional = 12 total - 9 = 3.
    assert _boundary_row(reshaped, 20, "waiting") == (9.0, 3.0)

    # triage: unlisted, so the scalar 5 applies. Ranks 1..5 individually, rank 6
    # is the boundary row carrying additional = 8 total - 6 = 2.
    assert _rank_map(reshaped, 20, "triage") == {
        101.0: 1.0,
        102.0: 2.0,
        103.0: 3.0,
        104.0: 4.0,
        105.0: 5.0,
        106.0: 6.0,
    }
    assert _boundary_row(reshaped, 20, "triage") == (6.0, 2.0)


def test_override_can_lift_an_event_above_the_scalar(two_queue_log):
    """A generous override shows a long queue in full (no boundary row) while
    the scalar still caps the other event."""
    reshaped = reshape_for_animations(
        two_queue_log,
        every_x_time_units=10,
        limit_duration=30,
        step_snapshot_max=5,
        step_snapshot_max_overrides={"waiting": 100},
    )

    waiting = reshaped[(reshaped["snapshot_time"] == 20) & (reshaped["event"] == "waiting")]
    assert len(waiting) == 12
    assert waiting["additional"].isna().all()

    triage = reshaped[(reshaped["snapshot_time"] == 20) & (reshaped["event"] == "triage")]
    assert len(triage) == 6  # 5 shown + 1 boundary row
    assert triage["additional"].notna().sum() == 1


def test_none_is_a_noop(two_queue_log, two_queue_positions):
    """``step_snapshot_max_overrides=None`` is byte-identical to omitting it,
    through both pipeline stages - the guarantee this is not a breaking change."""
    kw = dict(every_x_time_units=10, limit_duration=30, step_snapshot_max=5)

    omitted = reshape_for_animations(two_queue_log, **kw)
    explicit = reshape_for_animations(
        two_queue_log, step_snapshot_max_overrides=None, **kw
    )
    pd.testing.assert_frame_equal(omitted, explicit)

    gen_kw = dict(wrap_queues_at=5, step_snapshot_max=5)
    pd.testing.assert_frame_equal(
        generate_animation_df(omitted, two_queue_positions, **gen_kw),
        generate_animation_df(
            explicit, two_queue_positions, step_snapshot_max_overrides=None, **gen_kw
        ),
    )


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def test_non_mapping_raises(two_queue_log):
    with pytest.raises(TypeError, match="must be a mapping"):
        reshape_for_animations(
            two_queue_log,
            every_x_time_units=10,
            limit_duration=30,
            step_snapshot_max_overrides=[("waiting", 8)],
        )


def test_float_value_warns_and_rounds(two_queue_log):
    with pytest.warns(UserWarning, match="rounding to nearest integer"):
        reshaped = reshape_for_animations(
            two_queue_log,
            every_x_time_units=10,
            limit_duration=30,
            step_snapshot_max=5,
            step_snapshot_max_overrides={"waiting": 8.4},
        )
    # 8.4 -> 8, so rank 9 is still the boundary row.
    waiting = reshaped[(reshaped["snapshot_time"] == 20) & (reshaped["event"] == "waiting")]
    assert waiting["additional"].notna().sum() == 1
    assert float(waiting.loc[waiting["additional"].notna(), "rank"].iloc[0]) == 9.0


def test_unknown_event_key_warns(two_queue_log):
    with pytest.warns(UserWarning, match="match no event"):
        reshape_for_animations(
            two_queue_log,
            every_x_time_units=10,
            limit_duration=30,
            step_snapshot_max_overrides={"waitng": 8},
        )


# --------------------------------------------------------------------------- #
# generate_animation_df - overflow label placement
# --------------------------------------------------------------------------- #


def test_overflow_label_sits_on_the_per_event_boundary_rank(
    two_queue_log, two_queue_positions
):
    """The ``+ n more`` label is nudged towards the middle of its wrapped row.
    Its rank is ``cap + 1`` for that event: 11 for ``waiting`` (override 10),
    6 for ``triage`` (scalar 5)."""
    reshaped = reshape_for_animations(
        two_queue_log,
        every_x_time_units=10,
        limit_duration=30,
        step_snapshot_max=5,
        step_snapshot_max_overrides={"waiting": 10},
    )
    result = generate_animation_df(
        reshaped,
        two_queue_positions,
        wrap_queues_at=5,
        gap_between_entities=10,
        gap_between_queue_rows=30,
        step_snapshot_max=5,
        step_snapshot_max_overrides={"waiting": 10},
    )

    def overflow_row(event):
        rows = result[(result["event"] == event) & (result["snapshot_time"] == 20)]
        return rows.loc[rows["additional"].notna()].iloc[0]

    # waiting: boundary rank 11 -> row index floor((11-1)/5) = 2, base x steps
    # back to 400 - sign(left) nudged forward by 10 * (5/2) = 25 -> 375.
    w = overflow_row("waiting")
    assert w["rank"] == 11.0
    assert (w["x_final"], w["y_final"]) == (375.0, 275.0 + 2 * 30)

    # triage: boundary rank 6 -> row index 1, same nudge -> 375 on the second row.
    t = overflow_row("triage")
    assert t["rank"] == 6.0
    assert (t["x_final"], t["y_final"]) == (375.0, 175.0 + 1 * 30)


def test_end_to_end_through_animate_activity_log(two_queue_log, two_queue_positions):
    """A mixed dict reaches both pipeline stages: an event with a low override
    shows a ``+ n more`` label, a generously-overridden event does not."""
    from vidigi.animation import animate_activity_log

    fig = animate_activity_log(
        two_queue_log,
        event_position_df=two_queue_positions,
        every_x_time_units=10,
        limit_duration=30,
        step_snapshot_max=5,
        step_snapshot_max_overrides={"waiting": 100},
        wrap_queues_at=5,
    )

    def _texts(trace):
        return [] if trace.text is None else list(np.atleast_1d(trace.text))

    all_text = " ".join(
        str(t) for frame in fig.frames for trace in frame.data for t in _texts(trace)
    )
    assert "more" in all_text  # triage overflowed at the scalar cap of 5
    # waiting had 12 entities and a cap of 100, so no overflow label for it -
    # every 'more' label present belongs to triage.
