"""Tests for `vidigi.plots.plot_resource_utilisation` and
`plot_resource_utilisation_over_time` as free functions.

`TrialLogger`'s two delegating methods are tested separately in
`test_logging_triallogger.py`.
"""

import plotly.graph_objects as go
import pytest

from vidigi.logging import EventLogger, TrialLogger
from vidigi.plots import plot_resource_utilisation, plot_resource_utilisation_over_time


def _trial_df(loggers):
    return TrialLogger(loggers).to_dataframe()


# --------------------------------------------------------------------------- #
# plot_resource_utilisation
# --------------------------------------------------------------------------- #


def test_returns_a_figure(resource_use_loggers):
    fig = plot_resource_utilisation(
        _trial_df(resource_use_loggers),
        resource_capacities={"treatment_begins": 3},
        limit_duration=20,
    )
    assert isinstance(fig, go.Figure)


def test_by_step_bar_is_the_mean_of_the_two_runs_utilisation(resource_use_loggers):
    """Hand-computed from the fixture's docstring: run 1 utilisation 0.25, run
    2 utilisation 0.5 - the bar is their mean, and the CI half-width comes
    from the n=2, t_0.975,1 = 12.7062047 published value."""
    fig = plot_resource_utilisation(
        _trial_df(resource_use_loggers),
        by="step",
        resource_capacities={"treatment_begins": 3},
        limit_duration=20,
    )

    assert fig.data[0].x == ("treatment_begins",)
    assert fig.data[0].y == pytest.approx((0.375,))
    assert round(fig.data[0].error_y.array[0], 3) == 1.588


def test_by_resource_capacity_is_always_one_no_capacity_kwargs_needed(
    resource_use_loggers,
):
    """`by="resource"` needs no capacity route at all - capacity is always 1 -
    so `utilisation` (the default metric) must already be resolved, not NaN."""
    fig = plot_resource_utilisation(
        _trial_df(resource_use_loggers), by="resource", limit_duration=20
    )

    result = dict(zip(fig.data[0].x, fig.data[0].y))
    assert result == pytest.approx({"1": 0.25, "2": 0.625, "3": 0.25})


def test_by_run_draws_a_single_bar_labelled_all_resources(resource_use_loggers):
    fig = plot_resource_utilisation(
        _trial_df(resource_use_loggers),
        by="run",
        resource_capacities={"treatment_begins": 3},
        limit_duration=20,
    )

    assert fig.data[0].x == ("All resources",)
    assert fig.data[0].y == pytest.approx((0.375,))


def test_utilisation_falls_back_to_mean_in_use_when_capacity_unresolved(
    resource_use_loggers,
):
    with pytest.warns(UserWarning, match="falling back to metric='mean_in_use'"):
        fig = plot_resource_utilisation(
            _trial_df(resource_use_loggers), by="step", limit_duration=20
        )

    # busy_time totals 15 (run 1) and 30 (run 2) over a window of 20, so
    # mean_in_use is 0.75 and 1.5 - mean 1.125.
    assert fig.data[0].y == pytest.approx((1.125,))
    assert "mean_in_use" in fig.layout.title.text


def test_metric_busy_time_skips_the_utilisation_fallback_and_hline(resource_use_loggers):
    fig = plot_resource_utilisation(
        _trial_df(resource_use_loggers), by="step", metric="busy_time", limit_duration=20
    )

    assert fig.data[0].y == pytest.approx((22.5,))
    assert len(fig.layout.shapes) == 0


def test_utilisation_metric_adds_a_dashed_line_at_one(resource_use_loggers):
    fig = plot_resource_utilisation(
        _trial_df(resource_use_loggers),
        by="step",
        resource_capacities={"treatment_begins": 3},
        limit_duration=20,
    )

    assert len(fig.layout.shapes) == 1
    assert fig.layout.shapes[0].y0 == fig.layout.shapes[0].y1 == 1.0
    assert fig.layout.shapes[0].line.dash == "dash"


def test_sort_by_value_orders_bars_descending(resource_use_loggers):
    """'other_step' sorts before 'treatment_begins' alphabetically - the
    default (`sort_by=None`) group order - but has the *lower* utilisation, so
    this only passes if `sort_by="value"` actually reorders rather than
    happening to agree with the natural order."""
    logger_extra = EventLogger(run_number=1)
    logger_extra.log_resource_use_start(
        entity_id=99, resource_id=99, time=0.0, event="other_step"
    )
    logger_extra.log_resource_use_end(
        entity_id=99, resource_id=99, time=18.0, event="other_ends"
    )
    df = _trial_df(resource_use_loggers + [logger_extra])
    capacities = {"treatment_begins": 1, "other_step": 1}

    fig_unsorted = plot_resource_utilisation(
        df, by="step", resource_capacities=capacities, limit_duration=20
    )
    assert list(fig_unsorted.data[0].x) == ["other_step", "treatment_begins"]

    fig_sorted = plot_resource_utilisation(
        df,
        by="step",
        resource_capacities=capacities,
        limit_duration=20,
        sort_by="value",
    )
    assert list(fig_sorted.data[0].x) == ["treatment_begins", "other_step"]


def test_show_runs_overlays_one_point_per_run(resource_use_loggers):
    fig = plot_resource_utilisation(
        _trial_df(resource_use_loggers),
        by="step",
        resource_capacities={"treatment_begins": 3},
        limit_duration=20,
        show_runs=True,
    )

    run_traces = [trace for trace in fig.data if trace.name == "Runs"]
    assert len(run_traces) == 1
    assert sorted(run_traces[0].y) == pytest.approx([0.25, 0.5])


def test_show_runs_false_omits_the_runs_trace(resource_use_loggers):
    fig = plot_resource_utilisation(
        _trial_df(resource_use_loggers),
        by="step",
        resource_capacities={"treatment_begins": 3},
        limit_duration=20,
        show_runs=False,
    )

    assert not any(trace.name == "Runs" for trace in fig.data)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"by": "nonsense"},
        {"metric": "nonsense"},
        {"error_bars": "nonsense"},
        {"sort_by": "nonsense"},
    ],
)
def test_invalid_options_raise(kwargs, resource_use_loggers):
    with pytest.raises(ValueError):
        plot_resource_utilisation(_trial_df(resource_use_loggers), limit_duration=20, **kwargs)


def test_bar_chart_no_resource_use_events_raises(two_run_loggers):
    with pytest.raises(ValueError, match="No resource_use/resource_use_end pairs"):
        plot_resource_utilisation(_trial_df(two_run_loggers))


# --------------------------------------------------------------------------- #
# plot_resource_utilisation_over_time
# --------------------------------------------------------------------------- #


def test_matches_the_hand_computed_occupancy_curve_and_uses_hv_steps(resource_use_loggers):
    fig = plot_resource_utilisation_over_time(
        _trial_df(resource_use_loggers), every_x_time_units=5, limit_duration=20
    )

    run_traces = {trace.name: trace for trace in fig.data if trace.name in ("1", "2")}
    assert list(run_traces["1"].x) == [0, 5, 10, 15, 20]
    assert list(run_traces["1"].y) == [2, 1, 0, 0, 0]
    assert list(run_traces["2"].x) == [0, 5, 10, 15, 20]
    assert list(run_traces["2"].y) == [1, 2, 2, 1, 0]

    mean_trace = [trace for trace in fig.data if trace.name == "Mean"][0]
    assert list(mean_trace.y) == pytest.approx([1.5, 1.5, 1.0, 0.5, 0.0])

    assert all(trace.line.shape == "hv" for trace in fig.data)


def test_show_all_runs_false_only_plots_the_mean(resource_use_loggers):
    fig = plot_resource_utilisation_over_time(
        _trial_df(resource_use_loggers),
        every_x_time_units=5,
        limit_duration=20,
        show_all_runs=False,
    )

    assert len(fig.data) == 1
    assert fig.data[0].name == "Mean"


def test_as_proportion_divides_by_capacity(resource_use_loggers):
    fig = plot_resource_utilisation_over_time(
        _trial_df(resource_use_loggers),
        every_x_time_units=5,
        limit_duration=20,
        as_proportion=True,
        resource_capacities={"treatment_begins": 2},
        show_all_runs=False,
    )

    mean_trace = fig.data[0]
    assert list(mean_trace.y) == pytest.approx([0.75, 0.75, 0.5, 0.25, 0.0])
    assert "proportion" in fig.layout.yaxis.title.text


def test_as_proportion_raises_if_capacity_is_missing(resource_use_loggers):
    with pytest.raises(ValueError, match="resolvable capacity"):
        plot_resource_utilisation_over_time(
            _trial_df(resource_use_loggers),
            every_x_time_units=5,
            limit_duration=20,
            as_proportion=True,
        )


def test_over_time_no_resource_use_events_raises(two_run_loggers):
    with pytest.raises(ValueError, match="No resource_use/resource_use_end pairs"):
        plot_resource_utilisation_over_time(_trial_df(two_run_loggers))
