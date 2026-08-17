"""Tests for ``TrialLogger``.

TrialLogger is where multi-run statistics come from, so a mistake here shows
up as a plausible-looking number rather than an error. Every expected value
below is hand-computable from the fixtures in conftest.py: each entity arrives,
waits one time unit, and departs five time units after arriving.
"""

import pandas as pd
import plotly.graph_objects as go
import pytest

from vidigi.logging import EventLogger, TrialLogger


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #


def test_construct_from_list_of_loggers(two_run_loggers):
    trial = TrialLogger(two_run_loggers)

    assert trial.summary() == {"number_of_runs": 2}


def test_construct_empty():
    """An empty trial is a reasonable starting point for a loop of add_log calls.

    Regression test: this raised `ValueError: No objects to concatenate` from
    pd.concat on an empty list.
    """
    trial = TrialLogger()

    assert trial.summary() == {"number_of_runs": 0}
    assert trial.to_dataframe().empty


def test_add_log_to_empty_trial(single_run_logger):
    trial = TrialLogger()

    trial.add_log(single_run_logger)

    assert trial.summary() == {"number_of_runs": 1}
    assert len(trial.to_dataframe()) == len(single_run_logger.log)


def test_logger_without_run_number_is_rejected():
    """run_number identifies the run, so a log without one cannot be indexed."""
    logger = EventLogger()
    logger.log_arrival(entity_id=1, time=0.0)

    with pytest.raises(ValueError, match="no `run_number`"):
        TrialLogger([logger])


def test_empty_logger_is_rejected():
    with pytest.raises(ValueError, match="empty EventLogger"):
        TrialLogger([EventLogger(run_number=1)])


# --------------------------------------------------------------------------- #
# The trial dataframe stays current
# --------------------------------------------------------------------------- #


def test_add_log_is_reflected_in_the_trial_dataframe(two_run_loggers):
    """Regression test: the frame was built once in __init__ and never rebuilt.

    summary() counted the added run while every statistic was still computed
    from the runs present at construction - a silently wrong answer, with no
    error and no warning.
    """
    first, second = two_run_loggers
    trial = TrialLogger([first])

    trial.add_log(second)

    runs_in_frame = set(trial.to_dataframe()["run_number"])
    assert runs_in_frame == {1, 2}
    assert trial.summary()["number_of_runs"] == 2


def test_statistics_account_for_logs_added_after_construction(two_run_loggers):
    """The count of durations must double when a second identical run is added."""
    first, second = two_run_loggers
    trial = TrialLogger([first])

    before = trial.get_event_duration_stat("arrival", "depart", what="count")
    trial.add_log(second)
    after = trial.get_event_duration_stat("arrival", "depart", what="count")

    assert before == 2
    assert after == 4


def test_trial_dataframe_concatenates_all_runs(two_run_loggers):
    trial = TrialLogger(two_run_loggers)

    expected_rows = sum(len(logger.log) for logger in two_run_loggers)

    assert len(trial.to_dataframe()) == expected_rows


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #


def test_get_log_by_run_returns_the_logger(two_run_loggers):
    trial = TrialLogger(two_run_loggers)

    result = trial.get_log_by_run(1)

    assert isinstance(result, EventLogger)


def test_get_log_by_run_as_dataframe(two_run_loggers):
    """Regression test: both branches returned the EventLogger.

    `as_df=True` handed back an object with no DataFrame behaviour at all.
    """
    trial = TrialLogger(two_run_loggers)

    result = trial.get_log_by_run(1, as_df=True)

    assert isinstance(result, pd.DataFrame)
    assert set(result["run_number"]) == {1}


def test_get_log_by_run_rejects_unknown_run(two_run_loggers):
    trial = TrialLogger(two_run_loggers)

    with pytest.raises(KeyError):
        trial.get_log_by_run(99)


# --------------------------------------------------------------------------- #
# Duration statistics
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "what, expected",
    [
        ("mean", 5.0),
        ("median", 5.0),
        ("min", 5.0),
        ("max", 5.0),
        ("sum", 20.0),
        ("count", 4),
        ("std", 0.0),
        ("var", 0.0),
    ],
)
def test_duration_statistics(two_run_loggers, what, expected):
    """Every arrival-to-depart duration in the fixtures is exactly 5.0.

    Two runs of two entities gives four durations, so the sum is 20 and the
    spread is zero.
    """
    trial = TrialLogger(two_run_loggers)

    assert trial.get_event_duration_stat("arrival", "depart", what=what) == expected


def test_quantile_accepts_kwargs(two_run_loggers):
    trial = TrialLogger(two_run_loggers)

    result = trial.get_event_duration_stat(
        "arrival", "depart", what="quantile", q=0.9
    )

    assert result == 5.0


def test_rounding_honours_dp():
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_departure(entity_id=1, time=1.23456)
    trial = TrialLogger([logger])

    assert trial.get_event_duration_stat("arrival", "depart", what="mean", dp=3) == 1.235


def test_label_wraps_result(two_run_loggers):
    trial = TrialLogger(two_run_loggers)

    result = trial.get_event_duration_stat(
        "arrival", "depart", what="mean", label="Time in system"
    )

    assert result == {"stat": "Time in system", "value": 5.0}


def test_unsupported_aggregation_lists_the_valid_ones(two_run_loggers):
    trial = TrialLogger(two_run_loggers)

    with pytest.raises(ValueError, match="Unsupported aggregation"):
        trial.get_event_duration_stat("arrival", "depart", what="nonsense")


# --------------------------------------------------------------------------- #
# Served / unserved accounting
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "what, expected",
    [
        ("served_count", 2),
        ("unserved_count", 1),
        ("served_rate", pytest.approx(2 / 3, abs=0.01)),
        ("unserved_rate", pytest.approx(1 / 3, abs=0.01)),
    ],
)
def test_served_and_unserved_counts(logger_with_unserved_entity, what, expected):
    """Three entities arrive, two depart - so exactly one is unserved."""
    trial = TrialLogger([logger_with_unserved_entity])

    assert trial.get_event_duration_stat("arrival", "depart", what=what) == expected


def test_summary_unserved_count_is_the_number_unserved(logger_with_unserved_entity):
    """Regression test: this reported the *total* entity count, not the unserved.

    The standalone `what="unserved_count"` path was already correct, so the two
    routes to the same statistic disagreed - with three entities of which one
    was unserved, the summary said 3 and the standalone said 1.
    """
    trial = TrialLogger([logger_with_unserved_entity])

    summary = trial.get_event_duration_stat("arrival", "depart", what="summary")
    standalone = trial.get_event_duration_stat(
        "arrival", "depart", what="unserved_count"
    )

    assert summary["unserved_count"] == 1
    assert summary["unserved_count"] == standalone


def test_summary_per_run_means(logger_with_unserved_entity):
    """One run with one unserved and two served entities."""
    trial = TrialLogger([logger_with_unserved_entity])

    summary = trial.get_event_duration_stat("arrival", "depart", what="summary")

    assert summary["unserved_count_mean_per_run"] == 1.0
    assert summary["served_count_mean_per_run"] == 2.0


def test_summary_per_run_means_across_two_runs():
    """Per-run means must divide by the number of runs, not report the total."""
    loggers = []
    for run in (1, 2):
        logger = EventLogger(run_number=run)
        for entity_id in (1, 2):
            logger.log_arrival(entity_id=entity_id, time=float(entity_id))
            logger.log_departure(entity_id=entity_id, time=float(entity_id) + 5)
        logger.log_arrival(entity_id=99, time=10.0)
        loggers.append(logger)
    trial = TrialLogger(loggers)

    summary = trial.get_event_duration_stat("arrival", "depart", what="summary")

    # Six entities across two runs: four served, two unserved.
    assert summary["served_count"] == 4
    assert summary["unserved_count"] == 2
    assert summary["served_count_mean_per_run"] == 2.0
    assert summary["unserved_count_mean_per_run"] == 1.0


def test_summary_statistics_ignore_incomplete_journeys(
    logger_with_unserved_entity,
):
    """The unserved entity has no duration, so it must not drag the mean down."""
    trial = TrialLogger([logger_with_unserved_entity])

    summary = trial.get_event_duration_stat("arrival", "depart", what="summary")

    assert summary["mean (of complete)"] == 5.0
    assert summary["median (of complete)"] == 5.0


def test_count_can_include_incomplete_journeys(logger_with_unserved_entity):
    trial = TrialLogger([logger_with_unserved_entity])

    excluding = trial.get_event_duration_stat(
        "arrival", "depart", what="count", exclude_incomplete=True
    )
    including = trial.get_event_duration_stat(
        "arrival", "depart", what="count", exclude_incomplete=False
    )

    assert excluding == 2
    assert including == 3


# --------------------------------------------------------------------------- #
# Plotting entry points
# --------------------------------------------------------------------------- #


def test_plot_metric_bar_returns_a_figure(two_run_loggers):
    trial = TrialLogger(two_run_loggers)

    fig = trial.plot_metric_bar(
        [
            {
                "label": "Time in system",
                "first_event": "arrival",
                "second_event": "depart",
            }
        ]
    )

    assert isinstance(fig, go.Figure)


def test_plot_metric_bar_uses_one_bar_per_pair(two_run_loggers):
    trial = TrialLogger(two_run_loggers)

    fig = trial.plot_metric_bar(
        [
            {"label": "A", "first_event": "arrival", "second_event": "depart"},
            {"label": "B", "first_event": "arrival", "second_event": "waiting"},
        ]
    )

    assert list(fig.data[0].x) == ["A", "B"]


def test_plot_queue_size_returns_a_figure(two_run_loggers):
    trial = TrialLogger(two_run_loggers)

    fig = trial.plot_queue_size(event_list=["waiting"], limit_duration=20)

    assert isinstance(fig, go.Figure)


def test_plot_queue_size_mean_only(two_run_loggers):
    trial = TrialLogger(two_run_loggers)

    fig = trial.plot_queue_size(
        event_list=["waiting"], limit_duration=20, show_all_runs=False
    )

    assert isinstance(fig, go.Figure)
