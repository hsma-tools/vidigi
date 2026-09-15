"""Tests for `vidigi.analysis.flag_outlier_runs`.

Fence values are hand-computed from the quartiles before being encoded as
assertions (see each test's docstring for the arithmetic), matching this
project's convention of verifying expected values independently before
trusting them.
"""

import warnings

import pandas as pd
import pytest

from vidigi.analysis import flag_outlier_runs


def _values(values):
    return pd.DataFrame(
        {"run_number": range(1, len(values) + 1), "value": values}
    )


def test_flags_the_whole_outlier_mapping_not_a_spot_check():
    """values = [10, 11, 9, 10.5, 9.5, 13.0]; Q1=9.625, Q3=10.875, IQR=1.25,
    so the 1.5x fence is [7.75, 12.75] - only the 13.0 run (run 6) falls
    outside it. Asserting the full run->is_outlier mapping, not just run 6,
    since a reversed or off-by-one flag could still pass a spot check."""
    values = [10.0, 11.0, 9.0, 10.5, 9.5, 13.0]

    result = flag_outlier_runs(_values(values))

    assert dict(zip(result["run_number"], result["is_outlier"])) == {
        1: False,
        2: False,
        3: False,
        4: False,
        5: False,
        6: True,
    }
    assert result.loc[result["run_number"] == 6, "lower_fence"].iloc[0] == pytest.approx(7.75)
    assert result.loc[result["run_number"] == 6, "upper_fence"].iloc[0] == pytest.approx(12.75)


def test_wider_multiplier_flags_fewer_or_equal_outliers():
    """Same data as above: the 13.0 run is inside the wider 3.0x fence
    ([5.875, 14.625]), so it is no longer flagged."""
    values = [10.0, 11.0, 9.0, 10.5, 9.5, 13.0]

    result = flag_outlier_runs(_values(values), iqr_multiplier=3.0)

    assert not result["is_outlier"].any()
    assert result["upper_fence"].iloc[0] == pytest.approx(14.625)


def test_negative_multiplier_raises():
    with pytest.raises(ValueError, match="iqr_multiplier"):
        flag_outlier_runs(_values([1.0, 2.0, 3.0]), iqr_multiplier=-1)


def test_fewer_than_four_replications_warns_but_still_returns_a_result():
    with pytest.warns(UserWarning, match="quartiles"):
        result = flag_outlier_runs(_values([1.0, 2.0, 3.0]))

    assert len(result) == 3


def test_four_or_more_replications_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = flag_outlier_runs(_values([1.0, 2.0, 3.0, 4.0]))

    assert len(result) == 4
