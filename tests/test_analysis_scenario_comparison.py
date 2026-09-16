"""Tests for `vidigi.analysis.compare_replication_values`.

CI bounds are cross-checked against `mean_confidence_interval` directly
(see that function's own test suite for its independent verification) -
this file's job is the comparison logic built on top: delta, overlap, and
the Welch's-t p-value.
"""

import numpy as np
import pytest

from vidigi.analysis import ScenarioComparison, compare_replication_values


def test_disjoint_samples_do_not_overlap_and_have_a_low_p_value():
    values_a = [4.0, 5.0, 6.0, 4.5, 5.5]
    values_b = [10.0, 11.0, 12.0, 10.5, 11.5]

    result = compare_replication_values(values_a, values_b)

    assert result.mean_a == pytest.approx(5.0)
    assert result.mean_b == pytest.approx(11.0)
    assert result.delta == pytest.approx(6.0)
    assert result.delta_pct == pytest.approx(120.0)
    assert result.ci_overlap is False
    assert result.p_value < 0.01


def test_identical_samples_overlap_and_have_a_high_p_value():
    values = [4.0, 5.0, 6.0, 4.5, 5.5]

    result = compare_replication_values(values, values)

    assert result.delta == pytest.approx(0.0)
    assert result.ci_overlap is True
    assert result.p_value == pytest.approx(1.0)


def test_welch_p_value_with_unequal_sample_sizes_and_variances():
    # A: n=3, mean=2, sample variance=1; B: n=5, mean=6, variance=10.
    # Thus |t| = 4 / sqrt(1/3 + 10/5) and df = 98/19.
    # Expected two-sided p independently checked by Simpson integration of
    # the Student-t density (10,000 intervals from 0 to |t|), not scipy.
    # An equal-variance test instead gives p=0.083864616457, reversing the
    # verdict at 0.05; a one-sided test also fails this numeric assertion.
    result = compare_replication_values([1.0, 2.0, 3.0], [2.0, 4.0, 6.0, 8.0, 10.0])

    assert result.n_a == 3
    assert result.n_b == 5
    assert result.p_value == pytest.approx(0.04577582843879524, rel=1e-8)


def test_mean_a_of_zero_gives_nan_delta_pct_not_a_crash():
    values_a = [0.0, 0.0, 0.0]
    values_b = [1.0, 2.0, 3.0]

    result = compare_replication_values(values_a, values_b)

    assert np.isnan(result.delta_pct)
    assert result.delta == pytest.approx(2.0)


def test_fewer_than_two_replications_on_one_side_gives_no_overlap_verdict():
    with pytest.warns(UserWarning, match="Cannot compute"):
        result = compare_replication_values([5.0], [1.0, 2.0, 3.0])

    assert result.ci_overlap is None
    assert np.isnan(result.p_value)


def test_labels_are_carried_through():
    result = compare_replication_values(
        [1.0, 2.0, 3.0], [4.0, 5.0, 6.0], label_a="baseline", label_b="extra staff"
    )

    assert result.label_a == "baseline"
    assert result.label_b == "extra staff"


def test_returns_a_scenario_comparison_namedtuple():
    result = compare_replication_values([1.0, 2.0, 3.0], [4.0, 5.0, 6.0])

    assert isinstance(result, ScenarioComparison)
    assert result.n_a == 3
    assert result.n_b == 3
