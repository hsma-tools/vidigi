"""Tests for `vidigi.plots.plot_metric`, the `go`-based replacement for the
deprecated `plot_metric_bar`.

`kind="bar"` is checked directly against `plot_metric_bar`'s own output for
the same inputs, so the "drop-in replacement" claim in the deprecation
message is actually true, not just asserted. `kind="box"`/`"violin"` and
`highlight_bands` are new behaviour with no `plot_metric_bar` equivalent to
compare against, so those get their own assertions.
"""

import warnings

import plotly.graph_objects as go
import pytest

from vidigi.logging import EventLogger, TrialLogger
from vidigi.plots import plot_metric, plot_metric_bar

_PAIRS = [{"label": "A", "first_event": "arrival", "second_event": "depart"}]


def _trial_df(loggers):
    return TrialLogger(loggers).to_dataframe()


def _call_plot_metric_bar(*args, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return plot_metric_bar(*args, **kwargs)


def test_returns_a_figure(two_run_loggers):
    fig = plot_metric(_trial_df(two_run_loggers), _PAIRS)
    assert isinstance(fig, go.Figure)


def test_calling_it_emits_no_deprecation_warning(two_run_loggers):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        plot_metric(_trial_df(two_run_loggers), _PAIRS)
    assert not any(issubclass(w.category, DeprecationWarning) for w in caught)


# --------------------------------------------------------------------------- #
# kind="bar" matches plot_metric_bar exactly
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("across", ["entities", "runs"])
def test_bar_values_match_plot_metric_bar(unequal_run_loggers, across):
    df = _trial_df(unequal_run_loggers)
    old_fig = _call_plot_metric_bar(df, _PAIRS, across=across)
    new_fig = plot_metric(df, _PAIRS, kind="bar", across=across)
    assert list(new_fig.data[0].y) == pytest.approx(list(old_fig.data[0].y))


def test_bar_error_bars_match_plot_metric_bar(unequal_run_loggers):
    df = _trial_df(unequal_run_loggers)
    old_fig = _call_plot_metric_bar(df, _PAIRS, across="runs", error_bars="ci")
    new_fig = plot_metric(df, _PAIRS, kind="bar", across="runs", error_bars="ci")
    assert list(new_fig.data[0].error_y.array) == pytest.approx(
        list(old_fig.data[0].error_y.array)
    )


def test_bar_show_runs_matches_plot_metric_bar(unequal_run_loggers):
    df = _trial_df(unequal_run_loggers)
    old_fig = _call_plot_metric_bar(df, _PAIRS, across="runs", show_runs=True)
    new_fig = plot_metric(df, _PAIRS, kind="bar", across="runs", show_runs=True)
    old_scatter = [t for t in old_fig.data if isinstance(t, go.Scatter)][0]
    new_scatter = [t for t in new_fig.data if isinstance(t, go.Scatter)][0]
    assert sorted(new_scatter.y) == pytest.approx(sorted(old_scatter.y))


def test_one_bar_per_pair(two_run_loggers):
    pairs = [
        {"label": "A", "first_event": "arrival", "second_event": "depart"},
        {"label": "B", "first_event": "arrival", "second_event": "waiting"},
    ]
    fig = plot_metric(_trial_df(two_run_loggers), pairs)
    assert list(fig.data[0].x) == ["A", "B"]


# --------------------------------------------------------------------------- #
# kind="box" / "violin"
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kind", ["box", "violin"])
def test_box_and_violin_carry_the_per_run_values(unequal_run_loggers, kind):
    """Run means for this fixture are [4, 5, 9]."""
    fig = plot_metric(_trial_df(unequal_run_loggers), _PAIRS, kind=kind, across="runs")
    assert sorted(fig.data[0].y) == pytest.approx([4.0, 5.0, 9.0])


def test_box_kind_uses_a_go_box_trace(unequal_run_loggers):
    fig = plot_metric(_trial_df(unequal_run_loggers), _PAIRS, kind="box", across="runs")
    assert isinstance(fig.data[0], go.Box)


def test_violin_kind_uses_a_go_violin_trace(unequal_run_loggers):
    fig = plot_metric(
        _trial_df(unequal_run_loggers), _PAIRS, kind="violin", across="runs"
    )
    assert isinstance(fig.data[0], go.Violin)


def test_box_kind_with_across_entities_raises(unequal_run_loggers):
    with pytest.raises(ValueError, match='across="runs"'):
        plot_metric(
            _trial_df(unequal_run_loggers), _PAIRS, kind="box", across="entities"
        )


def test_box_kind_with_default_across_raises(unequal_run_loggers):
    """`across` defaults to `"entities"` - a caller who only sets `kind="box"`
    and forgets `across="runs"` must get the same clear error, not a silent
    single-point box."""
    with pytest.raises(ValueError, match='across="runs"'):
        plot_metric(_trial_df(unequal_run_loggers), _PAIRS, kind="box")


def test_error_bars_with_box_kind_raises(unequal_run_loggers):
    with pytest.raises(ValueError, match="error_bars"):
        plot_metric(
            _trial_df(unequal_run_loggers),
            _PAIRS,
            kind="box",
            across="runs",
            error_bars="ci",
        )


def test_show_runs_sets_boxpoints_all_for_box(unequal_run_loggers):
    fig = plot_metric(
        _trial_df(unequal_run_loggers),
        _PAIRS,
        kind="box",
        across="runs",
        show_runs=True,
    )
    assert fig.data[0].boxpoints == "all"


def test_show_runs_sets_points_all_for_violin(unequal_run_loggers):
    fig = plot_metric(
        _trial_df(unequal_run_loggers),
        _PAIRS,
        kind="violin",
        across="runs",
        show_runs=True,
    )
    assert fig.data[0].points == "all"


def test_show_runs_false_leaves_boxpoints_unset_for_box(unequal_run_loggers):
    """Mutation-proof companion to the show_runs=True test above: if the
    `if show_runs:` guard around `trace_kwargs.update(points_kwarg)` were
    dropped, `boxpoints` would be `"all"` here too."""
    fig = plot_metric(
        _trial_df(unequal_run_loggers),
        _PAIRS,
        kind="box",
        across="runs",
        show_runs=False,
    )
    assert fig.data[0].boxpoints != "all"


def test_invalid_kind_raises(two_run_loggers):
    with pytest.raises(ValueError, match="`kind`"):
        plot_metric(_trial_df(two_run_loggers), _PAIRS, kind="nonsense")


# --------------------------------------------------------------------------- #
# highlight_bands
# --------------------------------------------------------------------------- #


def test_highlight_bands_on_bar_kind_adds_shapes(two_run_loggers):
    fig = plot_metric(
        _trial_df(two_run_loggers),
        _PAIRS,
        kind="bar",
        highlight_bands=[{"upper": 3, "colour": "green"}],
    )
    assert len(fig.layout.shapes) == 2  # hrect + one boundary hline


def test_highlight_bands_on_box_kind_adds_shapes(unequal_run_loggers):
    fig = plot_metric(
        _trial_df(unequal_run_loggers),
        _PAIRS,
        kind="box",
        across="runs",
        highlight_bands=[{"upper": 3, "colour": "green"}],
    )
    assert len(fig.layout.shapes) == 2


def test_no_highlight_bands_adds_no_shapes(two_run_loggers):
    fig = plot_metric(_trial_df(two_run_loggers), _PAIRS)
    assert fig.layout.shapes == ()


# --------------------------------------------------------------------------- #
# error paths shared with plot_metric_bar's own validation
# --------------------------------------------------------------------------- #


def test_across_runs_raises_when_no_run_has_a_complete_pair():
    run1 = EventLogger(run_number=1)
    run1.log_arrival(entity_id=1, time=0.0)

    run2 = EventLogger(run_number=2)
    run2.log_departure(entity_id=1, time=5.0)

    trial_df = TrialLogger([run1, run2]).to_dataframe()

    with pytest.raises(ValueError, match="No complete"):
        plot_metric(trial_df, _PAIRS, across="runs")


def test_exclude_incomplete_false_with_across_runs_raises(two_run_loggers):
    with pytest.raises(ValueError, match="exclude_incomplete=False"):
        plot_metric(
            _trial_df(two_run_loggers), _PAIRS, across="runs", exclude_incomplete=False
        )
