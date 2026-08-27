"""Tests for `vidigi.analysis.entity_metric_by_arrival`."""

import numpy as np
import pandas as pd
import pytest

from vidigi.analysis import entity_metric_by_arrival
from vidigi.logging import EventLogger, TrialLogger


def _logger_with_arrivals(
    entries, *, arrival_event="arrival", first_event="wait_begins",
    second_event="depart", run_number=1,
):
    """One run where entity i arrives, hits `first_event`, then `second_event`
    at the three times in entries[i-1] = (arrival_time, first_time, second_time).

    If any of `arrival_event`/`first_event`/`second_event` name the same event,
    only one event is logged for it (at whichever of the three times is given
    for the earliest-named slot below) - `entries`' other time(s) for that slot
    are then unused, matching what one real event with one real time would do.
    """
    logger = EventLogger(run_number=run_number)
    for i, (arrival_time, first_time, second_time) in enumerate(entries, start=1):
        times_by_event = {}
        times_by_event[arrival_event] = arrival_time
        times_by_event.setdefault(first_event, first_time)
        times_by_event.setdefault(second_event, second_time)
        for event, time in times_by_event.items():
            logger.log_custom_event(
                entity_id=i, event_type="milestone", event=event, time=time
            )
    return logger


def _trial_df(loggers):
    return TrialLogger(loggers).to_dataframe()


def test_basic_shape_and_columns(unequal_run_loggers):
    df = entity_metric_by_arrival(_trial_df(unequal_run_loggers), "arrival", "depart")
    assert list(df.columns) == [
        "entity_id",
        "run_number",
        "pathway",
        "occurrence",
        "first_time",
        "second_time",
        "duration",
        "arrival_time",
    ]
    assert list(df["duration"]) == pytest.approx([4] * 2 + [5] * 4 + [9] * 2)
    # unequal_run_loggers has every entity arrive at t=0.0.
    assert list(df["arrival_time"]) == pytest.approx([0.0] * 8)


def test_arrival_time_comes_from_arrival_event_not_first_time():
    """`arrival_event` is deliberately independent of `first_event` - proves
    `arrival_time` tracks the former, not `event_durations`'s own `first_time`."""
    entries = [(0.0, 3.0, 10.0), (1.0, 6.0, 12.0)]
    logger = _logger_with_arrivals(
        entries, arrival_event="arrival", first_event="wait_begins", second_event="depart"
    )
    df = entity_metric_by_arrival(_trial_df([logger]), "wait_begins", "depart")

    assert list(df["arrival_time"]) == pytest.approx([0.0, 1.0])
    assert list(df["first_time"]) == pytest.approx([3.0, 6.0])
    assert list(df["duration"]) == pytest.approx([7.0, 6.0])


def test_occurrence_match_shares_one_arrival_time_across_rows(rework_loop_logger):
    """`rework_loop_logger` has no 'arrival' event at all, only 'assessment'
    (t=1, t=20) and 'treated' (t=5, t=30) - use 'assessment' as arrival_event.
    Under match='occurrence' both duration rows must get the *same*
    arrival_time (the earliest assessment, t=1) - not one each."""
    df = entity_metric_by_arrival(
        _trial_df([rework_loop_logger]),
        "assessment",
        "treated",
        arrival_event="assessment",
        match="occurrence",
    )
    assert list(df["duration"]) == pytest.approx([4.0, 10.0])
    assert list(df["arrival_time"]) == pytest.approx([1.0, 1.0])


def test_last_match_arrival_time_still_uses_earliest_assessment(rework_loop_logger):
    """match='last' pairs the duration on the *last* assessment (t=20), but the
    arrival lookup must still use the entity's *earliest* assessment (t=1) -
    mutation-catching if the arrival lookup were wired to `match` instead of
    always using the earliest occurrence."""
    df = entity_metric_by_arrival(
        _trial_df([rework_loop_logger]),
        "assessment",
        "treated",
        arrival_event="assessment",
        match="last",
    )
    assert df["duration"].iloc[0] == pytest.approx(10.0)  # 30 - 20
    assert df["arrival_time"].iloc[0] == pytest.approx(1.0)  # earliest assessment, not 20


def test_entity_with_no_arrival_event_keeps_row_with_nan_arrival_time():
    """`arrival_event` must exist *somewhere* in the log to pass
    `_check_events_present` (a whole-log check, like `event_durations`'s own
    presence checks) - entity 2 provides that, while entity 1, whose row is
    the one under test, has no arrival event of its own."""
    logger = EventLogger(run_number=1)
    logger.log_custom_event(entity_id=1, event_type="milestone", event="wait_begins", time=3.0)
    logger.log_custom_event(entity_id=1, event_type="milestone", event="depart", time=10.0)
    logger.log_arrival(entity_id=2, time=0.0)
    logger.log_departure(entity_id=2, time=1.0)

    df = entity_metric_by_arrival(
        _trial_df([logger]), "wait_begins", "depart", arrival_event="arrival"
    )

    row = df[df["entity_id"] == 1].iloc[0]
    assert row["duration"] == pytest.approx(7.0)
    assert np.isnan(row["arrival_time"])


def test_arrival_event_may_coincide_with_first_event():
    entries = [(0.0, 0.0, 5.0)]
    logger = _logger_with_arrivals(
        entries, arrival_event="arrival", first_event="arrival", second_event="depart"
    )
    df = entity_metric_by_arrival(
        _trial_df([logger]), "arrival", "depart", arrival_event="arrival"
    )
    assert df["arrival_time"].iloc[0] == pytest.approx(0.0)
    assert df["duration"].iloc[0] == pytest.approx(5.0)


def test_arrival_event_may_coincide_with_second_event():
    """arrival_event == second_event: the arrival lookup must use that event's
    one real time (0.0), not the unrelated time entries gives second_time
    (99.0, unused since the dict-building in `_logger_with_arrivals` only logs
    one event when two slots name the same event)."""
    entries = [(0.0, 3.0, 99.0)]
    logger = _logger_with_arrivals(
        entries, arrival_event="depart", first_event="wait_begins", second_event="depart"
    )
    df = entity_metric_by_arrival(
        _trial_df([logger]), "wait_begins", "depart", arrival_event="depart"
    )
    assert df["arrival_time"].iloc[0] == pytest.approx(0.0)


def test_arrival_event_missing_raises():
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_departure(entity_id=1, time=5.0)

    with pytest.raises(ValueError, match="nonexistent"):
        entity_metric_by_arrival(
            _trial_df([logger]), "arrival", "depart", arrival_event="nonexistent"
        )


def test_first_event_equals_second_event_raises():
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=0.0)

    with pytest.raises(ValueError, match="both"):
        entity_metric_by_arrival(_trial_df([logger]), "arrival", "arrival")


def test_no_run_column_still_joins_correctly():
    """A raw event log with no run-identifying column at all - `run_number` is
    `NA` on both the duration frame and the arrival frame, and must still
    match `NA` to `NA` under the merge rather than silently failing to join."""
    event_log = pd.DataFrame(
        {
            "entity_id": [1, 1, 2, 2, 2],
            "event": ["arrival", "depart", "arrival", "wait_begins", "depart"],
            "time": [0.0, 5.0, 1.0, 2.0, 8.0],
        }
    )

    df = entity_metric_by_arrival(event_log, "arrival", "depart", arrival_event="arrival")

    assert df["run_number"].isna().all()
    assert list(df["duration"]) == pytest.approx([5.0, 7.0])
    assert list(df["arrival_time"]) == pytest.approx([0.0, 1.0])
