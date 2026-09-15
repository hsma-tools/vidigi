"""Tests for `vidigi.plots.plot_scenario_comparison` as a free function.

`TrialLogger.plot_event_duration_comparison` is a thin delegator over this;
its own tests in `test_logging_scenario_comparison.py` are the proof the
delegation forwards every argument.
"""

import pandas as pd
import plotly.graph_objects as go
import pytest

from vidigi.analysis import (
    compare_replication_values,
    event_durations,
    replication_means,
)
from vidigi.logging import TrialLogger
from vidigi.plots import plot_scenario_comparison


def _trial_df(loggers):
    return TrialLogger(loggers).to_dataframe()


def test_returns_a_figure(unequal_run_loggers, two_run_loggers):
    fig = plot_scenario_comparison(
        _trial_df(unequal_run_loggers), _trial_df(two_run_loggers), "arrival", "depart"
    )
    assert isinstance(fig, go.Figure)


def test_bar_values_match_compare_replication_values(unequal_run_loggers, two_run_loggers):
    """Cross-check the plotted bar heights and error bars against the analysis
    function's own output directly, rather than re-deriving expectations."""
    log_a = _trial_df(unequal_run_loggers)
    log_b = _trial_df(two_run_loggers)

    fig = plot_scenario_comparison(log_a, log_b, "arrival", "depart")

    values_a = replication_means(event_durations(log_a, "arrival", "depart"))["value"]
    values_b = replication_means(event_durations(log_b, "arrival", "depart"))["value"]
    expected = compare_replication_values(values_a, values_b)

    bar = fig.data[0]
    assert list(bar.y) == pytest.approx([expected.mean_a, expected.mean_b])
    assert list(bar.error_y.array) == pytest.approx(
        [expected.ci_a.half_width, expected.ci_b.half_width]
    )


def test_bar_labels_use_label_a_and_label_b(unequal_run_loggers, two_run_loggers):
    fig = plot_scenario_comparison(
        _trial_df(unequal_run_loggers),
        _trial_df(two_run_loggers),
        "arrival",
        "depart",
        label_a="baseline",
        label_b="extra staff",
    )

    assert list(fig.data[0].x) == ["baseline", "extra staff"]


def test_no_complete_pairs_in_one_scenario_raises(unequal_run_loggers):
    """Both events are present (so the "event not found" check passes), but
    entity 1's arrival has no matching depart and entity 2's depart has no
    matching arrival - zero complete pairs."""
    log_b = pd.DataFrame(
        [
            {
                "time": 0,
                "entity_id": 1,
                "event_type": "arrival_departure",
                "event": "arrival",
                "run_number": 1,
            },
            {
                "time": 5,
                "entity_id": 2,
                "event_type": "arrival_departure",
                "event": "depart",
                "run_number": 1,
            },
        ]
    )

    with pytest.raises(ValueError, match="No complete"):
        plot_scenario_comparison(_trial_df(unequal_run_loggers), log_b, "arrival", "depart")
