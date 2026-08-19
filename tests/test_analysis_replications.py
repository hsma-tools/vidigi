"""Tests for `vidigi.analysis.replication_means` and `mean_confidence_interval`.

Expected values are hand-computed (see `unequal_run_loggers`'s docstring) or
checked against a published Student's t table, never derived from scipy calling
itself.
"""

import sys

import numpy as np
import pandas as pd
import pytest

from vidigi.analysis import (
    ConfidenceInterval,
    event_durations,
    mean_confidence_interval,
    replication_means,
)
from vidigi.logging import TrialLogger


def _unequal_run_durations(unequal_run_loggers):
    trial = TrialLogger(unequal_run_loggers)
    return event_durations(trial._trial_dataframe, "arrival", "depart")


# --------------------------------------------------------------------------- #
# replication_means
# --------------------------------------------------------------------------- #


def test_replication_means_gives_the_full_run_mean_mapping(unequal_run_loggers):
    durations = _unequal_run_durations(unequal_run_loggers)

    result = replication_means(durations)

    assert dict(zip(result["run_number"], result["value"])) == {1: 4.0, 2: 5.0, 3: 9.0}


def test_replication_means_defaults_to_the_event_durations_column_names():
    """`value_col`/`run_col` default to `event_durations`'s own output columns,
    so the common case needs no argument beyond the frame itself."""
    durations = pd.DataFrame(
        {"run_number": [1, 1, 2, 2], "duration": [2.0, 4.0, 10.0, 20.0]}
    )

    result = replication_means(durations)

    assert dict(zip(result["run_number"], result["value"])) == {1: 3.0, 2: 15.0}


def test_replication_means_drops_incomplete_pairings_before_aggregating():
    """A NaN duration (an incomplete pairing) cannot contribute to a run's mean -
    dropping it, rather than propagating NaN, is what lets a run with some
    incomplete journeys still report a value from its complete ones."""
    durations = pd.DataFrame(
        {"run_number": [1, 1, 2], "duration": [4.0, np.nan, np.nan]}
    )

    result = replication_means(durations)

    # Run 2 has no complete duration at all, so it drops out entirely rather
    # than reporting NaN.
    assert dict(zip(result["run_number"], result["value"])) == {1: 4.0}


@pytest.mark.parametrize("what", ["mean", "median", "max", "min", "std", "var", "sum"])
def test_every_simple_stat_is_accepted(what, unequal_run_loggers):
    durations = _unequal_run_durations(unequal_run_loggers)

    result = replication_means(durations, what=what)

    assert len(result) == 3


def test_quantile_forwards_kwargs(unequal_run_loggers):
    durations = _unequal_run_durations(unequal_run_loggers)

    result = replication_means(durations, what="quantile", q=0.5)

    # Each run's 50th percentile of its own (repeated) duration is that duration.
    assert dict(zip(result["run_number"], result["value"])) == {1: 4.0, 2: 5.0, 3: 9.0}


def test_entity_counting_aggregations_are_rejected():
    """`"count"`/`"unserved_rate"`/`"summary"` count entities, not durations - not
    meaningful re-averaged across runs, so must be rejected rather than silently
    doing something nonsensical."""
    durations = pd.DataFrame({"run_number": [1, 2], "duration": [4.0, 5.0]})

    with pytest.raises(ValueError, match="per-replication statistic"):
        replication_means(durations, what="count")


# --------------------------------------------------------------------------- #
# mean_confidence_interval
# --------------------------------------------------------------------------- #


def test_ci_matches_the_hand_computed_unequal_run_example(unequal_run_loggers):
    durations = _unequal_run_durations(unequal_run_loggers)
    run_values = replication_means(durations)["value"]

    result = mean_confidence_interval(run_values)

    assert isinstance(result, ConfidenceInterval)
    assert result.n == 3
    assert result.mean == pytest.approx(6.0)
    # t_0.975,2 = 4.302653, taken from a published Student's t table, not scipy.
    assert result.half_width == pytest.approx(
        4.302653 * np.sqrt(7) / np.sqrt(3), abs=1e-4
    )
    assert result.half_width == pytest.approx(6.5724, abs=1e-3)
    assert result.lower == pytest.approx(6.0 - 6.5724, abs=1e-3)
    assert result.upper == pytest.approx(6.0 + 6.5724, abs=1e-3)
    assert result.method == "t"


def test_ci_over_pooled_entities_is_narrower_and_wrong(unequal_run_loggers):
    """Mutation-style regression: pooling per-entity durations instead of using
    replication means treats correlated entities as independent, which
    (deliberately, to prove the test bites) is checked here to differ from the
    correct run-level answer computed above."""
    durations = _unequal_run_durations(unequal_run_loggers)

    pooled_result = mean_confidence_interval(durations["duration"])
    run_result = mean_confidence_interval(replication_means(durations)["value"])

    assert pooled_result.mean != run_result.mean
    assert pooled_result.half_width != pytest.approx(run_result.half_width, abs=1e-3)


def test_fewer_than_two_replications_gives_nan_and_warns():
    with pytest.warns(UserWarning, match="at least 2"):
        result = mean_confidence_interval([4.0])

    assert result.n == 1
    assert result.mean == 4.0
    assert np.isnan(result.half_width)
    assert np.isnan(result.lower)
    assert np.isnan(result.upper)


def test_n_equals_two_gives_a_large_but_real_interval():
    """Not special-cased: two replications genuinely produce a wide interval
    (t_0.975,1 = 12.706, from a published table), which is correct information,
    not a bug."""
    result = mean_confidence_interval([4.0, 6.0])

    assert result.n == 2
    assert result.mean == pytest.approx(5.0)
    # std of [4, 6] = sqrt(2); se = sqrt(2)/sqrt(2) = 1
    assert result.half_width == pytest.approx(12.706, abs=1e-2)


def test_unsupported_method_raises():
    with pytest.raises(ValueError, match="'t'"):
        mean_confidence_interval([1.0, 2.0, 3.0], method="bootstrap")


def test_t_not_z_makes_a_real_difference_at_small_n(unequal_run_loggers):
    """Mutation-proof: swapping `t.ppf` for a normal `z.ppf` would give a
    half-width about 29% too narrow at n=3 - assert the actual half-width is
    not what a normal approximation would produce."""
    durations = _unequal_run_durations(unequal_run_loggers)
    run_values = replication_means(durations)["value"]

    result = mean_confidence_interval(run_values)

    se = run_values.std(ddof=1) / np.sqrt(3)
    z_975 = 1.959964  # published normal-table value
    normal_half_width = z_975 * se

    assert result.half_width == pytest.approx(6.5724, abs=1e-3)
    assert result.half_width != pytest.approx(normal_half_width, abs=1e-3)
    assert result.half_width > normal_half_width


def test_missing_scipy_raises_a_legible_import_error(monkeypatch):
    """`error_bars="ci"` (via `mean_confidence_interval`) is the only statistic
    that needs scipy - simulate it being absent rather than actually
    uninstalling it."""
    monkeypatch.setitem(sys.modules, "scipy", None)
    monkeypatch.setitem(sys.modules, "scipy.stats", None)

    with pytest.raises(ImportError, match=r"pip install vidigi\[stats\]"):
        mean_confidence_interval([1.0, 2.0, 3.0])
