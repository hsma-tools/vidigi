"""Tests for `vidigi.analysis.queue_size_over_time`.

Extracted from `TrialLogger.plot_queue_size`; the numbers here mirror the
hand-computed expectations already pinned against that method in
`test_logging_triallogger.py`, checked here against the DataFrame directly
rather than through a rendered figure.
"""

import pandas as pd
import pytest

from vidigi.analysis import queue_size_over_time
from vidigi.logging import TrialLogger


def _trial_df(loggers):
    return TrialLogger(loggers).to_dataframe()


def test_reports_the_true_queue_length_not_the_snapshot_cap(long_queue_logger):
    """A 150-long queue must be reported as 150, not flatten off at a display cap."""
    event_log = _trial_df([long_queue_logger])

    result = queue_size_over_time(
        event_log, ["waiting"], limit_duration=30, every_x_time_units=10
    )

    assert list(result["snapshot_time"]) == [0, 10, 20, 30]
    assert list(result["count"]) == [150, 150, 150, 150]


def test_empty_queue_is_reported_as_zero_not_omitted(emptying_queue_loggers):
    event_log = _trial_df(emptying_queue_loggers)

    result = queue_size_over_time(
        event_log, ["waiting"], limit_duration=30, every_x_time_units=10
    )

    by_run = {
        run: sub.sort_values("snapshot_time")["count"].tolist()
        for run, sub in result.groupby("run_number")
    }
    assert by_run[1] == [1, 1, 0, 0]
    assert by_run[2] == [0, 0, 1, 1]


def test_unseen_event_warns_and_is_reported_as_zero(emptying_queue_loggers):
    event_log = _trial_df(emptying_queue_loggers)

    with pytest.warns(UserWarning, match="did not occur in any run"):
        result = queue_size_over_time(
            event_log, ["waitng"], limit_duration=30, every_x_time_units=10
        )

    assert (result["count"] == 0).all()


def test_warm_up_zero_is_a_verified_no_op(warm_up_log):
    without = queue_size_over_time(
        warm_up_log, ["waiting"], limit_duration=200, every_x_time_units=10
    )
    with_zero = queue_size_over_time(
        warm_up_log,
        ["waiting"],
        limit_duration=200,
        every_x_time_units=10,
        warm_up=0,
    )
    pd.testing.assert_frame_equal(without, with_zero)


def test_warm_up_trims_the_window(warm_up_log):
    """See the fixture's docstring: at snapshot 120, entities 1-7 are queuing."""
    result = queue_size_over_time(
        warm_up_log,
        ["waiting"],
        limit_duration=200,
        every_x_time_units=10,
        warm_up=100,
    )

    assert result["snapshot_time"].min() == 100
    at_120 = result.loc[result["snapshot_time"] == 120, "count"].item()
    assert at_120 == 7


def test_run_column_named_plain_run_is_auto_detected():
    """`run_col_name="auto"` must find a column literally called 'run', not just
    'run_number' - the name `TrialLogger` always uses.
    """
    event_log = pd.DataFrame(
        [
            {
                "entity_id": 1,
                "event_type": "arrival_departure",
                "event": "arrival",
                "time": 0,
                "run": 1,
            },
            {
                "entity_id": 1,
                "event_type": "queue",
                "event": "waiting",
                "time": 0,
                "run": 1,
            },
            {
                "entity_id": 1,
                "event_type": "arrival_departure",
                "event": "depart",
                "time": 5,
                "run": 1,
            },
        ]
    )

    result = queue_size_over_time(event_log, ["waiting"], limit_duration=5)

    assert (result["run_number"] == 1).all()


def test_no_run_column_still_produces_a_result():
    event_log = pd.DataFrame(
        [
            {
                "entity_id": 1,
                "event_type": "arrival_departure",
                "event": "arrival",
                "time": 0,
            },
            {"entity_id": 1, "event_type": "queue", "event": "waiting", "time": 0},
            {
                "entity_id": 1,
                "event_type": "arrival_departure",
                "event": "depart",
                "time": 5,
            },
        ]
    )

    result = queue_size_over_time(event_log, ["waiting"], limit_duration=5)

    assert result["run_number"].isna().all()
    assert result.loc[result["snapshot_time"] == 0, "count"].item() == 1
