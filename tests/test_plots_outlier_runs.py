"""Tests for `vidigi.plots._beeswarm_offsets` and `plot_outlier_runs`.

`_beeswarm_offsets`'s only real invariant is "no two values sharing a row are
closer than `spacing`" - that's what's checked directly, rather than pinning
exact offset numbers, which are an implementation detail of the greedy
placement order. `plot_outlier_runs` itself is checked against
`vidigi.analysis.flag_outlier_runs`'s own output directly.
"""

import numpy as np
import plotly.graph_objects as go
import pytest

from vidigi.analysis import flag_outlier_runs
from vidigi.logging import EventLogger, TrialLogger
from vidigi.plots import _beeswarm_offsets, plot_outlier_runs


def _trial_df(loggers):
    return TrialLogger(loggers).to_dataframe()


def _run_logger(run_number, duration):
    logger = EventLogger(run_number=run_number)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_departure(entity_id=1, time=float(duration))
    return logger


# --------------------------------------------------------------------------- #
# _beeswarm_offsets
# --------------------------------------------------------------------------- #


def _rows_never_share_a_close_pair(values, offsets, spacing):
    by_row = {}
    for v, o in zip(values, offsets):
        by_row.setdefault(o, []).append(v)
    for row_values in by_row.values():
        row_values = sorted(row_values)
        for a, b in zip(row_values, row_values[1:]):
            if b - a < spacing:
                return False
    return True


def test_widely_spaced_values_all_share_row_zero():
    values = np.array([0.0, 10.0, 20.0, 30.0])
    offsets = _beeswarm_offsets(values, spacing=1.0)
    assert (offsets == 0).all()


def test_a_dense_cluster_is_spread_across_multiple_rows():
    values = np.sort(np.array([1.0, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3]))
    offsets = _beeswarm_offsets(values, spacing=0.2)
    assert len(set(offsets)) > 1
    assert _rows_never_share_a_close_pair(values, offsets, spacing=0.2)


def test_no_two_values_within_spacing_share_a_row_random_data():
    rng = np.random.default_rng(0)
    values = np.sort(rng.uniform(0, 5, size=50))
    offsets = _beeswarm_offsets(values, spacing=0.1)
    assert _rows_never_share_a_close_pair(values, offsets, spacing=0.1)


# --------------------------------------------------------------------------- #
# plot_outlier_runs
# --------------------------------------------------------------------------- #


@pytest.fixture
def six_run_loggers_with_one_outlier():
    """Same fixture as `test_analysis_outliers.py`: Q1=9.625, Q3=10.875,
    1.5x fence=[7.75, 12.75] - only run 6 (13.0) is flagged."""
    durations = [10.0, 11.0, 9.0, 10.5, 9.5, 13.0]
    return [_run_logger(i + 1, d) for i, d in enumerate(durations)]


def test_returns_a_figure(six_run_loggers_with_one_outlier):
    fig = plot_outlier_runs(_trial_df(six_run_loggers_with_one_outlier), "arrival", "depart")
    assert isinstance(fig, go.Figure)


def test_points_partition_by_outlier_flag_matching_flag_outlier_runs(
    six_run_loggers_with_one_outlier,
):
    from vidigi.analysis import event_durations, replication_means

    event_log = _trial_df(six_run_loggers_with_one_outlier)
    fig = plot_outlier_runs(event_log, "arrival", "depart")

    expected = flag_outlier_runs(
        replication_means(event_durations(event_log, "arrival", "depart"))
    )
    expected_normal = sorted(expected.loc[~expected["is_outlier"], "value"])
    expected_outlier = sorted(expected.loc[expected["is_outlier"], "value"])

    traces = {t.name: sorted(t.x) for t in fig.data if t.type == "scatter"}
    assert traces["run"] == pytest.approx(expected_normal)
    assert traces["outlier run"] == pytest.approx(expected_outlier)


def test_no_outliers_omits_the_outlier_trace():
    loggers = [_run_logger(i + 1, 10.0) for i in range(5)]
    fig = plot_outlier_runs(_trial_df(loggers), "arrival", "depart")
    names = [t.name for t in fig.data]
    assert "outlier run" not in names
    assert "run" in names


def test_fence_shapes_use_the_hand_computed_fence_values(six_run_loggers_with_one_outlier):
    fig = plot_outlier_runs(_trial_df(six_run_loggers_with_one_outlier), "arrival", "depart")

    vlines = [s for s in fig.layout.shapes if s.line.dash == "dash"]
    x_values = sorted(s.x0 for s in vlines)
    assert x_values == pytest.approx([7.75, 12.75])


def test_title_states_the_outlier_count(six_run_loggers_with_one_outlier):
    fig = plot_outlier_runs(_trial_df(six_run_loggers_with_one_outlier), "arrival", "depart")
    assert "1 of 6 runs flagged" in fig.layout.title.text


def test_no_complete_pairs_raises():
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_departure(entity_id=2, time=5.0)
    trial_df = TrialLogger([logger]).to_dataframe()

    with pytest.raises(ValueError, match="No complete"):
        plot_outlier_runs(trial_df, "arrival", "depart")
