"""Tests for ``TrialLogger``.

TrialLogger is where multi-run statistics come from, so a mistake here shows
up as a plausible-looking number rather than an error. Every expected value
below is hand-computable from the fixtures in conftest.py: each entity arrives,
waits one time unit, and departs five time units after arriving.
"""

import typing
import warnings

import pandas as pd
import plotly.graph_objects as go
import pytest

from vidigi.logging import DurationStat, EventLogger, TrialLogger


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


def test_add_log_validates_too(single_run_logger):
    """The same checks must apply on both routes into the trial.

    Validating only in the constructor would let add_log store None as the
    run id, leaving the log unretrievable by run.
    """
    trial = TrialLogger([single_run_logger])
    no_run_number = EventLogger()
    no_run_number.log_arrival(entity_id=1, time=0.0)

    with pytest.raises(ValueError, match="no `run_number`"):
        trial.add_log(no_run_number)

    with pytest.raises(ValueError, match="empty EventLogger"):
        trial.add_log(EventLogger(run_number=2))


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
# get_event_durations - thin wrapper over vidigi.analysis.event_durations
# --------------------------------------------------------------------------- #


def test_get_event_durations_returns_the_full_per_entity_frame(two_run_loggers):
    trial = TrialLogger(two_run_loggers)

    result = trial.get_event_durations("arrival", "depart")

    assert sorted(result["duration"].tolist()) == [5.0, 5.0, 5.0, 5.0]
    assert set(result["run_number"]) == {1, 2}
    assert list(result.columns) == [
        "entity_id",
        "run_number",
        "pathway",
        "occurrence",
        "first_time",
        "second_time",
        "duration",
    ]


def test_get_event_durations_handles_a_rework_loop(rework_loop_logger):
    """The old pivot-based calculation cannot run against this fixture at all."""
    trial = TrialLogger([rework_loop_logger])

    result = trial.get_event_durations("assessment", "treated", match="occurrence")

    assert sorted(result["duration"].tolist()) == [4.0, 10.0]


def _old_pivot_durations(trial, first_event, second_event):
    """Replicates the pre-1.5.0 `pivot`-based calculation, for parity testing only."""
    df = trial.to_dataframe()
    event_df = df[df["event"].isin([first_event, second_event])][
        ["entity_id", "run_number", "event", "time"]
    ].copy()
    pivoted = event_df.pivot(
        columns="event", index=["entity_id", "run_number"], values="time"
    ).reset_index()[["entity_id", "run_number", first_event, second_event]]
    pivoted["duration"] = pivoted[second_event] - pivoted[first_event]
    return pivoted


@pytest.mark.parametrize(
    "fixture_name",
    [
        "single_run_logger",
        "two_run_loggers",
        "logger_with_unserved_entity",
        "long_queue_logger",
        "emptying_queue_loggers",
    ],
)
def test_get_event_durations_matches_the_old_pivot_where_it_worked(
    fixture_name, request
):
    """`match="first"` must reproduce the old pivot exactly wherever it succeeded.

    Every fixture here has each entity visiting 'arrival' and 'depart' at most
    once per run, which is exactly the case the pivot could handle.
    """
    fixture = request.getfixturevalue(fixture_name)
    loggers = fixture if isinstance(fixture, list) else [fixture]
    trial = TrialLogger(loggers)

    old = (
        _old_pivot_durations(trial, "arrival", "depart")
        .sort_values(["run_number", "entity_id"])
        .reset_index(drop=True)
    )
    new = (
        trial.get_event_durations("arrival", "depart")
        .sort_values(["run_number", "entity_id"])
        .reset_index(drop=True)
    )

    assert list(new["entity_id"]) == list(old["entity_id"])
    assert list(new["run_number"]) == list(old["run_number"])
    pd.testing.assert_series_equal(
        new["duration"], old["duration"], check_names=False
    )


def test_old_pivot_raises_on_a_rework_loop(rework_loop_logger):
    """Pins the behaviour `event_durations` replaces: the pivot cannot represent
    an entity visiting the same event twice, since both visits map to the same
    (entity_id, run_number, event) cell.
    """
    trial = TrialLogger([rework_loop_logger])

    with pytest.raises(ValueError):
        _old_pivot_durations(trial, "assessment", "treated")


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


def test_summary_per_run_means_count_runs_with_neither_event_too():
    """Regression test: the denominator was the number of runs *containing
    either event*, so a run where neither occurred at all was silently dropped
    from it - inflating served/unserved rates that are meant to be per-run
    averages over the whole trial.
    """
    loggers = []
    for run in (1, 2):
        logger = EventLogger(run_number=run)
        logger.log_custom_event(
            entity_id=1, event_type="milestone", event="check_in", time=0.0
        )
        logger.log_custom_event(
            entity_id=1, event_type="milestone", event="check_out", time=5.0
        )
        loggers.append(logger)

    # Run 3 never has a 'check_in' or 'check_out' event at all.
    third = EventLogger(run_number=3)
    third.log_arrival(entity_id=1, time=0.0)
    third.log_departure(entity_id=1, time=1.0)
    loggers.append(third)

    trial = TrialLogger(loggers)

    summary = trial.get_event_duration_stat("check_in", "check_out", what="summary")

    assert summary["served_count"] == 2
    assert summary["served_count_mean_per_run"] == round(2 / 3, 2)
    assert summary["unserved_count_mean_per_run"] == 0.0


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


@pytest.mark.parametrize("what", typing.get_args(DurationStat))
def test_every_duration_stat_literal_is_accepted(what, two_run_loggers):
    """The annotation must not advertise a statistic the runtime check rejects.

    `get_event_duration_stat` validates `what` against a set built in the method
    body, so the Literal is a second copy of that list and could drift from it.
    """
    trial = TrialLogger(two_run_loggers)
    extra = {"q": 0.9} if what == "quantile" else {}

    result = trial.get_event_duration_stat("arrival", "depart", what=what, **extra)

    assert result is not None


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


# --------------------------------------------------------------------------- #
# plot_queue_size: the plotted number must be the queue length
#
# These assert values rather than figure types. The two tests above would pass
# against a blank chart, and did pass while the queue length was saturating.
# --------------------------------------------------------------------------- #


def test_plot_queue_size_reports_queues_longer_than_step_snapshot_max(
    long_queue_logger,
):
    """A 150-long queue must plot as 150, not flatten off at the display cap.

    `step_snapshot_max` caps how many entity icons an animation draws. Inherited
    here it capped the *count*, so every long queue plotted a flat 61 - a
    bottleneck reads as a stable queue, with no visual cue that anything had
    been discarded.
    """
    trial = TrialLogger([long_queue_logger])

    fig = trial.plot_queue_size(
        event_list=["waiting"], limit_duration=30, every_x_time_units=10
    )

    run_trace = fig.data[0]
    assert list(run_trace.x) == [0, 10, 20, 30]
    assert list(run_trace.y) == [150, 150, 150, 150]


def test_plot_queue_size_plots_an_empty_queue_as_zero(emptying_queue_loggers):
    """A snapshot with nobody queuing must be plotted, not omitted.

    An event with no rows contributed no point at all, so the line was drawn
    straight across the gap - asserting a queue over exactly the period it had
    emptied. See the fixture for the full expected series.
    """
    trial = TrialLogger(emptying_queue_loggers)

    fig = trial.plot_queue_size(
        event_list=["waiting"], limit_duration=30, every_x_time_units=10
    )

    by_run = {trace.name: list(trace.y) for trace in fig.data}
    assert by_run["1"] == [1, 1, 0, 0]
    assert by_run["2"] == [0, 0, 1, 1]
    assert all(list(trace.x) == [0, 10, 20, 30] for trace in fig.data)


def test_plot_queue_size_mean_includes_runs_with_an_empty_queue(
    emptying_queue_loggers,
):
    """The mean must be over every run, including those with nobody queuing.

    Averaging only the runs that happened to have a row biases the mean upwards
    exactly when the queue is shortest. Here one run holds 1 and the other 0 at
    every snapshot, so the mean is 0.5 throughout; it previously read 1.0.
    """
    trial = TrialLogger(emptying_queue_loggers)

    fig = trial.plot_queue_size(
        event_list=["waiting"],
        limit_duration=30,
        every_x_time_units=10,
        show_all_runs=False,
    )

    assert list(fig.data[0].y) == [0.5, 0.5, 0.5, 0.5]


def test_plot_queue_size_warns_when_an_event_never_occurs(emptying_queue_loggers):
    """Zero-filling means a misspelt event name would silently plot a flat zero."""
    trial = TrialLogger(emptying_queue_loggers)

    with pytest.warns(UserWarning, match="did not occur in any run"):
        fig = trial.plot_queue_size(
            event_list=["waitng"], limit_duration=30, every_x_time_units=10
        )

    assert list(fig.data[0].y) == [0, 0, 0, 0]


def test_plot_queue_size_does_not_warn_when_an_event_occurs_in_only_some_runs():
    """A queue that forms in one run but not another is ordinary, not suspicious.

    The warning has to key off the runs collectively. Keyed off each run
    individually it would fire on entirely valid input, and a warning that cries
    wolf gets filtered out along with the real one.
    """
    queues = EventLogger(run_number=1)
    queues.log_arrival(entity_id=1, time=0.0)
    queues.log_queue(entity_id=1, event="waiting", time=0.0)
    queues.log_departure(entity_id=1, time=30.0)

    never_queues = EventLogger(run_number=2)
    never_queues.log_arrival(entity_id=1, time=0.0)
    never_queues.log_departure(entity_id=1, time=30.0)

    trial = TrialLogger([queues, never_queues])

    with warnings.catch_warnings(record=True) as raised:
        warnings.simplefilter("always")
        fig = trial.plot_queue_size(
            event_list=["waiting"], limit_duration=20, every_x_time_units=10
        )

    assert not [w for w in raised if "did not occur" in str(w.message)]

    by_run = {trace.name: list(trace.y) for trace in fig.data}
    assert by_run["1"] == [1, 1, 1]
    assert by_run["2"] == [0, 0, 0]
