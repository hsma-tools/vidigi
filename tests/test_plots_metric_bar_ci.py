"""Tests for `vidigi.plots.plot_metric_bar` as a free function.

`TrialLogger.plot_metric_bar` is a thin delegator over this; its own tests in
`test_logging_triallogger.py` remain the proof that the delegation is
byte-identical to the pre-extraction behaviour at defaults.
"""

import sys
import typing

import numpy as np
import plotly.graph_objects as go
import pytest

from vidigi.logging import EventLogger, TrialLogger
from vidigi.plots import Across, ErrorBars, plot_metric_bar

_PAIRS = [{"label": "A", "first_event": "arrival", "second_event": "depart"}]


def _trial_df(loggers):
    return TrialLogger(loggers).to_dataframe()


def test_returns_a_figure(two_run_loggers):
    fig = plot_metric_bar(_trial_df(two_run_loggers), _PAIRS)
    assert isinstance(fig, go.Figure)


def test_one_bar_per_pair(two_run_loggers):
    pairs = [
        {"label": "A", "first_event": "arrival", "second_event": "depart"},
        {"label": "B", "first_event": "arrival", "second_event": "waiting"},
    ]
    fig = plot_metric_bar(_trial_df(two_run_loggers), pairs)
    assert list(fig.data[0].x) == ["A", "B"]


def test_across_entities_gives_the_pooled_mean(unequal_run_loggers):
    fig = plot_metric_bar(_trial_df(unequal_run_loggers), _PAIRS, across="entities")
    assert fig.data[0].y == pytest.approx((5.75,))


def test_across_runs_gives_the_mean_of_run_means(unequal_run_loggers):
    fig = plot_metric_bar(_trial_df(unequal_run_loggers), _PAIRS, across="runs")
    assert fig.data[0].y == pytest.approx((6.0,))


def test_across_runs_with_ci_error_bars_matches_the_hand_computed_half_width(
    unequal_run_loggers,
):
    fig = plot_metric_bar(
        _trial_df(unequal_run_loggers), _PAIRS, across="runs", error_bars="ci"
    )
    assert fig.data[0].y == pytest.approx((6.0,))
    assert round(fig.data[0].error_y.array[0], 3) == 6.572


def test_ci_level_reaches_the_figure(unequal_run_loggers):
    """No prior test passes a non-default `ci_level` - pins that it actually
    reaches the underlying `mean_confidence_interval` call rather than being
    dropped somewhere in the delegation."""
    fig_95 = plot_metric_bar(
        _trial_df(unequal_run_loggers), _PAIRS, across="runs", error_bars="ci"
    )
    fig_90 = plot_metric_bar(
        _trial_df(unequal_run_loggers),
        _PAIRS,
        across="runs",
        error_bars="ci",
        ci_level=0.90,
    )

    # t_0.95,2 = 2.919986, from a published Student's t table (90% CI, df=2).
    assert round(fig_90.data[0].error_y.array[0], 3) == 4.460
    assert fig_90.data[0].error_y.array[0] != pytest.approx(
        fig_95.data[0].error_y.array[0], abs=1e-3
    )


def test_across_runs_raises_when_no_run_has_a_complete_pair():
    """Every run individually has an unmatched event - `event_durations` still
    finds both event names in the log (so does not raise there), but no run
    contributes a single complete pairing for `replication_means` to average."""
    run1 = EventLogger(run_number=1)
    run1.log_arrival(entity_id=1, time=0.0)  # never departs

    run2 = EventLogger(run_number=2)
    run2.log_departure(entity_id=1, time=5.0)  # never arrived

    trial_df = TrialLogger([run1, run2]).to_dataframe()

    with pytest.raises(ValueError, match="No complete"):
        plot_metric_bar(trial_df, _PAIRS, across="runs")


def test_across_runs_with_a_single_run_gives_nan_ci_and_warns(two_run_loggers):
    """A single replication cannot support a confidence interval -
    `mean_confidence_interval` warns and returns a NaN half-width rather than
    raising, and that must survive the trip through `plot_metric_bar`."""
    single_run_df = TrialLogger([two_run_loggers[0]]).to_dataframe()

    with pytest.warns(UserWarning, match="at least 2"):
        fig = plot_metric_bar(single_run_df, _PAIRS, across="runs", error_bars="ci")

    assert np.isnan(fig.data[0].error_y.array[0])


def test_across_runs_with_a_single_run_sd_and_se_are_also_nan(two_run_loggers):
    """`"sd"`/`"se"` don't go through `mean_confidence_interval`'s warning path -
    a single-point sample standard deviation (ddof=1) is NaN by construction,
    with no warning, so this checks that path separately."""
    single_run_df = TrialLogger([two_run_loggers[0]]).to_dataframe()

    sd_fig = plot_metric_bar(single_run_df, _PAIRS, across="runs", error_bars="sd")
    se_fig = plot_metric_bar(single_run_df, _PAIRS, across="runs", error_bars="se")

    assert np.isnan(sd_fig.data[0].error_y.array[0])
    assert np.isnan(se_fig.data[0].error_y.array[0])


@pytest.mark.parametrize(
    "error_bars,expected_plus,expected_minus",
    [
        ("sd", np.sqrt(7), np.sqrt(7)),
        ("se", np.sqrt(7) / np.sqrt(3), np.sqrt(7) / np.sqrt(3)),
        ("range", 9.0 - 6.0, 6.0 - 4.0),
        ("iqr", 7.0 - 6.0, 6.0 - 4.5),
    ],
)
def test_every_error_bar_kind_matches_independently_computed_values(
    unequal_run_loggers, error_bars, expected_plus, expected_minus
):
    """Run values are [4, 5, 9]: quartiles (linear interpolation, pandas default)
    are Q1=4.5, Q3=7.0."""
    fig = plot_metric_bar(
        _trial_df(unequal_run_loggers),
        _PAIRS,
        across="runs",
        error_bars=error_bars,
    )
    assert fig.data[0].error_y.array[0] == pytest.approx(expected_plus, abs=1e-4)
    assert fig.data[0].error_y.arrayminus[0] == pytest.approx(expected_minus, abs=1e-4)


def test_show_runs_overlays_one_point_per_run(unequal_run_loggers):
    fig = plot_metric_bar(
        _trial_df(unequal_run_loggers),
        _PAIRS,
        across="runs",
        show_runs=True,
    )
    scatter_traces = [t for t in fig.data if isinstance(t, go.Scatter)]
    assert len(scatter_traces) == 1
    assert sorted(scatter_traces[0].y) == [4.0, 5.0, 9.0]


def test_kwargs_still_forward_to_plotly_express_bar(two_run_loggers):
    """`**kwargs` on `plot_metric_bar` is unlike every other new-style plot
    function - it keeps forwarding to `plotly.express.bar` unchanged, since the
    committed example notebook already relies on `title=`/`width=` reaching it."""
    fig = plot_metric_bar(_trial_df(two_run_loggers), _PAIRS, title="Custom", width=800)
    assert fig.layout.title.text == "Custom"
    assert fig.layout.width == 800


def test_error_bars_without_across_runs_raises(two_run_loggers):
    with pytest.raises(ValueError, match='across="runs"'):
        plot_metric_bar(_trial_df(two_run_loggers), _PAIRS, error_bars="ci")


def test_show_runs_without_across_runs_raises(two_run_loggers):
    with pytest.raises(ValueError, match='across="runs"'):
        plot_metric_bar(_trial_df(two_run_loggers), _PAIRS, show_runs=True)


def test_exclude_incomplete_false_with_across_runs_raises(two_run_loggers):
    with pytest.raises(ValueError, match="exclude_incomplete=False"):
        plot_metric_bar(
            _trial_df(two_run_loggers),
            _PAIRS,
            across="runs",
            exclude_incomplete=False,
        )


def test_invalid_across_raises(two_run_loggers):
    with pytest.raises(ValueError, match="`across`"):
        plot_metric_bar(_trial_df(two_run_loggers), _PAIRS, across="nonsense")


def test_invalid_error_bars_raises(two_run_loggers):
    with pytest.raises(ValueError, match="`error_bars`"):
        plot_metric_bar(
            _trial_df(two_run_loggers), _PAIRS, across="runs", error_bars="nonsense"
        )


def test_entity_counting_what_is_rejected_across_runs(unequal_run_loggers):
    with pytest.raises(ValueError, match="per-replication statistic"):
        plot_metric_bar(
            _trial_df(unequal_run_loggers), _PAIRS, across="runs", what="count"
        )


def test_missing_scipy_raises_a_legible_import_error(monkeypatch, unequal_run_loggers):
    monkeypatch.setitem(sys.modules, "scipy", None)
    monkeypatch.setitem(sys.modules, "scipy.stats", None)

    with pytest.raises(ImportError, match=r"pip install vidigi\[stats\]"):
        plot_metric_bar(
            _trial_df(unequal_run_loggers), _PAIRS, across="runs", error_bars="ci"
        )


@pytest.mark.parametrize("across", typing.get_args(Across))
def test_every_across_literal_is_accepted(across, unequal_run_loggers):
    """The annotation must not advertise an `across` the runtime check rejects."""
    fig = plot_metric_bar(_trial_df(unequal_run_loggers), _PAIRS, across=across)
    assert isinstance(fig, go.Figure)


@pytest.mark.parametrize("error_bars", typing.get_args(ErrorBars))
def test_every_error_bars_literal_is_accepted(error_bars, unequal_run_loggers):
    """The annotation must not advertise an `error_bars` the runtime check rejects."""
    fig = plot_metric_bar(
        _trial_df(unequal_run_loggers), _PAIRS, across="runs", error_bars=error_bars
    )
    assert isinstance(fig, go.Figure)


def test_ci_kind_bites_if_error_bars_are_swapped_for_sd(unequal_run_loggers):
    """Mutation-proof: 'ci' and 'sd' give different half-widths for this fixture -
    proves the dispatch actually looks at `error_bars`, not just that a bar is
    attached at all."""
    ci_fig = plot_metric_bar(
        _trial_df(unequal_run_loggers), _PAIRS, across="runs", error_bars="ci"
    )
    sd_fig = plot_metric_bar(
        _trial_df(unequal_run_loggers), _PAIRS, across="runs", error_bars="sd"
    )
    assert ci_fig.data[0].error_y.array[0] != pytest.approx(
        sd_fig.data[0].error_y.array[0], abs=1e-4
    )
