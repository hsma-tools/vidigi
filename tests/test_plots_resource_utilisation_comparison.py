"""Tests for `vidigi.plots.plot_resource_utilisation_comparison` as a free function.

`TrialLogger.plot_resource_utilisation_comparison` is a thin delegator over
this; its own tests in `test_logging_scenario_comparison.py` are the proof
the delegation forwards every argument (including defaulting `scenario_a`/
`scenario_b` from each trial's `.scenario`).
"""

import plotly.graph_objects as go
import pytest

from vidigi.analysis import compare_replication_values, resource_utilisation
from vidigi.logging import TrialLogger
from vidigi.plots import plot_resource_utilisation_comparison


def _trial_df(loggers):
    return TrialLogger(loggers).to_dataframe()


def test_returns_a_figure(resource_use_loggers):
    log = _trial_df(resource_use_loggers)
    fig = plot_resource_utilisation_comparison(
        log, log, resource_capacities={"treatment_begins": 3}, limit_duration=20
    )
    assert isinstance(fig, go.Figure)


def test_bar_values_match_compare_replication_values(resource_use_loggers):
    """Cross-check the plotted bar heights and error bars against the analysis
    function's own output directly, rather than re-deriving expectations."""
    log_a = _trial_df(resource_use_loggers)
    log_b = _trial_df(resource_use_loggers)

    fig = plot_resource_utilisation_comparison(
        log_a, log_b, resource_capacities={"treatment_begins": 3}, limit_duration=20
    )

    values_a = resource_utilisation(
        log_a, by="run", resource_capacities={"treatment_begins": 3}, limit_duration=20
    )["utilisation"]
    values_b = resource_utilisation(
        log_b, by="run", resource_capacities={"treatment_begins": 3}, limit_duration=20
    )["utilisation"]
    expected = compare_replication_values(values_a, values_b)

    bar = fig.data[0]
    assert list(bar.y) == pytest.approx([expected.mean_a, expected.mean_b])
    assert list(bar.error_y.array) == pytest.approx(
        [expected.ci_a.half_width, expected.ci_b.half_width]
    )


def test_hand_computed_utilisation_matches_the_fixture(resource_use_loggers):
    """`resource_use_loggers`'s own docstring hand-computes utilisation 0.25
    (run 1) and 0.5 (run 2), mean 0.375, for both sides here."""
    log = _trial_df(resource_use_loggers)
    fig = plot_resource_utilisation_comparison(
        log, log, resource_capacities={"treatment_begins": 3}, limit_duration=20
    )
    assert list(fig.data[0].y) == pytest.approx([0.375, 0.375])


def test_metric_selects_the_resource_utilisation_column(resource_use_loggers):
    log = _trial_df(resource_use_loggers)
    fig = plot_resource_utilisation_comparison(
        log,
        log,
        metric="busy_time",
        resource_capacities={"treatment_begins": 3},
        limit_duration=20,
    )
    expected = resource_utilisation(
        log, by="run", resource_capacities={"treatment_begins": 3}, limit_duration=20
    )["busy_time"]
    assert list(fig.data[0].y) == pytest.approx([expected.mean(), expected.mean()])


def test_unknown_metric_raises(resource_use_loggers):
    log = _trial_df(resource_use_loggers)
    with pytest.raises(ValueError, match="metric"):
        plot_resource_utilisation_comparison(log, log, metric="not_a_real_metric")


def test_bar_labels_use_label_a_and_label_b(resource_use_loggers):
    log = _trial_df(resource_use_loggers)
    fig = plot_resource_utilisation_comparison(
        log,
        log,
        resource_capacities={"treatment_begins": 3},
        limit_duration=20,
        label_a="baseline",
        label_b="extra staff",
    )
    assert list(fig.data[0].x) == ["baseline", "extra staff"]


def test_scenario_a_and_scenario_b_resolve_capacity_independently(
    resource_use_loggers, scenario_with_resources
):
    """`scenario_a`/`scenario_b`, combined with a shared `resource_map`, let
    each side resolve capacity from its own scenario object - the free-
    function equivalent of each `TrialLogger`'s own attached `.scenario`."""
    log = _trial_df(resource_use_loggers)
    resource_map = {"treatment_begins": "n_cubicles"}

    fig = plot_resource_utilisation_comparison(
        log,
        log,
        resource_map=resource_map,
        scenario_a=scenario_with_resources,
        scenario_b={"n_cubicles": 6},
        limit_duration=20,
    )
    # Mean busy time is 22.5 over 20 time units: divide by each capacity,
    # 3 and 6. Reusing either scenario for both sides must change the result.
    assert list(fig.data[0].y) == pytest.approx([0.375, 0.1875])


def test_a_log_with_no_resource_use_at_all_compares_as_zero_not_an_error(
    resource_use_loggers, no_departure_log
):
    """`resource_utilisation(by="run")` always reports at least one row - a
    genuine `busy_time`/`utilisation` of `0` for a log with no resource use
    at all, never an empty frame (see its own "real zero, not a missing
    row" convention) - so a scenario with nothing to compare is not an
    error here, unlike the event-duration comparison's "no complete pairs"
    case."""
    log_a = _trial_df(resource_use_loggers)

    fig = plot_resource_utilisation_comparison(
        log_a, no_departure_log, resource_capacities={"treatment_begins": 3},
        limit_duration=20,
    )
    assert fig.data[0].y[1] == pytest.approx(0.0)


def test_highlight_bands_adds_shapes(resource_use_loggers):
    fig = plot_resource_utilisation_comparison(
        _trial_df(resource_use_loggers),
        _trial_df(resource_use_loggers),
        resource_capacities={"treatment_begins": 3},
        limit_duration=20,
        highlight_bands=[{"upper": 0.1, "colour": "green", "label": "idle"}],
    )
    assert len(fig.layout.shapes) == 2  # hrect + one boundary hline
    assert any(t.name == "idle" for t in fig.data)


def test_no_highlight_bands_adds_no_shapes(resource_use_loggers):
    fig = plot_resource_utilisation_comparison(
        _trial_df(resource_use_loggers),
        _trial_df(resource_use_loggers),
        resource_capacities={"treatment_begins": 3},
        limit_duration=20,
    )
    assert fig.layout.shapes == ()
