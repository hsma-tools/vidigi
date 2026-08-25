"""Tests for `vidigi.plots.plot_replication_analysis` as a free function.

`TrialLogger.plot_replication_analysis`/`.get_replication_precision` are thin
delegators over this and `vidigi.analysis.replication_precision`; their own
tests in `test_logging_triallogger.py` are the proof the delegation forwards
every argument.
"""

import sys

import numpy as np
import plotly.graph_objects as go
import pytest

from vidigi.logging import EventLogger, TrialLogger
from vidigi.plots import plot_replication_analysis


def _trial_df(loggers):
    return TrialLogger(loggers).to_dataframe()


def test_returns_a_figure(unequal_run_loggers):
    fig = plot_replication_analysis(_trial_df(unequal_run_loggers), "arrival", "depart")
    assert isinstance(fig, go.Figure)


def test_cumulative_mean_matches_the_hand_computed_unequal_run_example(unequal_run_loggers):
    """`unequal_run_loggers`'s own docstring already hand-computes cumulative
    means [4.0, 4.5, 6.0] for this exact event pair."""
    fig = plot_replication_analysis(_trial_df(unequal_run_loggers), "arrival", "depart")

    mean_trace = fig.data[1]
    assert mean_trace.name == "cumulative mean"
    assert list(mean_trace.y) == pytest.approx([4.0, 4.5, 6.0])


def test_deviation_trace_matches_the_hand_computed_half_widths(unequal_run_loggers):
    """k=3's half-width (6.5724, published-t-table value pinned elsewhere in
    this suite) gives deviation 6.5724 / 6.0; k=1 is NaN (no spread from one
    point)."""
    fig = plot_replication_analysis(_trial_df(unequal_run_loggers), "arrival", "depart")

    deviation_trace = fig.data[2]
    assert np.isnan(deviation_trace.y[0])
    assert deviation_trace.y[2] == pytest.approx(6.5724 / 6.0, abs=1e-3)


def test_show_deviation_false_drops_the_second_panel(unequal_run_loggers):
    fig = plot_replication_analysis(
        _trial_df(unequal_run_loggers), "arrival", "depart", show_deviation=False
    )
    names = [t.name for t in fig.data]
    assert "deviation" not in names
    assert len(fig.data) == 2


def test_ci_band_uses_the_precision_table_bounds(unequal_run_loggers):
    """The filled CI-band trace's y values are `upper` (k=1..3) followed by
    reversed `lower` (k=3..1) - proves the band is actually built from
    `replication_precision`'s bounds, not some independently recomputed
    interval."""
    fig = plot_replication_analysis(_trial_df(unequal_run_loggers), "arrival", "depart")

    band = fig.data[0]
    assert band.fill == "toself"
    # x is [1, 2, 3] followed by its own reverse [3, 2, 1] - the closed
    # polygon walk (forward along upper, backward along lower) the fill
    # needs, not just a coincidentally-matching y array.
    assert list(band.x) == [1, 2, 3, 3, 2, 1]
    # index 2 = upper at k=3 (6.0 + 6.5724); index 3 = lower at k=3 (6.0 - 6.5724).
    assert band.y[2] == pytest.approx(6.0 + 6.5724, abs=1e-3)
    assert band.y[3] == pytest.approx(6.0 - 6.5724, abs=1e-3)


def test_ci_level_reaches_the_figure(unequal_run_loggers):
    """No prior test passes a non-default `ci_level` - pins that it reaches
    `replication_precision`/`mean_confidence_interval` rather than being
    dropped in this function's own body."""
    fig_95 = plot_replication_analysis(_trial_df(unequal_run_loggers), "arrival", "depart")
    fig_90 = plot_replication_analysis(
        _trial_df(unequal_run_loggers), "arrival", "depart", ci_level=0.90
    )

    assert fig_90.data[2].y[2] != pytest.approx(fig_95.data[2].y[2], abs=1e-4)
    # t_0.95,2 = 2.919986 (published table) vs t_0.975,2 = 4.302653: narrower.
    assert fig_90.data[2].y[2] < fig_95.data[2].y[2]


def test_deviation_threshold_reaches_the_reference_line(unequal_run_loggers):
    fig = plot_replication_analysis(
        _trial_df(unequal_run_loggers), "arrival", "depart", deviation_threshold=0.2
    )
    hlines = [
        shape for shape in fig.layout.shapes if shape.type == "line" and shape.y0 == shape.y1
    ]
    assert any(shape.y0 == pytest.approx(0.2) for shape in hlines)


def test_recommended_n_appears_in_the_title_when_it_converges():
    """Every run identical -> deviation is 0.0 from k=2 onward, so it stays
    below any positive threshold immediately - recommended n=2 (the smallest
    k with a defined, below-threshold deviation)."""
    loggers = [EventLogger(run_number=r) for r in (1, 2, 3, 4)]
    for run_number, logger in enumerate(loggers, start=1):
        logger.log_arrival(entity_id=1, time=0.0)
        logger.log_departure(entity_id=1, time=5.0)

    fig = plot_replication_analysis(_trial_df(loggers), "arrival", "depart")

    assert "2 replications" in fig.layout.title.text


def test_title_reports_no_convergence_when_deviation_never_settles(unequal_run_loggers):
    fig = plot_replication_analysis(_trial_df(unequal_run_loggers), "arrival", "depart")
    assert "never stays below" in fig.layout.title.text


def test_what_reaches_replication_means(unequal_run_loggers):
    """`what="max"` on constant-per-run durations gives the same run values as
    `"mean"` for this fixture (each run is internally constant), so this uses
    a run with internal variation instead - `two_run_loggers` extended with an
    unequal entity within one run."""
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_departure(entity_id=1, time=2.0)
    logger.log_arrival(entity_id=2, time=0.0)
    logger.log_departure(entity_id=2, time=8.0)
    logger2 = EventLogger(run_number=2)
    logger2.log_arrival(entity_id=1, time=0.0)
    logger2.log_departure(entity_id=1, time=10.0)

    mean_fig = plot_replication_analysis(_trial_df([logger, logger2]), "arrival", "depart", what="mean")
    max_fig = plot_replication_analysis(_trial_df([logger, logger2]), "arrival", "depart", what="max")

    assert list(mean_fig.data[1].y) == pytest.approx([5.0, 7.5])
    assert list(max_fig.data[1].y) == pytest.approx([8.0, 9.0])


def test_no_complete_pairs_raises():
    """Both event names exist somewhere in the log (so `event_durations`
    itself does not raise), but no run has a complete pairing of the two."""
    run1 = EventLogger(run_number=1)
    run1.log_arrival(entity_id=1, time=0.0)  # never departs
    run2 = EventLogger(run_number=2)
    run2.log_departure(entity_id=1, time=5.0)  # never arrived

    with pytest.raises(ValueError, match="No complete"):
        plot_replication_analysis(_trial_df([run1, run2]), "arrival", "depart")


def test_fewer_than_two_replications_raises(two_run_loggers):
    single_run_df = _trial_df([two_run_loggers[0]])
    with pytest.raises(ValueError, match="at least 2 replications"):
        plot_replication_analysis(single_run_df, "arrival", "depart")


def test_missing_scipy_raises_a_legible_import_error(monkeypatch, unequal_run_loggers):
    monkeypatch.setitem(sys.modules, "scipy", None)
    monkeypatch.setitem(sys.modules, "scipy.stats", None)

    with pytest.raises(ImportError, match=r"pip install vidigi\[stats\]"):
        plot_replication_analysis(_trial_df(unequal_run_loggers), "arrival", "depart")


def test_match_kwarg_reaches_event_durations():
    """`match="last"` vs the default `"first"` must reach `event_durations`
    through `**col_kwargs` and change which occurrence is paired."""
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_queue(entity_id=1, event="assessment", time=1.0)
    logger.log_queue(entity_id=1, event="assessment", time=20.0)
    logger2 = EventLogger(run_number=2)
    logger2.log_arrival(entity_id=1, time=0.0)
    logger2.log_queue(entity_id=1, event="assessment", time=2.0)
    logger2.log_queue(entity_id=1, event="assessment", time=30.0)

    first_fig = plot_replication_analysis(
        _trial_df([logger, logger2]), "arrival", "assessment", match="first"
    )
    last_fig = plot_replication_analysis(
        _trial_df([logger, logger2]), "arrival", "assessment", match="last"
    )

    assert list(first_fig.data[1].y) == pytest.approx([1.0, 1.5])
    assert list(last_fig.data[1].y) == pytest.approx([20.0, 25.0])
