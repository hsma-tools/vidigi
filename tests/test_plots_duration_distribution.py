"""Tests for `vidigi.plots.plot_duration_distribution`."""

import typing

import numpy as np
import plotly.graph_objects as go
import pytest

from vidigi.logging import EventLogger, TrialLogger
from vidigi.plots import DistributionKind, SplitBy, plot_duration_distribution


def _logger_with_durations(durations, run_number=1, pathway_by_entity=None):
    """One run where entity i's arrival->depart duration is durations[i-1]."""
    logger = EventLogger(run_number=run_number)
    for i, d in enumerate(durations, start=1):
        pathway = None if pathway_by_entity is None else pathway_by_entity[i - 1]
        logger.log_arrival(entity_id=i, time=0.0, pathway=pathway)
        logger.log_departure(entity_id=i, time=float(d), pathway=pathway)
    return logger


DURATIONS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


def _basic_event_log():
    return TrialLogger([_logger_with_durations(DURATIONS)]).to_dataframe()


# --------------------------------------------------------------------------- #
# kind="hist"
# --------------------------------------------------------------------------- #


def test_hist_uses_a_bar_trace_not_go_histogram():
    """go.Histogram bins in the browser, so fig.data[0].y is None there - the
    project's testing rules forbid isinstance()-only assertions, which is all
    that would be possible against it.
    """
    fig = plot_duration_distribution(_basic_event_log(), "arrival", "depart")
    assert isinstance(fig.data[0], go.Bar)


def test_hist_matches_numpy_binning_with_default_bins():
    fig = plot_duration_distribution(_basic_event_log(), "arrival", "depart")

    edges = np.histogram_bin_edges(DURATIONS, bins=10)
    expected_centers = (edges[:-1] + edges[1:]) / 2
    expected_counts, _ = np.histogram(DURATIONS, bins=edges)

    assert np.allclose(fig.data[0].x, expected_centers)
    assert list(fig.data[0].y) == list(expected_counts)


def test_hist_bins_argument_is_forwarded_to_numpy():
    fig = plot_duration_distribution(
        _basic_event_log(), "arrival", "depart", bins=5
    )

    edges = np.histogram_bin_edges(DURATIONS, bins=5)
    expected_centers = (edges[:-1] + edges[1:]) / 2
    expected_counts, _ = np.histogram(DURATIONS, bins=edges)

    assert np.allclose(fig.data[0].x, expected_centers)
    assert list(fig.data[0].y) == list(expected_counts)


def test_hist_normalise_gives_a_density():
    fig = plot_duration_distribution(
        _basic_event_log(), "arrival", "depart", bins=5, normalise=True
    )

    edges = np.histogram_bin_edges(DURATIONS, bins=5)
    expected_density, _ = np.histogram(DURATIONS, bins=edges, density=True)

    assert np.allclose(fig.data[0].y, expected_density)
    # A density integrates to 1 over the bin widths.
    assert np.isclose(np.sum(fig.data[0].y * np.diff(edges)), 1.0)


# --------------------------------------------------------------------------- #
# kind="box" / "violin"
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kind", ["box", "violin"])
def test_box_and_violin_carry_the_raw_durations(kind):
    fig = plot_duration_distribution(_basic_event_log(), "arrival", "depart", kind=kind)

    assert sorted(fig.data[0].y) == [float(d) for d in DURATIONS]


def test_warm_up_reaches_event_durations_via_kwargs():
    """`plot_duration_distribution` has no explicit `warm_up=` of its own - it
    reaches `vidigi.analysis.event_durations` purely through `**kwargs`, same
    as `entity_col_name`/`run_col_name`. Entity 1 arrives at t=0, entity 2 at
    t=10 (both depart 5 later); `warm_up=5` must exclude entity 1's pairing."""
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_departure(entity_id=1, time=5.0)
    logger.log_arrival(entity_id=2, time=10.0)
    logger.log_departure(entity_id=2, time=15.0)
    event_log = TrialLogger([logger]).to_dataframe()

    fig = plot_duration_distribution(event_log, "arrival", "depart", kind="box", warm_up=5)

    assert list(fig.data[0].y) == [5.0]


# --------------------------------------------------------------------------- #
# kind="ecdf"
# --------------------------------------------------------------------------- #


def test_ecdf_gives_the_full_step_arrays():
    fig = plot_duration_distribution(_basic_event_log(), "arrival", "depart", kind="ecdf")

    n = len(DURATIONS)
    assert list(fig.data[0].x) == [float(d) for d in sorted(DURATIONS)]
    assert list(fig.data[0].y) == [(i + 1) / n for i in range(n)]


def test_ecdf_is_drawn_as_a_step_line():
    """Linear interpolation between sorted points would draw cumulative
    probabilities that never occurred between two observed durations.
    """
    fig = plot_duration_distribution(_basic_event_log(), "arrival", "depart", kind="ecdf")
    assert fig.data[0].line.shape == "hv"


# --------------------------------------------------------------------------- #
# split_by
# --------------------------------------------------------------------------- #


def test_split_by_run_gives_the_whole_name_to_values_mapping():
    trial = TrialLogger(
        [
            _logger_with_durations([1, 2, 3], run_number=1),
            _logger_with_durations([10, 20, 30], run_number=2),
        ]
    )

    fig = plot_duration_distribution(
        trial.to_dataframe(), "arrival", "depart", kind="box", split_by="run"
    )

    by_name = {trace.name: sorted(trace.y) for trace in fig.data}
    assert by_name == {"1": [1.0, 2.0, 3.0], "2": [10.0, 20.0, 30.0]}


def test_split_by_pathway_gives_the_whole_name_to_values_mapping():
    logger = _logger_with_durations(
        [1, 2, 3, 10, 20], pathway_by_entity=["fast", "fast", "fast", "slow", "slow"]
    )
    event_log = TrialLogger([logger]).to_dataframe()

    fig = plot_duration_distribution(
        event_log, "arrival", "depart", kind="violin", split_by="pathway"
    )

    by_name = {trace.name: sorted(trace.y) for trace in fig.data}
    assert by_name == {"fast": [1.0, 2.0, 3.0], "slow": [10.0, 20.0]}


def test_split_by_uses_shared_bins_across_groups_for_hist():
    trial = TrialLogger(
        [
            _logger_with_durations([1, 2, 3], run_number=1),
            _logger_with_durations([10, 20, 30], run_number=2),
        ]
    )

    fig = plot_duration_distribution(
        trial.to_dataframe(), "arrival", "depart", kind="hist", split_by="run"
    )

    assert np.allclose(fig.data[0].x, fig.data[1].x)


def test_split_by_missing_column_raises():
    event_log = _basic_event_log()  # no pathway information at all

    with pytest.raises(ValueError, match="pathway"):
        plot_duration_distribution(
            event_log, "arrival", "depart", split_by="pathway"
        )


# --------------------------------------------------------------------------- #
# Incomplete pairs and error paths
# --------------------------------------------------------------------------- #


def test_incomplete_pairs_are_dropped_before_plotting():
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_departure(entity_id=1, time=5.0)
    # Entity 2 arrives but never departs.
    logger.log_arrival(entity_id=2, time=0.0)
    event_log = TrialLogger([logger]).to_dataframe()

    fig = plot_duration_distribution(event_log, "arrival", "depart", kind="box")

    assert list(fig.data[0].y) == [5.0]


def test_no_complete_pairs_raises():
    """'depart' must occur somewhere in the log, or event_durations itself
    raises first (an absent event name is almost certainly a typo). To reach
    plot_duration_distribution's own "no complete pairs" check, every pairing
    must be incomplete despite both event names existing: entity 1 arrives but
    never departs, and entity 2 departs having never arrived.
    """
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_departure(entity_id=2, time=5.0)
    event_log = TrialLogger([logger]).to_dataframe()

    with pytest.raises(ValueError, match="No complete"):
        plot_duration_distribution(event_log, "arrival", "depart")


# --------------------------------------------------------------------------- #
# kind="ridgeline" / "heatmap" - both require split_by
# --------------------------------------------------------------------------- #


def _two_group_event_log():
    return TrialLogger(
        [
            _logger_with_durations([1, 2, 3], run_number=1),
            _logger_with_durations([4, 5, 6], run_number=2),
        ]
    ).to_dataframe()


@pytest.mark.parametrize("kind", ["ridgeline", "heatmap"])
def test_ridgeline_and_heatmap_require_split_by(kind):
    with pytest.raises(ValueError, match="split_by"):
        plot_duration_distribution(_basic_event_log(), "arrival", "depart", kind=kind)


def test_heatmap_gives_the_full_matrix_and_labels():
    event_log = _two_group_event_log()

    fig = plot_duration_distribution(
        event_log, "arrival", "depart", kind="heatmap", split_by="run", bins=3
    )

    edges = np.histogram_bin_edges([1, 2, 3, 4, 5, 6], bins=3)
    expected_centers = (edges[:-1] + edges[1:]) / 2
    expected_row1, _ = np.histogram([1, 2, 3], bins=edges)
    expected_row2, _ = np.histogram([4, 5, 6], bins=edges)

    assert np.allclose(fig.data[0].x, expected_centers)
    assert list(fig.data[0].y) == ["1", "2"]
    assert np.allclose(list(fig.data[0].z), [expected_row1, expected_row2])


def test_heatmap_normalise_gives_density_per_row():
    event_log = _two_group_event_log()

    fig = plot_duration_distribution(
        event_log,
        "arrival",
        "depart",
        kind="heatmap",
        split_by="run",
        bins=3,
        normalise=True,
    )

    edges = np.histogram_bin_edges([1, 2, 3, 4, 5, 6], bins=3)
    expected_row1, _ = np.histogram([1, 2, 3], bins=edges, density=True)
    expected_row2, _ = np.histogram([4, 5, 6], bins=edges, density=True)

    assert np.allclose(list(fig.data[0].z), [expected_row1, expected_row2])


def test_ridgeline_gives_the_full_polygon_per_group():
    event_log = _two_group_event_log()

    fig = plot_duration_distribution(
        event_log, "arrival", "depart", kind="ridgeline", split_by="run", bins=3
    )

    edges = np.histogram_bin_edges([1, 2, 3, 4, 5, 6], bins=3)
    centers = (edges[:-1] + edges[1:]) / 2
    density1, _ = np.histogram([1, 2, 3], bins=edges, density=True)
    density2, _ = np.histogram([4, 5, 6], bins=edges, density=True)
    peak = max(density1.max(), density2.max())
    scale = 1.5 / peak

    expected_x = [centers[0], *centers, centers[-1], centers[0]]
    expected_y0 = [0, *(density1 * scale), 0, 0]
    expected_y1 = [1.0, *(1.0 + density2 * scale), 1.0, 1.0]

    assert len(fig.data) == 2
    assert np.allclose(fig.data[0].x, expected_x)
    assert np.allclose(fig.data[0].y, expected_y0)
    assert fig.data[0].name == "1"
    assert np.allclose(fig.data[1].x, expected_x)
    assert np.allclose(fig.data[1].y, expected_y1)
    assert fig.data[1].name == "2"

    assert list(fig.layout.yaxis.tickvals) == [0.0, 1.0]
    assert list(fig.layout.yaxis.ticktext) == ["1", "2"]


def test_ridgeline_uses_density_so_group_size_does_not_affect_height():
    """A group with twice as many observations but the same relative shape
    must produce the same ridge height as a group with fewer - proving
    ridgeline always uses density, never raw counts, regardless of
    `normalise`. Otherwise a busier run would misleadingly look "different"
    from a quieter one with an identical distribution shape.
    """
    event_log = TrialLogger(
        [
            _logger_with_durations([1, 1, 2, 2, 3, 3], run_number=1),
            _logger_with_durations([1, 2, 3], run_number=2),
        ]
    ).to_dataframe()

    fig = plot_duration_distribution(
        event_log, "arrival", "depart", kind="ridgeline", split_by="run", bins=3
    )

    peak0 = max(fig.data[0].y) - 0.0
    peak1 = max(fig.data[1].y) - 1.0
    assert np.isclose(peak0, peak1)


def test_invalid_kind_raises():
    with pytest.raises(ValueError, match="`kind`"):
        plot_duration_distribution(
            _basic_event_log(), "arrival", "depart", kind="pie"
        )


def test_invalid_split_by_raises():
    with pytest.raises(ValueError, match="`split_by`"):
        plot_duration_distribution(
            _basic_event_log(), "arrival", "depart", split_by="entity"
        )


@pytest.mark.parametrize("kind", typing.get_args(DistributionKind))
def test_every_distribution_kind_literal_is_accepted(kind):
    """The annotation must not advertise a `kind` the runtime check rejects.

    "ridgeline" and "heatmap" additionally require `split_by`, so a run column
    with more than one value is used for every kind rather than switching
    fixtures per kind.
    """
    trial = TrialLogger(
        [
            _logger_with_durations([1, 2, 3], run_number=1),
            _logger_with_durations([4, 5, 6], run_number=2),
        ]
    )
    split_by = "run" if kind in ("ridgeline", "heatmap") else None

    fig = plot_duration_distribution(
        trial.to_dataframe(), "arrival", "depart", kind=kind, split_by=split_by
    )
    assert isinstance(fig, go.Figure)


@pytest.mark.parametrize("split_by", typing.get_args(SplitBy))
def test_every_split_by_literal_is_accepted(split_by):
    """The annotation must not advertise a `split_by` the runtime check rejects."""
    logger = _logger_with_durations([1, 2, 3], pathway_by_entity=["a", "a", "a"])
    event_log = TrialLogger([logger]).to_dataframe()

    fig = plot_duration_distribution(
        event_log, "arrival", "depart", split_by=split_by
    )
    assert isinstance(fig, go.Figure)


# --------------------------------------------------------------------------- #
# TrialLogger delegation
# --------------------------------------------------------------------------- #


def test_trial_logger_delegates_to_plots_plot_duration_distribution():
    trial = TrialLogger([_logger_with_durations(DURATIONS)])

    fig = trial.plot_duration_distribution("arrival", "depart", kind="box")

    assert sorted(fig.data[0].y) == [float(d) for d in DURATIONS]
