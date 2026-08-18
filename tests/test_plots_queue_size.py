"""Tests for `vidigi.plots.plot_queue_size` as a free function.

`TrialLogger.plot_queue_size` is a thin delegator over this; its own tests in
`test_logging_triallogger.py` remain the proof that the delegation is
byte-identical to the pre-extraction behaviour.
"""

import plotly.graph_objects as go

from vidigi.logging import TrialLogger
from vidigi.plots import plot_queue_size


def _trial_df(loggers):
    return TrialLogger(loggers).to_dataframe()


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
