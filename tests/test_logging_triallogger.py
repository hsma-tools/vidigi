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


def test_get_event_durations_warm_up_is_passed_through(two_run_loggers):
    """Entity 1 arrives at t=1, entity 2 at t=2, in both runs (see
    `_build_logger`). `warm_up=1.5` excludes entity 1 from every run,
    leaving only entity 2's four pairings."""
    trial = TrialLogger(two_run_loggers)

    result = trial.get_event_durations("arrival", "depart", warm_up=1.5)

    assert set(result["entity_id"]) == {2}
    assert len(result) == 2


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


def test_get_event_duration_stat_warm_up_is_passed_through(two_run_loggers):
    """Entity 1 arrives at t=1, entity 2 at t=2 (see `_build_logger`).
    `warm_up=1.5` excludes entity 1 from both runs, leaving only entity 2's
    two durations - `count` drops from 4 to 2, proven to fail if `warm_up`
    were dropped on the way to `get_event_durations`."""
    trial = TrialLogger(two_run_loggers)

    assert trial.get_event_duration_stat("arrival", "depart", what="count", warm_up=1.5) == 2


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


def test_plot_metric_bar_across_runs_with_ci_is_passed_through(unequal_run_loggers):
    """`across="runs"`/`error_bars="ci"` reach `vidigi.plots.plot_metric_bar`, and
    the delegation reproduces the hand-computed values from that fixture's
    docstring exactly."""
    trial = TrialLogger(unequal_run_loggers)

    fig = trial.plot_metric_bar(
        [{"label": "A", "first_event": "arrival", "second_event": "depart"}],
        across="runs",
        error_bars="ci",
    )

    assert fig.data[0].y == pytest.approx((6.0,))
    assert round(fig.data[0].error_y.array[0], 3) == 6.572


def test_plot_metric_bar_across_entities_is_unchanged_at_defaults(unequal_run_loggers):
    """`across="entities"` (the default) must give exactly what every prior
    release gave: the pooled mean over every entity, ignoring run boundaries."""
    trial = TrialLogger(unequal_run_loggers)

    fig = trial.plot_metric_bar(
        [{"label": "A", "first_event": "arrival", "second_event": "depart"}]
    )

    assert fig.data[0].y == pytest.approx((5.75,))


def test_plot_metric_bar_warm_up_is_passed_through():
    """One entity's pairing starts before t=10 (duration 4), the other after
    (duration 6) - a dropped `warm_up` would pool both into a mean of 5.0,
    so this distinguishes a working passthrough from a silently ignored one
    purely through `plot_metric_bar` itself."""
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_departure(entity_id=1, time=4.0)
    logger.log_arrival(entity_id=2, time=10.0)
    logger.log_departure(entity_id=2, time=16.0)
    trial = TrialLogger([logger])

    fig = trial.plot_metric_bar(
        [{"label": "A", "first_event": "arrival", "second_event": "depart"}],
        warm_up=10,
    )

    assert fig.data[0].y == pytest.approx((6.0,))


def test_get_resource_utilisation_is_passed_through(resource_use_loggers):
    """`get_resource_utilisation` reaches `vidigi.analysis.resource_utilisation`,
    and reproduces the hand-computed values from that fixture's docstring
    exactly."""
    trial = TrialLogger(resource_use_loggers)

    result = trial.get_resource_utilisation(
        by="resource", resource_capacities={"treatment_begins": 3}, limit_duration=20
    )

    run1 = result[result["run_number"] == 1]
    assert dict(zip(run1["resource_id"], run1["busy_time"])) == {1: 10.0, 2: 5.0, 3: 0.0}


def _colliding_pool_logger():
    """One run, two entities sharing resource_id=1 but with disjoint
    unique_resource_id values, genuinely overlapping in time - the motivating
    case for `VidigiStore`'s `label=`/`unique_id_attribute`."""
    logger = EventLogger(run_number=1)
    logger.log_resource_use_start(
        entity_id=1, resource_id=1, unique_resource_id="a_1", time=0.0, event="step_begins"
    )
    logger.log_resource_use_end(
        entity_id=1, resource_id=1, unique_resource_id="a_1", time=10.0, event="step_ends"
    )
    logger.log_resource_use_start(
        entity_id=2, resource_id=1, unique_resource_id="b_1", time=5.0, event="step_begins"
    )
    logger.log_resource_use_end(
        entity_id=2, resource_id=1, unique_resource_id="b_1", time=15.0, event="step_ends"
    )
    return logger


def test_get_resource_utilisation_resource_col_name_auto_prefers_unique_resource_id():
    """`resource_col_name=None` (the default) picks `unique_resource_id`
    over `resource_id` whenever the log has it - so a model built the
    recommended way needs no extra argument here to get a collision-proof
    breakdown."""
    trial = TrialLogger([_colliding_pool_logger()])

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = trial.get_resource_utilisation(by="resource", limit_duration=20)

    assert not any("overlapping" in str(w.message) for w in caught)
    assert set(result["resource_id"]) == {"a_1", "b_1"}


def test_get_resource_utilisation_resource_col_name_explicit_override_still_works():
    """Passing resource_col_name="resource_id" explicitly must still reach the
    raw, collision-prone column, overriding the `None` (auto-detect) default."""
    trial = TrialLogger([_colliding_pool_logger()])

    with pytest.warns(UserWarning, match="overlapping"):
        result = trial.get_resource_utilisation(
            by="resource", resource_col_name="resource_id", limit_duration=20
        )
    assert set(result["resource_id"]) == {1}


def test_resolve_resource_col_name_defaults_to_unique_resource_id_when_present():
    trial = TrialLogger([_colliding_pool_logger()])
    df = trial.to_dataframe()
    assert trial._resolve_resource_col_name(None, df) == "unique_resource_id"


def test_resolve_resource_col_name_falls_back_to_resource_id_when_absent(resource_use_loggers):
    trial = TrialLogger(resource_use_loggers)
    df = trial.to_dataframe()
    assert trial._resolve_resource_col_name(None, df) == "resource_id"


def test_resolve_resource_col_name_explicit_value_is_returned_unchanged(resource_use_loggers):
    trial = TrialLogger(resource_use_loggers)
    df = trial.to_dataframe()
    assert trial._resolve_resource_col_name("something_else", df) == "something_else"


def test_resolve_resource_col_name_uses_the_passed_dataframe_not_a_fresh_rebuild():
    """The resolver must check `unique_resource_id` on the dataframe it is
    given, not re-derive its own copy from `self._trial_dataframe` - that
    would defeat the point of building the frame once per call and passing
    it in (see the callers in get_resource_utilisation etc.)."""
    trial = TrialLogger([_colliding_pool_logger()])  # has unique_resource_id
    other_df = pd.DataFrame({"resource_id": [1, 2]})  # does not

    assert trial._resolve_resource_col_name(None, other_df) == "resource_id"


def test_get_resource_utilisation_auto_raises_on_a_partially_populated_column():
    """Documented **BREAKING** edge case (see HISTORY.md): a trial where
    unique_resource_id is present on some resource-use rows but not others -
    e.g. only part of a model's logging was updated to the label= pattern -
    used to succeed under the old hard-coded resource_id default. `None` now
    picks unique_resource_id (it exists somewhere in the trial) and
    resource_use_intervals correctly refuses to pair on a partially-populated
    column, so this now raises instead of silently working. Passing
    resource_col_name="resource_id" explicitly restores the old behaviour."""
    with_unique_id = EventLogger(run_number=1)
    with_unique_id.log_resource_use_start(
        entity_id=1, resource_id=1, unique_resource_id="a_1", time=0.0, event="step_begins"
    )
    with_unique_id.log_resource_use_end(
        entity_id=1, resource_id=1, unique_resource_id="a_1", time=10.0, event="step_ends"
    )
    without_unique_id = EventLogger(run_number=2)
    without_unique_id.log_resource_use_start(
        entity_id=1, resource_id=1, time=0.0, event="step_begins"
    )
    without_unique_id.log_resource_use_end(
        entity_id=1, resource_id=1, time=10.0, event="step_ends"
    )
    trial = TrialLogger([with_unique_id, without_unique_id])

    with pytest.raises(ValueError, match="unique_resource_id"):
        trial.get_resource_utilisation(by="resource", limit_duration=20)

    # The explicit escape hatch named in HISTORY.md must still work.
    result = trial.get_resource_utilisation(
        by="resource", resource_col_name="resource_id", limit_duration=20
    )
    assert set(result["run_number"]) == {1, 2}


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


def test_plot_queue_size_backend_go_is_passed_through(long_queue_logger):
    """`backend="go"` reaches vidigi.plots.plot_queue_size, and reports the same
    queue length as the default express backend does.
    """
    trial = TrialLogger([long_queue_logger])

    fig = trial.plot_queue_size(
        event_list=["waiting"],
        limit_duration=30,
        every_x_time_units=10,
        backend="go",
    )

    run_trace = [t for t in fig.data if t.name == "1"][0]
    assert list(run_trace.x) == [0, 10, 20, 30]
    assert list(run_trace.y) == [150, 150, 150, 150]


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


def test_plot_resource_utilisation_is_passed_through(resource_use_loggers):
    """Reaches `vidigi.plots.plot_resource_utilisation`, and reproduces the
    hand-computed values from the fixture's docstring: run 1 utilisation 0.25,
    run 2 utilisation 0.5, mean 0.375."""
    trial = TrialLogger(resource_use_loggers)

    fig = trial.plot_resource_utilisation(
        resource_capacities={"treatment_begins": 3}, limit_duration=20
    )

    assert fig.data[0].x == ("treatment_begins",)
    assert fig.data[0].y == pytest.approx((0.375,))


def _two_units_sharing_a_resource_id_logger():
    """One run, two entities using disjoint units (never overlapping in time)
    that nonetheless share resource_id=1 - only unique_resource_id tells them
    apart."""
    logger = EventLogger(run_number=1)
    logger.log_resource_use_start(
        entity_id=1, resource_id=1, unique_resource_id="a_1", time=0.0, event="step_begins"
    )
    logger.log_resource_use_end(
        entity_id=1, resource_id=1, unique_resource_id="a_1", time=10.0, event="step_ends"
    )
    logger.log_resource_use_start(
        entity_id=2, resource_id=1, unique_resource_id="b_1", time=20.0, event="step_begins"
    )
    logger.log_resource_use_end(
        entity_id=2, resource_id=1, unique_resource_id="b_1", time=30.0, event="step_ends"
    )
    return logger


def test_plot_resource_utilisation_resource_col_name_auto_prefers_unique_resource_id():
    """`resource_col_name=None` (the default) draws one bar per
    unique_resource_id whenever the log has that column, rather than
    collapsing units that happen to share a resource_id."""
    trial = TrialLogger([_two_units_sharing_a_resource_id_logger()])

    fig = trial.plot_resource_utilisation(by="resource", limit_duration=40)

    assert set(fig.data[0].x) == {"a_1", "b_1"}


def test_plot_resource_utilisation_resource_col_name_explicit_override_still_works():
    trial = TrialLogger([_two_units_sharing_a_resource_id_logger()])

    fig = trial.plot_resource_utilisation(
        by="resource", resource_col_name="resource_id", limit_duration=40
    )

    assert fig.data[0].x == ("1",)


def test_plot_resource_utilisation_over_time_is_passed_through(resource_use_loggers):
    """Reaches `vidigi.plots.plot_resource_utilisation_over_time`, and
    reproduces the hand-computed occupancy curve from the fixture's
    docstring."""
    trial = TrialLogger(resource_use_loggers)

    fig = trial.plot_resource_utilisation_over_time(
        every_x_time_units=5, limit_duration=20
    )

    run_traces = {trace.name: trace for trace in fig.data if trace.name in ("1", "2")}
    assert list(run_traces["1"].y) == [2, 1, 0, 0, 0]
    assert list(run_traces["2"].y) == [1, 2, 2, 1, 0]
    assert all(trace.line.shape == "hv" for trace in fig.data)


def test_plot_resource_utilisation_over_time_resource_col_name_is_passed_through():
    """`resource_col_name` reaches `vidigi.plots.plot_resource_utilisation_over_time`
    - previously not exposed on this method at all, with no `**kwargs` escape
    hatch either. Proven by pointing it at a nonexistent column and seeing the
    underlying missing-column fallback warning name it."""
    logger = EventLogger(run_number=1)
    logger.log_resource_use_start(entity_id=1, resource_id=1, time=0.0, event="step_begins")
    logger.log_resource_use_end(entity_id=1, resource_id=1, time=10.0, event="step_ends")
    trial = TrialLogger([logger])

    with pytest.warns(UserWarning, match="totally_not_a_column"):
        trial.plot_resource_utilisation_over_time(
            resource_col_name="totally_not_a_column", limit_duration=20
        )


def test_plot_resource_utilisation_over_time_resource_col_name_auto_does_not_warn_when_absent(
    resource_use_loggers,
):
    """No `unique_resource_id` column - `None` must resolve to plain
    `resource_id`, which is genuinely present, rather than triggering the
    missing-column fallback warning."""
    trial = TrialLogger(resource_use_loggers)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        trial.plot_resource_utilisation_over_time(limit_duration=20)

    assert not any(
        "missing from every resource_use row" in str(w.message) for w in caught
    )


def test_plot_warm_up_diagnostic_is_passed_through(resource_use_loggers):
    """Reaches `vidigi.plots.plot_warm_up_diagnostic`, and reproduces the
    hand-computed occupancy curve from the fixture's docstring.

    `limit_duration=10` is deliberately shorter than the fixture's natural
    log end (t=20) - passing 20 here would coincidentally match what
    `resource_occupancy_over_time`'s own default resolves to if
    `limit_duration` were silently dropped on the way through, so that value
    would not prove the passthrough works. Snapshots are [0, 5, 10]; both
    runs' bouts are clipped to the window and so end exactly *at* t=10 -
    counted as free there under the half-open `[start, end)` convention -
    giving ensemble [1.5, 1.5, 0.0]. `window=1` welch then drops the last
    snapshot (output length `3 - 1 = 2`): `[1.5, mean(1.5, 1.5, 0.0)]` =
    `[1.5, 1.0]`. Verified by running the call directly, not by hand alone -
    an earlier version of this test had the wrong expected values because it
    missed the boundary-clipping effect."""
    trial = TrialLogger(resource_use_loggers)

    fig = trial.plot_warm_up_diagnostic(
        series="occupancy",
        event="treatment_begins",
        every_x_time_units=5,
        limit_duration=10,
        windows=(1,),
        show_ensemble=False,
    )

    trace = fig.data[0]
    assert trace.name == "window=1"
    assert list(trace.x) == [0, 5]
    assert list(trace.y) == pytest.approx([1.5, 1.0])


def test_plot_warm_up_diagnostic_duration_series_and_cumulative_method_are_passed_through():
    """`series="duration"` and `method="cumulative"` are the two `plot_warm_up_diagnostic`
    options the occupancy-based test above never exercises. Two runs,
    durations [4, 2, 8] and [6, 4, 2] -> ensemble [5, 3, 5] -> cumulative
    mean [5.0, 4.0, 13/3] (hand-computed and independently verified, same
    fixture shape as `test_plots_warm_up_diagnostic.py::_duration_loggers`)."""
    run1 = EventLogger(run_number=1)
    run2 = EventLogger(run_number=2)
    for logger, durations in ((run1, [4, 2, 8]), (run2, [6, 4, 2])):
        for i, duration in enumerate(durations):
            logger.log_arrival(entity_id=i, time=float(i))
            logger.log_departure(entity_id=i, time=float(i) + duration)
    trial = TrialLogger([run1, run2])

    fig = trial.plot_warm_up_diagnostic(
        series="duration",
        first_event="arrival",
        second_event="depart",
        method="cumulative",
        show_ensemble=False,
    )

    trace = fig.data[0]
    assert trace.name == "cumulative mean"
    assert list(trace.y) == pytest.approx([5.0, 4.0, 13 / 3])


def test_plot_warm_up_diagnostic_show_runs_is_passed_through(resource_use_loggers):
    trial = TrialLogger(resource_use_loggers)

    fig = trial.plot_warm_up_diagnostic(
        series="occupancy",
        event="treatment_begins",
        every_x_time_units=5,
        limit_duration=20,
        windows=(1,),
        show_ensemble=False,
        show_runs=True,
    )

    run_traces = [trace for trace in fig.data if trace.name == "individual runs"]
    assert [list(t.y) for t in run_traces] == [[2, 1, 0, 0, 0], [1, 2, 2, 1, 0]]


def test_plot_warm_up_diagnostic_match_kwarg_reaches_event_durations(rework_loop_logger):
    """`match=` isn't a named parameter on `plot_warm_up_diagnostic` - it
    reaches `vidigi.analysis.event_durations` purely via `**kwargs`, the same
    path `run_col_name` would take. Entity 1 hits `assessment`/`treated`
    twice (see `rework_loop_logger`); `match="occurrence"` must produce two
    observations instead of the one `match="first"` (the default) would."""
    trial = TrialLogger([rework_loop_logger])

    fig = trial.plot_warm_up_diagnostic(
        series="duration",
        first_event="assessment",
        second_event="treated",
        match="occurrence",
        method="cumulative",
        show_ensemble=False,
    )

    assert len(fig.data[0].y) == 2


# --------------------------------------------------------------------------- #
# get_replication_precision / plot_replication_analysis
# --------------------------------------------------------------------------- #


def test_get_replication_precision_is_passed_through(unequal_run_loggers):
    """Reaches `vidigi.analysis.replication_precision` via `event_durations`
    and `replication_means`, and reproduces `unequal_run_loggers`'s own
    hand-computed cumulative means [4.0, 4.5, 6.0]."""
    trial = TrialLogger(unequal_run_loggers)

    result = trial.get_replication_precision("arrival", "depart")

    assert list(result["n_replications"]) == [1, 2, 3]
    assert result["cumulative_mean"].tolist() == pytest.approx([4.0, 4.5, 6.0])
    assert result["half_width"].iloc[2] == pytest.approx(6.5724, abs=1e-3)


def test_get_replication_precision_ci_level_is_passed_through(unequal_run_loggers):
    trial = TrialLogger(unequal_run_loggers)

    result_95 = trial.get_replication_precision("arrival", "depart")
    result_90 = trial.get_replication_precision("arrival", "depart", ci_level=0.90)

    assert result_90["half_width"].iloc[2] != pytest.approx(
        result_95["half_width"].iloc[2], abs=1e-4
    )
    # t_0.95,2 = 2.919986 (published table) vs t_0.975,2 = 4.302653: narrower.
    assert result_90["half_width"].iloc[2] < result_95["half_width"].iloc[2]


def test_get_replication_precision_deviation_threshold_is_passed_through():
    """Every run identical -> deviation is 0.0 from k=2 onward, so a generous
    threshold recommends k=2 while an impossible one (negative - deviation can
    never be negative) never converges."""
    loggers = [EventLogger(run_number=r) for r in (1, 2, 3)]
    for logger in loggers:
        logger.log_arrival(entity_id=1, time=0.0)
        logger.log_departure(entity_id=1, time=5.0)
    trial = TrialLogger(loggers)

    generous = trial.get_replication_precision("arrival", "depart", deviation_threshold=0.5)
    impossible = trial.get_replication_precision("arrival", "depart", deviation_threshold=-0.01)

    assert generous["stays_below_threshold"].any()
    assert not impossible["stays_below_threshold"].any()


def test_get_replication_precision_no_complete_pairs_raises():
    run1 = EventLogger(run_number=1)
    run1.log_arrival(entity_id=1, time=0.0)  # never departs
    run2 = EventLogger(run_number=2)
    run2.log_departure(entity_id=1, time=5.0)  # never arrived
    trial = TrialLogger([run1, run2])

    with pytest.raises(ValueError, match="No complete"):
        trial.get_replication_precision("arrival", "depart")


def test_get_replication_precision_what_is_passed_through():
    """`what="max"` vs the default `"mean"` must reach `replication_means` -
    a run with internal duration variation is needed, since a constant-per-run
    fixture like `unequal_run_loggers` can't distinguish the two."""
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_departure(entity_id=1, time=2.0)
    logger.log_arrival(entity_id=2, time=0.0)
    logger.log_departure(entity_id=2, time=8.0)
    logger2 = EventLogger(run_number=2)
    logger2.log_arrival(entity_id=1, time=0.0)
    logger2.log_departure(entity_id=1, time=10.0)
    trial = TrialLogger([logger, logger2])

    mean_result = trial.get_replication_precision("arrival", "depart", what="mean")
    max_result = trial.get_replication_precision("arrival", "depart", what="max")

    assert mean_result["cumulative_mean"].tolist() == pytest.approx([5.0, 7.5])
    assert max_result["cumulative_mean"].tolist() == pytest.approx([8.0, 9.0])


def test_get_replication_precision_match_kwarg_reaches_event_durations():
    """`match=` reaches `vidigi.analysis.event_durations` via `**kwargs` -
    `match="occurrence"` must give each run two observations for its repeated
    `assessment`/`treated` pair (mean per run = mean(4, 10) = 7.0) instead of
    the single observation `match="first"` (the default) would give (4.0)."""
    loggers = []
    for run_number in (1, 2):
        logger = EventLogger(run_number=run_number)
        logger.log_custom_event(entity_id=1, event_type="milestone", event="assessment", time=1.0)
        logger.log_custom_event(entity_id=1, event_type="milestone", event="treated", time=5.0)
        logger.log_custom_event(entity_id=1, event_type="milestone", event="assessment", time=20.0)
        logger.log_custom_event(entity_id=1, event_type="milestone", event="treated", time=30.0)
        loggers.append(logger)
    trial = TrialLogger(loggers)

    first_result = trial.get_replication_precision("assessment", "treated", match="first")
    occurrence_result = trial.get_replication_precision(
        "assessment", "treated", match="occurrence"
    )

    assert first_result["cumulative_mean"].tolist() == pytest.approx([4.0, 4.0])
    assert occurrence_result["cumulative_mean"].tolist() == pytest.approx([7.0, 7.0])


def test_get_replication_precision_succeeds_at_a_single_replication(two_run_loggers):
    """Unlike `plot_replication_analysis`, `get_replication_precision` has no
    `n >= 2` guard - it returns the same graceful one-row, NaN-spread table
    `vidigi.analysis.replication_precision` gives for any single-replication
    input, rather than raising. This pins that as intentional, not an
    oversight."""
    trial = TrialLogger([two_run_loggers[0]])

    result = trial.get_replication_precision("arrival", "depart")

    assert len(result) == 1
    assert result.loc[0, "cumulative_mean"] == pytest.approx(5.0)
    assert pd.isna(result.loc[0, "half_width"])


def test_plot_replication_analysis_is_passed_through(unequal_run_loggers):
    trial = TrialLogger(unequal_run_loggers)

    fig = trial.plot_replication_analysis("arrival", "depart")

    assert isinstance(fig, go.Figure)
    mean_trace = fig.data[1]
    assert mean_trace.name == "cumulative mean"
    assert list(mean_trace.y) == pytest.approx([4.0, 4.5, 6.0])


def test_plot_replication_analysis_show_deviation_is_passed_through(unequal_run_loggers):
    trial = TrialLogger(unequal_run_loggers)

    with_deviation = trial.plot_replication_analysis("arrival", "depart")
    without_deviation = trial.plot_replication_analysis(
        "arrival", "depart", show_deviation=False
    )

    assert "deviation" in [t.name for t in with_deviation.data]
    assert "deviation" not in [t.name for t in without_deviation.data]


def test_plot_replication_analysis_match_kwarg_reaches_event_durations():
    """`match=` reaches `vidigi.analysis.event_durations` the same way it does
    for `plot_warm_up_diagnostic` above - `match="occurrence"` must give each
    run two observations for its repeated `assessment`/`treated` pair
    (mean per run = mean(4, 10) = 7.0) instead of the single observation
    `match="first"` (the default) would give (duration 4.0 per run)."""
    loggers = []
    for run_number in (1, 2):
        logger = EventLogger(run_number=run_number)
        logger.log_custom_event(entity_id=1, event_type="milestone", event="assessment", time=1.0)
        logger.log_custom_event(entity_id=1, event_type="milestone", event="treated", time=5.0)
        logger.log_custom_event(entity_id=1, event_type="milestone", event="assessment", time=20.0)
        logger.log_custom_event(entity_id=1, event_type="milestone", event="treated", time=30.0)
        loggers.append(logger)
    trial = TrialLogger(loggers)

    first_fig = trial.plot_replication_analysis("assessment", "treated", match="first")
    occurrence_fig = trial.plot_replication_analysis(
        "assessment", "treated", match="occurrence"
    )

    assert list(first_fig.data[1].y) == pytest.approx([4.0, 4.0])
    assert list(occurrence_fig.data[1].y) == pytest.approx([7.0, 7.0])


# --------------------------------------------------------------------------- #
# get_entity_metric_by_arrival / plot_metric_vs_arrival_time
# --------------------------------------------------------------------------- #


def test_get_entity_metric_by_arrival_is_passed_through(unequal_run_loggers):
    trial = TrialLogger(unequal_run_loggers)

    result = trial.get_entity_metric_by_arrival("arrival", "depart")

    assert list(result.columns) == [
        "entity_id",
        "run_number",
        "pathway",
        "occurrence",
        "first_time",
        "second_time",
        "duration",
        "arrival_time",
    ]
    assert list(result["duration"]) == pytest.approx([4] * 2 + [5] * 4 + [9] * 2)


def test_get_entity_metric_by_arrival_arrival_event_is_passed_through():
    """`arrival_event="assessment"` must reach `entity_metric_by_arrival` -
    `rework_loop_logger`'s own event set has no 'arrival' event at all, so
    the default would raise if this kwarg were silently dropped."""
    logger = EventLogger(run_number=1)
    logger.log_custom_event(entity_id=1, event_type="milestone", event="assessment", time=1.0)
    logger.log_custom_event(entity_id=1, event_type="milestone", event="treated", time=5.0)
    trial = TrialLogger([logger])

    result = trial.get_entity_metric_by_arrival(
        "assessment", "treated", arrival_event="assessment"
    )

    assert result["arrival_time"].iloc[0] == pytest.approx(1.0)


def test_plot_metric_vs_arrival_time_is_passed_through(unequal_run_loggers):
    trial = TrialLogger(unequal_run_loggers)

    fig = trial.plot_metric_vs_arrival_time("arrival", "depart")

    assert isinstance(fig, go.Figure)
    # Every entity arrives at t=0.0, so the secondary sort key (entity_id)
    # decides order: entity 1's three runs (4, 5, 9), then entity 2's (4, 5,
    # 9), then run 2's extra entities 3 and 4 (5, 5).
    assert list(fig.data[0].y) == pytest.approx([4, 5, 9, 4, 5, 9, 5, 5])


def test_plot_metric_vs_arrival_time_colour_by_is_passed_through(unequal_run_loggers):
    trial = TrialLogger(unequal_run_loggers)

    fig = trial.plot_metric_vs_arrival_time("arrival", "depart", colour_by="run")

    by_name = {trace.name: sorted(trace.y) for trace in fig.data}
    assert by_name == {"1": [4.0, 4.0], "2": [5.0, 5.0, 5.0, 5.0], "3": [9.0, 9.0]}


def test_plot_metric_vs_arrival_time_rolling_window_is_passed_through():
    logger = EventLogger(run_number=1)
    for i, (arrival, duration) in enumerate([(0.0, 10.0), (2.0, 20.0), (4.0, 30.0)], start=1):
        logger.log_arrival(entity_id=i, time=arrival)
        logger.log_departure(entity_id=i, time=arrival + duration)
    trial = TrialLogger([logger])

    no_trend = trial.plot_metric_vs_arrival_time("arrival", "depart")
    with_trend = trial.plot_metric_vs_arrival_time("arrival", "depart", rolling_window=1)

    assert "rolling mean" not in [t.name for t in no_trend.data]
    trend = [t for t in with_trend.data if t.name == "rolling mean"][0]
    assert list(trend.y) == pytest.approx([15.0, 20.0, 25.0])


def test_plot_metric_vs_arrival_time_rolling_time_is_passed_through():
    logger = EventLogger(run_number=1)
    for i, (arrival, duration) in enumerate([(0.0, 10.0), (2.0, 20.0), (4.0, 30.0)], start=1):
        logger.log_arrival(entity_id=i, time=arrival)
        logger.log_departure(entity_id=i, time=arrival + duration)
    trial = TrialLogger([logger])

    fig = trial.plot_metric_vs_arrival_time("arrival", "depart", rolling_time=2.5)

    trend = [t for t in fig.data if t.name == "rolling mean"][0]
    assert list(trend.y) == pytest.approx([15.0, 20.0, 25.0])


def test_plot_metric_vs_arrival_time_warm_up_is_passed_through():
    logger = EventLogger(run_number=1)
    for i, (arrival, duration) in enumerate([(0.0, 10.0), (10.0, 20.0)], start=1):
        logger.log_arrival(entity_id=i, time=arrival)
        logger.log_departure(entity_id=i, time=arrival + duration)
    trial = TrialLogger([logger])

    unfiltered = trial.plot_metric_vs_arrival_time("arrival", "depart")
    filtered = trial.plot_metric_vs_arrival_time("arrival", "depart", warm_up=5)

    assert list(unfiltered.data[0].y) == pytest.approx([10.0, 20.0])
    assert list(filtered.data[0].y) == pytest.approx([20.0])
