"""Tests for `vidigi.analysis.welch_moving_average`."""

import numpy as np
import pytest

from vidigi.analysis import welch_moving_average


def test_welch_method_matches_the_hand_computed_array(welch_series):
    """Full array, edge points included - the shrinking-window (`2i - 1`) left
    edge and the interior full-width window both land in this one array, so a
    mutation to either formula fails this assertion, not just a shape check."""
    result = welch_moving_average(welch_series, window=2, method="welch")

    assert result == pytest.approx([8.0, 16 / 3, 6.0, 6.4])


def test_welch_method_output_length_is_series_length_minus_window(welch_series):
    result = welch_moving_average(welch_series, window=2, method="welch")

    assert len(result) == 6 - 2


def test_cumulative_method_matches_the_hand_computed_array(welch_series):
    result = welch_moving_average(welch_series, method="cumulative")

    assert result == pytest.approx([8.0, 6.0, 16 / 3, 5.5, 6.0, 20 / 3])


def test_cumulative_method_output_is_full_length(welch_series):
    result = welch_moving_average(welch_series, method="cumulative")

    assert len(result) == 6


def test_cumulative_method_ignores_window(welch_series):
    with_window = welch_moving_average(welch_series, window=1, method="cumulative")
    without_window = welch_moving_average(welch_series, method="cumulative")

    assert with_window == pytest.approx(without_window)


def test_shrinking_edge_differs_from_naive_full_width_average(welch_series):
    """The first output point (i=1) must be the single value ensemble[0]=8, not
    a `NaN` (as `pandas.rolling(center=True)` would give) and not an average
    that reaches beyond the data that actually exists on the left."""
    result = welch_moving_average(welch_series, window=2, method="welch")

    assert not np.isnan(result).any()
    assert result[0] == pytest.approx(8.0)


def test_runs_of_unequal_length_are_truncated_to_the_shortest_with_a_warning():
    short = [1.0, 2.0, 3.0]
    long = [1.0, 2.0, 3.0, 4.0, 5.0]

    with pytest.warns(UserWarning, match="unequal length"):
        result = welch_moving_average([short, long], method="cumulative")

    assert len(result) == 3


def test_single_run_is_its_own_ensemble_mean():
    result = welch_moving_average([[1.0, 2.0, 3.0, 4.0, 5.0]], method="cumulative")

    assert result == pytest.approx([1.0, 1.5, 2.0, 2.5, 3.0])


def test_single_run_welch_method_uses_its_own_values_as_the_ensemble():
    """With one run, the ensemble mean is just that run's series, so the
    shrinking-edge/interior formula runs against non-linear real values
    rather than only ever being exercised on an averaged-out series."""
    result = welch_moving_average([[10.0, 4.0, 2.0, 8.0, 6.0, 12.0]], window=2, method="welch")

    # i=1 (shrink, size 1): [10]; i=2 (shrink, size 3): mean([10,4,2]);
    # i=3 (interior, size 5): mean([10,4,2,8,6]); i=4: mean([4,2,8,6,12])
    assert result == pytest.approx([10.0, 16 / 3, 6.0, 6.4])


def test_empty_series_by_run_raises():
    with pytest.raises(ValueError, match="series_by_run"):
        welch_moving_average([], method="cumulative")


def test_unknown_method_raises(welch_series):
    with pytest.raises(ValueError, match="method"):
        welch_moving_average(welch_series, window=2, method="bogus")


def test_missing_window_raises_for_welch_method(welch_series):
    with pytest.raises(ValueError, match="window"):
        welch_moving_average(welch_series, method="welch")


@pytest.mark.parametrize("bad_window", [0, -1])
def test_non_positive_window_raises(welch_series, bad_window):
    with pytest.raises(ValueError, match="window"):
        welch_moving_average(welch_series, window=bad_window, method="welch")


def test_window_at_least_series_length_raises(welch_series):
    with pytest.raises(ValueError, match="window"):
        welch_moving_average(welch_series, window=6, method="welch")
