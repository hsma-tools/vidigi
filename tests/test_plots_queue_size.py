"""Tests for `vidigi.plots.plot_queue_size` as a free function.

`TrialLogger.plot_queue_size` is a thin delegator over this; its own tests in
`test_logging_triallogger.py` remain the proof that the delegation is
byte-identical to the pre-extraction behaviour.
"""

import plotly.graph_objects as go
import pytest

from vidigi.logging import EventLogger, TrialLogger
from vidigi.plots import plot_queue_size


def _trial_df(loggers):
    return TrialLogger(loggers).to_dataframe()


def _two_event_log():
    """One run, one entity queuing at 'waiting', one at 'triage', both t=0-10."""
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_queue(entity_id=1, event="waiting", time=0.0)
    logger.log_departure(entity_id=1, time=10.0)
    logger.log_arrival(entity_id=2, time=0.0)
    logger.log_queue(entity_id=2, event="triage", time=0.0)
    logger.log_departure(entity_id=2, time=10.0)
    return TrialLogger([logger]).to_dataframe()


def test_returns_a_figure(two_run_loggers):
    fig = plot_queue_size(_trial_df(two_run_loggers), ["waiting"], limit_duration=20)
    assert isinstance(fig, go.Figure)


def test_show_all_runs_false_returns_a_figure(two_run_loggers):
    fig = plot_queue_size(
        _trial_df(two_run_loggers),
        ["waiting"],
        limit_duration=20,
        show_all_runs=False,
    )
    assert isinstance(fig, go.Figure)


def test_reports_the_true_queue_length(long_queue_logger):
    fig = plot_queue_size(
        _trial_df([long_queue_logger]),
        ["waiting"],
        limit_duration=30,
        every_x_time_units=10,
    )

    assert list(fig.data[0].x) == [0, 10, 20, 30]
    assert list(fig.data[0].y) == [150, 150, 150, 150]


def test_warm_up_trims_the_plotted_window(warm_up_log):
    fig = plot_queue_size(
        warm_up_log,
        ["waiting"],
        limit_duration=200,
        every_x_time_units=10,
        warm_up=100,
        show_all_runs=False,
    )

    assert min(fig.data[0].x) == 100


def test_px_kwargs_still_reach_plotly_express(two_run_loggers):
    """The pre-existing `**kwargs` meaning (plotly express passthrough) is kept,
    rather than being repurposed for column-name overrides, so no caller's
    existing styling kwargs silently start doing something else.
    """
    fig = plot_queue_size(
        _trial_df(two_run_loggers),
        ["waiting"],
        limit_duration=20,
        title="Custom title",
    )

    assert fig.layout.title.text == "Custom title"


# --------------------------------------------------------------------------- #
# backend="go" - opt-in alternative with deterministic trace identity
# --------------------------------------------------------------------------- #


def test_invalid_backend_raises(two_run_loggers):
    with pytest.raises(ValueError, match="Invalid backend"):
        plot_queue_size(
            _trial_df(two_run_loggers),
            ["waiting"],
            limit_duration=20,
            backend="nonsense",
        )


@pytest.mark.parametrize("spelling", ["go", "GO", "graph objects", "plotly go"])
def test_go_backend_matches_case_insensitively_and_every_spelling(
    two_run_loggers, spelling
):
    fig = plot_queue_size(
        _trial_df(two_run_loggers), ["waiting"], limit_duration=20, backend=spelling
    )
    assert isinstance(fig, go.Figure)


def test_go_backend_reports_the_true_queue_length(long_queue_logger):
    fig = plot_queue_size(
        _trial_df([long_queue_logger]),
        ["waiting"],
        limit_duration=30,
        every_x_time_units=10,
        backend="go",
    )

    run_trace = [t for t in fig.data if t.name == "1"][0]
    mean_trace = [t for t in fig.data if t.name == "Mean"][0]
    assert list(run_trace.x) == [0, 10, 20, 30]
    assert list(run_trace.y) == [150, 150, 150, 150]
    assert list(mean_trace.y) == [150, 150, 150, 150]


def test_go_backend_plots_an_empty_queue_as_zero_per_run(emptying_queue_loggers):
    fig = plot_queue_size(
        _trial_df(emptying_queue_loggers),
        ["waiting"],
        limit_duration=30,
        every_x_time_units=10,
        backend="go",
    )

    by_run = {trace.name: list(trace.y) for trace in fig.data if trace.name != "Mean"}
    assert by_run["1"] == [1, 1, 0, 0]
    assert by_run["2"] == [0, 0, 1, 1]
    assert all(list(trace.x) == [0, 10, 20, 30] for trace in fig.data)


def test_go_backend_mean_includes_runs_with_an_empty_queue(emptying_queue_loggers):
    fig = plot_queue_size(
        _trial_df(emptying_queue_loggers),
        ["waiting"],
        limit_duration=30,
        every_x_time_units=10,
        show_all_runs=False,
        backend="go",
    )

    assert len(fig.data) == 1
    assert list(fig.data[0].y) == [0.5, 0.5, 0.5, 0.5]


def test_go_backend_warm_up_trims_the_plotted_window(warm_up_log):
    fig = plot_queue_size(
        warm_up_log,
        ["waiting"],
        limit_duration=200,
        every_x_time_units=10,
        warm_up=100,
        show_all_runs=False,
        backend="go",
    )

    assert min(fig.data[0].x) == 100


def test_go_backend_facets_multiple_events_with_clean_titles():
    """Unlike the express path, go builds subplot titles directly via
    `make_subplots`, so no `event=` prefix ever needs stripping off afterwards.
    """
    fig = plot_queue_size(
        _two_event_log(),
        ["waiting", "triage"],
        limit_duration=10,
        every_x_time_units=10,
        backend="go",
    )

    titles = [ann.text for ann in fig.layout.annotations]
    assert titles == ["waiting", "triage"]

    by_axis = {}
    for trace in fig.data:
        by_axis.setdefault(trace.yaxis, []).append((trace.name, list(trace.y)))

    assert ("1", [1, 0]) in by_axis["y"]
    assert ("Mean", [1, 0]) in by_axis["y"]
    assert ("1", [1, 0]) in by_axis["y2"]
    assert ("Mean", [1, 0]) in by_axis["y2"]


def test_go_backend_warns_and_ignores_px_kwargs(two_run_loggers):
    with pytest.warns(UserWarning, match="does not use"):
        fig = plot_queue_size(
            _trial_df(two_run_loggers),
            ["waiting"],
            limit_duration=20,
            backend="go",
            title="Ignored",
        )

    assert fig.layout.title.text is None
