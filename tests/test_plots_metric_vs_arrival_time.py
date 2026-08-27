"""Tests for `vidigi.plots.plot_metric_vs_arrival_time`."""

import plotly.graph_objects as go
import pytest

from vidigi.analysis import entity_metric_by_arrival
from vidigi.logging import EventLogger, TrialLogger
from vidigi.plots import plot_metric_vs_arrival_time


def _trial_df(loggers):
    return TrialLogger(loggers).to_dataframe()


def _logger_with_points(points, run_number=1):
    """One run where entity i arrives at points[i-1][0] and departs
    points[i-1][1] time units later - `first_event="arrival"` coincides with
    `arrival_event`, so `duration == points[i-1][1]` exactly."""
    logger = EventLogger(run_number=run_number)
    for i, (arrival_time, duration) in enumerate(points, start=1):
        logger.log_arrival(entity_id=i, time=arrival_time)
        logger.log_departure(entity_id=i, time=arrival_time + duration)
    return logger


# Evenly spaced arrivals (every 2 time units), durations chosen with no simple
# pattern so a rolling mean is a genuine check, not a coincidence.
POINTS = [(0.0, 10.0), (2.0, 20.0), (4.0, 30.0), (6.0, 25.0), (8.0, 15.0), (10.0, 5.0)]


def test_returns_a_figure(unequal_run_loggers):
    fig = plot_metric_vs_arrival_time(_trial_df(unequal_run_loggers), "arrival", "depart")
    assert isinstance(fig, go.Figure)


def test_scatter_matches_entity_metric_by_arrival_output(nonstationary_logger):
    event_log = _trial_df([nonstationary_logger[0]])  # run 1 only
    fig = plot_metric_vs_arrival_time(event_log, "arrival", "depart")

    expected = entity_metric_by_arrival(event_log, "arrival", "depart").sort_values(
        "arrival_time"
    )
    assert list(fig.data[0].x) == pytest.approx(list(expected["arrival_time"]))
    assert list(fig.data[0].y) == pytest.approx(list(expected["duration"]))


def test_colour_by_run_groups_the_scatter(unequal_run_loggers):
    fig = plot_metric_vs_arrival_time(
        _trial_df(unequal_run_loggers), "arrival", "depart", colour_by="run"
    )
    by_name = {trace.name: sorted(trace.y) for trace in fig.data}
    assert by_name == {"1": [4.0, 4.0], "2": [5.0, 5.0, 5.0, 5.0], "3": [9.0, 9.0]}


def test_colour_by_pathway_missing_column_raises(unequal_run_loggers):
    with pytest.raises(ValueError, match="pathway"):
        plot_metric_vs_arrival_time(
            _trial_df(unequal_run_loggers), "arrival", "depart", colour_by="pathway"
        )


def test_rolling_window_exact_arithmetic_with_edge_shrinkage():
    fig = plot_metric_vs_arrival_time(
        _trial_df([_logger_with_points(POINTS)]), "arrival", "depart", rolling_window=1
    )
    trend = [t for t in fig.data if t.name == "rolling mean"][0]

    # half-width=1, both edges shrink to a 2-point window rather than being dropped.
    expected = [15.0, 20.0, 25.0, 70.0 / 3, 15.0, 10.0]
    assert list(trend.x) == pytest.approx([0.0, 2.0, 4.0, 6.0, 8.0, 10.0])
    assert list(trend.y) == pytest.approx(expected)


def test_rolling_time_exact_arithmetic_with_edge_shrinkage():
    fig = plot_metric_vs_arrival_time(
        _trial_df([_logger_with_points(POINTS)]), "arrival", "depart", rolling_time=5.0
    )
    trend = [t for t in fig.data if t.name == "rolling mean"][0]

    # half-span=5.0 over arrivals spaced 2 apart captures a *different* window
    # shape from rolling_window=1 above (up to 2 neighbours each side, not 1) -
    # proves this is a genuinely distinct code path, not a coincidental match.
    expected = [20.0, 21.25, 20.0, 19.0, 18.75, 15.0]
    assert list(trend.y) == pytest.approx(expected)


def test_rolling_window_and_rolling_time_together_raises(unequal_run_loggers):
    with pytest.raises(ValueError, match="mutually exclusive"):
        plot_metric_vs_arrival_time(
            _trial_df(unequal_run_loggers),
            "arrival",
            "depart",
            rolling_window=1,
            rolling_time=1.0,
        )


@pytest.mark.parametrize("rolling_window", [0, -1])
def test_non_positive_rolling_window_raises(unequal_run_loggers, rolling_window):
    with pytest.raises(ValueError, match="rolling_window"):
        plot_metric_vs_arrival_time(
            _trial_df(unequal_run_loggers), "arrival", "depart", rolling_window=rolling_window
        )


@pytest.mark.parametrize("rolling_time", [0, -1.0])
def test_non_positive_rolling_time_raises(unequal_run_loggers, rolling_time):
    with pytest.raises(ValueError, match="rolling_time"):
        plot_metric_vs_arrival_time(
            _trial_df(unequal_run_loggers), "arrival", "depart", rolling_time=rolling_time
        )


def test_warm_up_filters_by_arrival_time_not_first_time():
    """entity 1 arrives early (t=0) but its `wait_begins` fires late (t=50);
    entity 2 arrives late (t=100) but its `wait_begins` fires early (t=5).
    `warm_up=10` must exclude entity 1 (arrival_time=0 < 10) and keep entity 2
    (arrival_time=100 >= 10) - the opposite of what filtering by `first_time`
    would do (entity 1's first_time=50 >= 10 would survive; entity 2's
    first_time=5 < 10 would not)."""
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_custom_event(entity_id=1, event_type="milestone", event="wait_begins", time=50.0)
    logger.log_departure(entity_id=1, time=60.0)
    logger.log_arrival(entity_id=2, time=100.0)
    logger.log_custom_event(entity_id=2, event_type="milestone", event="wait_begins", time=5.0)
    logger.log_departure(entity_id=2, time=8.0)

    fig = plot_metric_vs_arrival_time(
        _trial_df([logger]), "wait_begins", "depart", warm_up=10
    )

    assert list(fig.data[0].y) == pytest.approx([3.0])  # entity 2's duration only


def test_warm_up_applied_before_smoothing():
    """A point just past the warm_up boundary must have a rolling mean
    unaffected by points excluded before it - if smoothing ran on the
    unfiltered series first, the excluded point's huge duration (100) would
    leak into the surviving points' rolling mean."""
    points = [(0.0, 100.0), (5.0, 10.0), (10.0, 20.0)]
    fig = plot_metric_vs_arrival_time(
        _trial_df([_logger_with_points(points)]),
        "arrival",
        "depart",
        warm_up=5,
        rolling_window=1,
    )
    trend = [t for t in fig.data if t.name == "rolling mean"][0]

    assert list(trend.x) == pytest.approx([5.0, 10.0])
    assert list(trend.y) == pytest.approx([15.0, 15.0])


def test_warm_up_zero_is_a_no_op(unequal_run_loggers):
    event_log = _trial_df(unequal_run_loggers)
    default_fig = plot_metric_vs_arrival_time(event_log, "arrival", "depart")
    explicit_fig = plot_metric_vs_arrival_time(event_log, "arrival", "depart", warm_up=0)

    assert list(default_fig.data[0].y) == pytest.approx(list(explicit_fig.data[0].y))


def test_no_points_survive_filtering_raises():
    logger = _logger_with_points([(0.0, 5.0)])
    with pytest.raises(ValueError, match="No points"):
        plot_metric_vs_arrival_time(
            _trial_df([logger]), "arrival", "depart", warm_up=100
        )


def test_match_kwarg_reaches_event_durations():
    logger = EventLogger(run_number=1)
    logger.log_custom_event(entity_id=1, event_type="milestone", event="arrival", time=0.0)
    logger.log_custom_event(entity_id=1, event_type="milestone", event="assessment", time=1.0)
    logger.log_custom_event(entity_id=1, event_type="milestone", event="assessment", time=20.0)

    first_fig = plot_metric_vs_arrival_time(
        _trial_df([logger]), "arrival", "assessment", match="first"
    )
    last_fig = plot_metric_vs_arrival_time(
        _trial_df([logger]), "arrival", "assessment", match="last"
    )

    assert list(first_fig.data[0].y) == pytest.approx([1.0])
    assert list(last_fig.data[0].y) == pytest.approx([20.0])


def test_title_reaches_the_figure(unequal_run_loggers):
    fig = plot_metric_vs_arrival_time(
        _trial_df(unequal_run_loggers), "arrival", "depart", title="my title"
    )
    assert fig.layout.title.text == "my title"


def test_marker_size_and_line_width_default_to_the_documented_values(unequal_run_loggers):
    fig = plot_metric_vs_arrival_time(
        _trial_df(unequal_run_loggers), "arrival", "depart", rolling_window=1
    )
    scatter = fig.data[0]
    trend = [t for t in fig.data if t.name == "rolling mean"][0]
    assert scatter.marker.size == 6
    assert trend.line.width == 3


def test_marker_size_and_line_width_reach_the_traces(unequal_run_loggers):
    fig = plot_metric_vs_arrival_time(
        _trial_df(unequal_run_loggers),
        "arrival",
        "depart",
        rolling_window=1,
        marker_size=2,
        line_width=1,
    )
    scatter = fig.data[0]
    trend = [t for t in fig.data if t.name == "rolling mean"][0]
    assert scatter.marker.size == 2
    assert trend.line.width == 1
