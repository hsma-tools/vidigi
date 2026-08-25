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
    replication_precision,
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


def test_quantile_forwards_kwargs():
    """`unequal_run_loggers` gives every entity *within a run* the same duration,
    so `quantile(q=...)` returns that constant regardless of `q` - it cannot
    catch a dropped `q` kwarg. This uses within-run-varying durations instead,
    where different `q` values give different, independently hand-computed
    answers (linear interpolation, pandas' default)."""
    durations = pd.DataFrame(
        {
            "run_number": [1, 1, 1, 1, 2, 2, 2, 2],
            "duration": [1.0, 2.0, 3.0, 4.0, 10.0, 20.0, 30.0, 40.0],
        }
    )

    low = replication_means(durations, what="quantile", q=0.25)
    high = replication_means(durations, what="quantile", q=0.75)

    assert dict(zip(low["run_number"], low["value"])) == {1: 1.75, 2: 17.5}
    assert dict(zip(high["run_number"], high["value"])) == {1: 3.25, 2: 32.5}


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
    replication means treats correlated entities as independent, which shrinks
    the standard error and produces an interval that is too *narrow* - not just
    different, which the direction check below pins explicitly."""
    durations = _unequal_run_durations(unequal_run_loggers)

    pooled_result = mean_confidence_interval(durations["duration"])
    run_result = mean_confidence_interval(replication_means(durations)["value"])

    assert pooled_result.mean != run_result.mean
    # Hand-computed: pooled half-width ~= 1.716 (n=8, pooled std), run-level
    # half-width ~= 6.572 (n=3, run means) - pooling is the narrower, wrong one.
    assert pooled_result.half_width < run_result.half_width
    assert pooled_result.half_width == pytest.approx(1.716, abs=1e-3)


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


def test_ci_level_reaches_the_t_distribution_call(unequal_run_loggers):
    """No prior test passes a non-default `ci_level` - this pins that the
    argument actually reaches `scipy.stats.t.ppf` rather than being ignored."""
    durations = _unequal_run_durations(unequal_run_loggers)
    run_values = replication_means(durations)["value"]

    result = mean_confidence_interval(run_values, ci_level=0.90)

    se = run_values.std(ddof=1) / np.sqrt(3)
    # t_0.95,2 = 2.919986, from a published Student's t table (90% CI, df=2).
    assert result.half_width == pytest.approx(2.919986 * se, abs=1e-4)
    assert result.half_width == pytest.approx(4.4604, abs=1e-3)
    # And must differ from the default ci_level=0.95 answer computed above.
    assert result.half_width != pytest.approx(6.5724, abs=1e-3)


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


# --------------------------------------------------------------------------- #
# replication_precision
# --------------------------------------------------------------------------- #


def test_replication_precision_matches_hand_computed_unequal_run_example():
    """Each row's (mean, half_width) is independently checked against
    `mean_confidence_interval` applied to the same prefix - k=3 also matches
    the published-t-table value already pinned in
    `test_ci_matches_the_hand_computed_unequal_run_example` (half-width
    6.5724). k=2's half-width is verified against scipy directly (t_0.975,1 =
    12.706205, std([4,5],ddof=1) = sqrt(0.5)) since no published-table value
    for that exact case exists elsewhere in this file."""
    result = replication_precision([4.0, 5.0, 9.0])

    assert list(result["n_replications"]) == [1, 2, 3]
    assert result["cumulative_mean"].tolist() == pytest.approx([4.0, 4.5, 6.0])

    assert np.isnan(result.loc[0, "half_width"])
    assert np.isnan(result.loc[0, "deviation"])

    assert result.loc[1, "half_width"] == pytest.approx(6.353102, abs=1e-4)
    assert result.loc[1, "deviation"] == pytest.approx(6.353102 / 4.5, abs=1e-4)

    assert result.loc[2, "half_width"] == pytest.approx(6.5724, abs=1e-3)
    assert result.loc[2, "deviation"] == pytest.approx(6.5724 / 6.0, abs=1e-3)
    assert result.loc[2, "lower"] == pytest.approx(6.0 - 6.5724, abs=1e-3)
    assert result.loc[2, "upper"] == pytest.approx(6.0 + 6.5724, abs=1e-3)


def test_replication_precision_columns_and_length():
    result = replication_precision([1.0, 2.0, 3.0, 4.0])

    assert len(result) == 4
    assert list(result.columns) == [
        "n_replications",
        "cumulative_mean",
        "half_width",
        "lower",
        "upper",
        "deviation",
        "stays_below_threshold",
    ]


def test_k_equals_one_is_always_below_threshold_false():
    """`deviation` is undefined at k=1 (no spread from a single point), so
    `stays_below_threshold` must be False there regardless of how generous
    `deviation_threshold` is - even a threshold of infinity cannot make an
    undefined deviation count as "below" it."""
    result = replication_precision([4.0], deviation_threshold=float("inf"))

    assert result.loc[0, "stays_below_threshold"] == False  # noqa: E712


def test_stays_below_threshold_is_true_once_deviation_settles():
    """Deviation drops to 0 for k=2..5 (identical values), rises to ~0.37 at
    k=6 (once the one genuine outlier enters the running window), then keeps
    falling - every one of those points is <= the 0.5 threshold, so every k
    from 2 onward should be flagged, matching the "stays below from here to
    the end" contract."""
    values = [10, 10, 10, 10, 10, 20, 10, 10]

    result = replication_precision(values, deviation_threshold=0.5)

    assert result["stays_below_threshold"].tolist() == [
        False, True, True, True, True, True, True, True,
    ]


def test_stays_below_threshold_is_false_when_a_later_point_never_recovers():
    """Mutation-proof for "stays below", not "first drops below": deviation is
    genuinely 0.0 (<= the 0.15 threshold) at k=2..6, which a naive
    first-drops-below check would flag True - but a later outlier (k=7) pushes
    deviation to ~0.89 and it never comes back under 0.15 within the data
    given, so *every* row, including the early zero-deviation ones, must be
    False."""
    values = [10, 10, 10, 10, 10, 10, 50, 9, 10, 10]

    result = replication_precision(values, deviation_threshold=0.15)

    assert not result["stays_below_threshold"].any()

    # Prove the "stays below" semantics, not a coincidence: reverting to a
    # "this row's own deviation <= threshold" check would flag k=2..6.
    naive = (result["deviation"] <= 0.15).fillna(False)
    assert naive.tolist() != result["stays_below_threshold"].tolist()
    assert naive.sum() == 5


def test_deviation_is_nan_when_cumulative_mean_is_zero():
    """A cumulative mean of exactly 0 makes the relative half-width
    (half_width / mean) undefined - must be NaN, not a ZeroDivisionError or
    +/-inf."""
    result = replication_precision([-5.0, 5.0, 3.0])

    assert result.loc[1, "cumulative_mean"] == 0.0
    assert np.isnan(result.loc[1, "deviation"])
    assert result.loc[1, "stays_below_threshold"] == False  # noqa: E712


def test_deviation_is_non_negative_for_a_negative_cumulative_mean():
    """A metric with a negative mean (e.g. a before/after difference) must
    not read as trivially "precise" because half_width / mean came out
    negative - deviation is always a non-negative relative half-width.
    Found by an independent OR-specialist review, which showed a naive
    `half_width / mean` (no `abs()`) makes `stays_below_threshold` flip
    `True` from k=2 onward on a genuinely imprecise, negative-mean series."""
    values = [-8, -12, -6, -15, -9, -11, -7, -13, -10, -14]

    result = replication_precision(values, deviation_threshold=0.05)

    assert (result["cumulative_mean"] < 0).all()
    deviations = result["deviation"].dropna()
    assert (deviations >= 0).all()
    # The true relative half-width here is large (~250% at k=2) - nothing
    # should stay below a 5% threshold within this series.
    assert not result["stays_below_threshold"].any()


def test_empty_values_raises():
    with pytest.raises(ValueError, match="at least one replication"):
        replication_precision([])


def test_single_value_needs_no_scipy(monkeypatch):
    """k never reaches 2, so `mean_confidence_interval` (and therefore scipy)
    is never called - a single-replication call must not raise ImportError
    even without scipy installed."""
    monkeypatch.setitem(sys.modules, "scipy", None)
    monkeypatch.setitem(sys.modules, "scipy.stats", None)

    result = replication_precision([7.0])

    assert result.loc[0, "cumulative_mean"] == 7.0
    assert np.isnan(result.loc[0, "half_width"])


def test_missing_scipy_raises_once_a_second_replication_is_reached(monkeypatch):
    monkeypatch.setitem(sys.modules, "scipy", None)
    monkeypatch.setitem(sys.modules, "scipy.stats", None)

    with pytest.raises(ImportError, match=r"pip install vidigi\[stats\]"):
        replication_precision([7.0, 8.0])


def test_deviation_threshold_reaches_the_stays_below_computation():
    """No prior test passes a non-default `deviation_threshold` for this
    exact array - pins that the argument actually reaches
    `stays_below_threshold`'s comparison rather than being ignored (a
    threshold of 0.0 makes even a converged run fail every row)."""
    values = [10, 10, 10, 10, 10, 20, 10, 10]

    generous = replication_precision(values, deviation_threshold=0.5)
    impossible = replication_precision(values, deviation_threshold=0.0)

    assert generous["stays_below_threshold"].any()
    assert not impossible["stays_below_threshold"].any()


def test_ci_level_reaches_replication_precision_directly():
    """`ci_level` is tested indirectly through `plot_replication_analysis`/
    `TrialLogger` elsewhere in this suite, but never directly against
    `replication_precision` itself - pins that it reaches the per-k
    `mean_confidence_interval` call in this function's own body, using the
    same published-t-table values already pinned for `mean_confidence_interval`
    (`test_ci_level_reaches_the_t_distribution_call`)."""
    result_95 = replication_precision([4.0, 5.0, 9.0])
    result_90 = replication_precision([4.0, 5.0, 9.0], ci_level=0.90)

    assert result_95.loc[2, "half_width"] == pytest.approx(6.5724, abs=1e-3)
    # t_0.95,2 = 2.919986, from a published Student's t table (90% CI, df=2).
    assert result_90.loc[2, "half_width"] == pytest.approx(4.4604, abs=1e-3)
    assert result_90.loc[2, "half_width"] != pytest.approx(
        result_95.loc[2, "half_width"], abs=1e-3
    )
