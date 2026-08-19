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

from vidigi.logging import TrialLogger
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


def test_across_entities_and_across_runs_together_are_the_meaningful_pair(
    unequal_run_loggers,
):
    """The two must differ - proves `across` actually changes which mean is drawn,
    not just which error bar is attached."""
    entities_fig = plot_metric_bar(
        _trial_df(unequal_run_loggers), _PAIRS, across="entities"
    )
    runs_fig = plot_metric_bar(_trial_df(unequal_run_loggers), _PAIRS, across="runs")

    assert entities_fig.data[0].y[0] == pytest.approx(5.75)
    assert runs_fig.data[0].y[0] == pytest.approx(6.0)


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
