"""Tests for `vidigi.plots.plot_warm_up_diagnostic` as a free function.

`TrialLogger.plot_warm_up_diagnostic`'s delegation is tested separately in
`test_logging_triallogger.py`.
"""

import warnings

import plotly.graph_objects as go
import pytest

from vidigi.logging import EventLogger, TrialLogger
from vidigi.plots import plot_warm_up_diagnostic


def _trial_df(loggers):
    return TrialLogger(loggers).to_dataframe()


def _duration_loggers():
    """Two runs, three entities each, arriving in the same order (t=0,1,2).

    Durations: run 1 = [4, 2, 8], run 2 = [6, 4, 2]. Ensemble mean = [5, 3, 5]
    - not monotonic, so distinguishes the shrinking left-edge window from an
    interior one, same as `welch_series`.
    """
    run1 = EventLogger(run_number=1)
    run2 = EventLogger(run_number=2)
    for logger, durations in ((run1, [4, 2, 8]), (run2, [6, 4, 2])):
        for i, duration in enumerate(durations):
            logger.log_arrival(entity_id=i, time=float(i))
            logger.log_departure(entity_id=i, time=float(i) + duration)
    return [run1, run2]


def test_returns_a_figure(resource_use_loggers):
    fig = plot_warm_up_diagnostic(
        _trial_df(resource_use_loggers),
        series="occupancy",
        event="treatment_begins",
        windows=(1,),
    )

    assert isinstance(fig, go.Figure)


# --------------------------------------------------------------------------- #
# series="occupancy" - exact arrays, both methods
# --------------------------------------------------------------------------- #


def test_occupancy_welch_matches_the_hand_computed_array(resource_use_loggers):
    """Ensemble = [1.5, 1.5, 1.0, 0.5, 0.0] (snapshots 0,5,10,15,20); window=1
    welch = [1.5, 4/3, 1.0, 0.5]."""
    fig = plot_warm_up_diagnostic(
        _trial_df(resource_use_loggers),
        series="occupancy",
        event="treatment_begins",
        every_x_time_units=5,
        limit_duration=20,
        windows=(1,),
        show_ensemble=False,
    )

    trace = fig.data[0]
    assert trace.name == "window=1"
    assert list(trace.x) == [0, 5, 10, 15]
    assert list(trace.y) == pytest.approx([1.5, 4 / 3, 1.0, 0.5])


def test_occupancy_cumulative_matches_the_hand_computed_array(resource_use_loggers):
    fig = plot_warm_up_diagnostic(
        _trial_df(resource_use_loggers),
        series="occupancy",
        event="treatment_begins",
        every_x_time_units=5,
        limit_duration=20,
        method="cumulative",
        show_ensemble=False,
    )

    trace = fig.data[0]
    assert trace.name == "cumulative mean"
    assert list(trace.x) == [0, 5, 10, 15, 20]
    assert list(trace.y) == pytest.approx([1.5, 1.5, 4 / 3, 1.125, 0.9])


def test_occupancy_show_ensemble_adds_the_raw_trace(resource_use_loggers):
    fig = plot_warm_up_diagnostic(
        _trial_df(resource_use_loggers),
        series="occupancy",
        event="treatment_begins",
        every_x_time_units=5,
        limit_duration=20,
        method="cumulative",
        show_ensemble=True,
    )

    assert len(fig.data) == 2
    assert fig.data[0].name == "ensemble mean"
    assert list(fig.data[0].y) == pytest.approx([1.5, 1.5, 1.0, 0.5, 0.0])


def test_show_runs_defaults_to_off(resource_use_loggers):
    fig = plot_warm_up_diagnostic(
        _trial_df(resource_use_loggers),
        series="occupancy",
        event="treatment_begins",
        every_x_time_units=5,
        limit_duration=20,
        windows=(1,),
        show_ensemble=False,
    )

    assert not any(trace.name == "individual runs" for trace in fig.data)


def test_occupancy_show_runs_adds_one_trace_per_run_at_the_hand_computed_values(
    resource_use_loggers,
):
    """Run 1's occupancy is [2, 1, 0, 0, 0], run 2's is [1, 2, 2, 1, 0] - see
    `resource_use_loggers`'s own docstring. Each must appear as its own raw
    trace, not just folded into the ensemble mean."""
    fig = plot_warm_up_diagnostic(
        _trial_df(resource_use_loggers),
        series="occupancy",
        event="treatment_begins",
        every_x_time_units=5,
        limit_duration=20,
        windows=(1,),
        show_ensemble=False,
        show_runs=True,
    )

    run_traces = [trace for trace in fig.data if trace.name == "individual runs"]
    assert len(run_traces) == 2
    assert [list(t.y) for t in run_traces] == [[2, 1, 0, 0, 0], [1, 2, 2, 1, 0]]
    assert [list(t.x) for t in run_traces] == [[0, 5, 10, 15, 20]] * 2


def test_show_runs_traces_share_one_legend_entry(resource_use_loggers):
    """A full per-run legend (one entry per replication) would swamp the
    windows=/method entries that are the actual point of this plot - so every
    run's trace shares a single legendgroup/name, and only the first one is
    marked to actually appear in the legend."""
    fig = plot_warm_up_diagnostic(
        _trial_df(resource_use_loggers),
        series="occupancy",
        event="treatment_begins",
        every_x_time_units=5,
        limit_duration=20,
        windows=(1,),
        show_ensemble=False,
        show_runs=True,
    )

    run_traces = [trace for trace in fig.data if trace.name == "individual runs"]
    assert all(trace.legendgroup == "individual runs" for trace in run_traces)
    assert [trace.showlegend for trace in run_traces] == [True, False]


def test_duration_show_runs_uses_each_runs_own_full_length(unequal_run_loggers):
    """Run 1 has 2 entities, run 2 has 4, run 3 has 2 (see
    `unequal_run_loggers`) - `_ensemble_mean` truncates the *summary* traces
    to the shortest run (2), but each run's own raw trace must keep its full
    length, not be truncated to match."""
    fig = plot_warm_up_diagnostic(
        _trial_df(unequal_run_loggers),
        series="duration",
        first_event="arrival",
        second_event="depart",
        method="cumulative",
        show_ensemble=False,
        show_runs=True,
    )

    run_traces = [trace for trace in fig.data if trace.name == "individual runs"]
    assert sorted(len(t.y) for t in run_traces) == [2, 2, 4]
    for trace in run_traces:
        assert list(trace.x) == list(range(1, len(trace.y) + 1))


def test_occupancy_none_method_matches_the_ensemble_mean(resource_use_loggers):
    fig = plot_warm_up_diagnostic(
        _trial_df(resource_use_loggers),
        series="occupancy",
        event="treatment_begins",
        every_x_time_units=5,
        limit_duration=20,
        method="none",
        show_ensemble=False,
    )

    trace = fig.data[0]
    assert trace.name == "ensemble mean (unsmoothed)"
    assert list(trace.x) == [0, 5, 10, 15, 20]
    assert list(trace.y) == pytest.approx([1.5, 1.5, 1.0, 0.5, 0.0])


def test_occupancy_none_method_ignores_show_ensemble_to_avoid_a_duplicate_trace(
    resource_use_loggers,
):
    """`method="none"` already draws the raw ensemble mean as its one trace -
    `show_ensemble=True`'s reference line would be a second, identical trace,
    so it must not be drawn here."""
    fig = plot_warm_up_diagnostic(
        _trial_df(resource_use_loggers),
        series="occupancy",
        event="treatment_begins",
        every_x_time_units=5,
        limit_duration=20,
        method="none",
        show_ensemble=True,
    )

    assert len(fig.data) == 1
    assert fig.data[0].name == "ensemble mean (unsmoothed)"


def test_occupancy_multiple_windows_draw_one_trace_each(resource_use_loggers):
    fig = plot_warm_up_diagnostic(
        _trial_df(resource_use_loggers),
        series="occupancy",
        event="treatment_begins",
        every_x_time_units=5,
        limit_duration=20,
        windows=(1, 2),
        show_ensemble=False,
    )

    assert [trace.name for trace in fig.data] == ["window=1", "window=2"]


def test_occupancy_unknown_event_raises_with_available_steps(resource_use_loggers):
    with pytest.raises(ValueError, match="treatment_begins"):
        plot_warm_up_diagnostic(
            _trial_df(resource_use_loggers), series="occupancy", event="nope"
        )


def test_occupancy_unknown_event_close_to_a_real_one_gets_the_hint(resource_use_loggers):
    """`"nope"` (above) isn't close enough to any real step for
    `difflib.get_close_matches` to suggest anything - this exercises the
    branch where it does."""
    with pytest.raises(ValueError, match=r"did you mean 'treatment_begins'"):
        plot_warm_up_diagnostic(
            _trial_df(resource_use_loggers),
            series="occupancy",
            event="treatment_begin",
        )


# --------------------------------------------------------------------------- #
# series="queue" - wiring/pass-through
# --------------------------------------------------------------------------- #


def test_queue_series_pulls_the_named_queue(emptying_queue_loggers):
    fig = plot_warm_up_diagnostic(
        _trial_df(emptying_queue_loggers),
        series="queue",
        event="waiting",
        every_x_time_units=10,
        limit_duration=30,
        method="cumulative",
        show_ensemble=False,
    )

    trace = fig.data[0]
    assert list(trace.x) == [0, 10, 20, 30]
    assert list(trace.y) == pytest.approx([0.5, 0.5, 0.5, 0.5])


def test_queue_series_limit_duration_none_resolves_to_latest_time_without_warning(
    emptying_queue_loggers,
):
    """`emptying_queue_loggers`' latest time is 35 (run 2's depart) - deliberately
    not the round number 30 the test above uses, so `limit_duration=None` auto-
    resolving to it is distinguishable from a coincidence. `event_log[...].max()`
    is a numpy float64; passed raw into `queue_size_over_time` that would trigger
    its "provided as float64... rounding to nearest integer" warning on every
    call with no explicit `limit_duration` - `plot_warm_up_diagnostic` rounds it
    itself first specifically to avoid that."""
    df = _trial_df(emptying_queue_loggers)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fig_auto = plot_warm_up_diagnostic(
            df,
            series="queue",
            event="waiting",
            every_x_time_units=10,
            method="cumulative",
            show_ensemble=False,
        )

    assert not any(
        "rounding to nearest integer" in str(w.message) for w in caught
    )

    fig_explicit = plot_warm_up_diagnostic(
        df,
        series="queue",
        event="waiting",
        every_x_time_units=10,
        limit_duration=35,
        method="cumulative",
        show_ensemble=False,
    )

    assert list(fig_auto.data[0].x) == list(fig_explicit.data[0].x)
    assert list(fig_auto.data[0].y) == pytest.approx(list(fig_explicit.data[0].y))


# --------------------------------------------------------------------------- #
# series="duration" - exact arrays, no time axis
# --------------------------------------------------------------------------- #


def test_duration_welch_matches_the_hand_computed_array():
    fig = plot_warm_up_diagnostic(
        _trial_df(_duration_loggers()),
        series="duration",
        first_event="arrival",
        second_event="depart",
        windows=(1,),
        show_ensemble=False,
    )

    trace = fig.data[0]
    assert list(trace.x) == [1, 2]
    assert list(trace.y) == pytest.approx([5.0, 13 / 3])


def test_duration_cumulative_matches_the_hand_computed_array():
    fig = plot_warm_up_diagnostic(
        _trial_df(_duration_loggers()),
        series="duration",
        first_event="arrival",
        second_event="depart",
        method="cumulative",
        show_ensemble=False,
    )

    trace = fig.data[0]
    assert list(trace.x) == [1, 2, 3]
    assert list(trace.y) == pytest.approx([5.0, 4.0, 13 / 3])


def test_duration_x_axis_is_arrival_order_not_time():
    fig = plot_warm_up_diagnostic(
        _trial_df(_duration_loggers()),
        series="duration",
        first_event="arrival",
        second_event="depart",
        method="cumulative",
        show_ensemble=False,
    )

    assert fig.layout.xaxis.title.text == "nth entity (arrival order)"


# --------------------------------------------------------------------------- #
# Shape-only assertions against a nonstationary series - never a warm-up value
# --------------------------------------------------------------------------- #


def test_nonstationary_welch_curve_rises_then_flattens(nonstationary_logger):
    fig = plot_warm_up_diagnostic(
        _trial_df(nonstationary_logger),
        series="duration",
        first_event="arrival",
        second_event="depart",
        windows=(5,),
        show_ensemble=False,
    )

    y = list(fig.data[0].y)
    assert y[0] < y[-1]
    assert y[-1] == pytest.approx(5.0, abs=0.5)
    assert y == sorted(y)  # deterministic, identical runs -> exactly non-decreasing


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def test_unknown_series_raises(resource_use_loggers):
    with pytest.raises(ValueError, match="series"):
        plot_warm_up_diagnostic(_trial_df(resource_use_loggers), series="bogus")


def test_queue_series_without_event_raises(resource_use_loggers):
    with pytest.raises(ValueError, match="event"):
        plot_warm_up_diagnostic(_trial_df(resource_use_loggers), series="queue")


def test_occupancy_series_without_event_raises(resource_use_loggers):
    with pytest.raises(ValueError, match="event"):
        plot_warm_up_diagnostic(_trial_df(resource_use_loggers), series="occupancy")


def test_duration_series_without_both_events_raises(resource_use_loggers):
    with pytest.raises(ValueError, match="first_event"):
        plot_warm_up_diagnostic(
            _trial_df(resource_use_loggers), series="duration", first_event="arrival"
        )


def test_duration_series_with_event_raises(resource_use_loggers):
    with pytest.raises(ValueError, match="event"):
        plot_warm_up_diagnostic(
            _trial_df(resource_use_loggers),
            series="duration",
            first_event="arrival",
            second_event="depart",
            event="waiting",
        )


def test_queue_series_with_first_event_raises(resource_use_loggers):
    with pytest.raises(ValueError, match="first_event"):
        plot_warm_up_diagnostic(
            _trial_df(resource_use_loggers),
            series="queue",
            event="waiting",
            first_event="arrival",
        )
