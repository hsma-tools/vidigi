"""Tests for `vidigi.analysis.resource_occupancy_over_time`."""

import pytest

from vidigi.analysis import resource_occupancy_over_time
from vidigi.logging import EventLogger, TrialLogger


def _trial_df(loggers):
    return TrialLogger(loggers).to_dataframe()


def test_matches_the_hand_computed_step_function(resource_use_loggers):
    """Full arrays for both runs, at every_x_time_units=5 - not two sampled
    points. Hand-computed from the fixture: run 1 has unit 1 busy [0, 10) and
    unit 2 busy [0, 5), so occupancy is 2, then 1 (unit 2 frees exactly at
    t=5, so is not counted there - half-open), then 0. Run 2 has unit 2 busy
    [0, 20) and unit 3 busy [5, 15)."""
    occupancy = resource_occupancy_over_time(
        _trial_df(resource_use_loggers), every_x_time_units=5, limit_duration=20
    )

    run1 = occupancy[occupancy["run_number"] == 1].sort_values("snapshot_time")
    run2 = occupancy[occupancy["run_number"] == 2].sort_values("snapshot_time")

    assert list(run1["snapshot_time"]) == [0, 5, 10, 15, 20]
    assert list(run1["count"]) == [2, 1, 0, 0, 0]
    assert list(run2["snapshot_time"]) == [0, 5, 10, 15, 20]
    assert list(run2["count"]) == [1, 2, 2, 1, 0]
    assert (occupancy["event"] == "treatment_begins").all()


def test_unclosed_use_is_occupied_through_to_the_window_end(unclosed_resource_use_logger):
    """The resource use starts at t=15 and is never closed - `resource_occupancy_over_time`
    always censors (there is no `unclosed` parameter), so it must read as
    occupied for [15, 20), not vanish or read as occupied for the whole window."""
    occupancy = resource_occupancy_over_time(
        _trial_df([unclosed_resource_use_logger]), every_x_time_units=5, limit_duration=20
    )

    counts = dict(zip(occupancy["snapshot_time"], occupancy["count"]))
    assert counts == {0: 0, 5: 0, 10: 0, 15: 1, 20: 0}


def test_missing_resource_id_still_groups_by_step(resource_use_no_resource_id_logger):
    """Pairing falls back to (run, entity) when resource_id is missing entirely
    (see `resource_use_intervals`), but occupancy is grouped by step (`event`)
    regardless, so this must still produce a sensible per-step curve."""
    occupancy = resource_occupancy_over_time(
        _trial_df([resource_use_no_resource_id_logger]),
        every_x_time_units=5,
        limit_duration=20,
    )

    counts = dict(zip(occupancy["snapshot_time"], occupancy["count"]))
    assert counts == {0: 1, 5: 1, 10: 0, 15: 0, 20: 0}


@pytest.mark.parametrize("bad_value", [0, -1])
def test_every_x_time_units_must_be_positive(bad_value, resource_use_loggers):
    with pytest.raises(ValueError, match="every_x_time_units"):
        resource_occupancy_over_time(
            _trial_df(resource_use_loggers),
            every_x_time_units=bad_value,
            limit_duration=20,
        )


def test_no_resource_use_events_returns_an_empty_frame_with_the_right_columns(
    two_run_loggers,
):
    occupancy = resource_occupancy_over_time(_trial_df(two_run_loggers))

    assert list(occupancy.columns) == ["run_number", "event", "snapshot_time", "count"]
    assert occupancy.empty


def test_a_unit_freed_exactly_at_a_snapshot_is_not_counted_as_busy_there():
    """Pins the half-open [start, end) convention: mutating the clip so `end`
    is compared with `<=` instead of strict `<` on the occupied side would make
    this test fail, since unit 1 (busy [0, 10)) would still read as busy at
    t=10."""
    logger = EventLogger(run_number=1)
    logger.log_resource_use_start(
        entity_id=1, resource_id=1, time=0.0, event="treatment_begins"
    )
    logger.log_resource_use_end(
        entity_id=1, resource_id=1, time=10.0, event="treatment_ends"
    )

    occupancy = resource_occupancy_over_time(
        TrialLogger([logger]).to_dataframe(), every_x_time_units=10, limit_duration=10
    )

    counts = dict(zip(occupancy["snapshot_time"], occupancy["count"]))
    assert counts == {0: 1, 10: 0}
