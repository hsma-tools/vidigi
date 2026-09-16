"""Tests for `vidigi.analysis.event_occurrence_rate`.

Expected Wilson-interval values are hand-computed with the textbook formula
using the published standard-normal 97.5th percentile (z=1.9599639845400545,
e.g. NIST/SEMATECH e-Handbook of Statistical Methods, Table 1.3.6.7.2),
independently in plain Python `math` - never derived from scipy calling
itself.
"""

import warnings

import pandas as pd
import pytest

from vidigi.analysis import ProportionEstimate, event_occurrence_rate


def _log(rows):
    """Build a minimal event log from (run_number, event) tuples."""
    return pd.DataFrame(
        [{"run_number": run, "event": event} for run, event in rows]
    )


def test_matches_the_hand_computed_wilson_interval():
    """20 runs, the event occurs in 5 of them (p_hat=0.25).

    Hand-computed (see module docstring): centre=0.29028128951320487,
    lower=0.11186170140766563, upper=0.4687008776187441.
    """
    rows = [(run, "other") for run in range(1, 21)]
    rows += [(run, "rare") for run in range(1, 6)]
    log = _log(rows)

    result = event_occurrence_rate(log, "rare")

    assert result.proportion == pytest.approx(0.25)
    assert result.lower == pytest.approx(0.11186170140766563, rel=1e-6)
    assert result.upper == pytest.approx(0.4687008776187441, rel=1e-6)
    assert result.n_runs == 20
    assert result.n_occurred == 5
    assert result.method == "wilson"


def test_rare_event_worked_example():
    """50 runs, the event occurs in exactly 1 (a genuinely rare event).

    Hand-computed: lower=0.003539259271646236, upper=0.10495443589637815.
    """
    rows = [(run, "other") for run in range(1, 51)]
    rows += [(1, "rare")]
    log = _log(rows)

    result = event_occurrence_rate(log, "rare", n_runs=50)

    assert result.proportion == pytest.approx(0.02)
    assert result.lower == pytest.approx(0.003539259271646236, rel=1e-6)
    assert result.upper == pytest.approx(0.10495443589637815, rel=1e-6)


def test_all_occurrences_boundary_is_finite_not_nan():
    """n_occurred=n_runs is a genuine, well-defined Wilson boundary case -
    unlike `mean_confidence_interval`, which needs >=2 points and returns
    NaN below that, a proportion's interval is defined for any n_runs >= 1."""
    rows = [(run, "other") for run in range(1, 11)]
    log = _log(rows)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = event_occurrence_rate(log, "other", n_runs=10)

    assert result.n_occurred == 10
    assert result.proportion == pytest.approx(1.0)
    assert result.lower == pytest.approx(0.7224672001371106, rel=1e-6)
    assert result.upper == pytest.approx(1.0, rel=1e-6)


def test_never_occurred_boundary_is_finite_not_nan():
    """n_occurred=0 out of n_runs=10: hand-computed lower=0.0,
    upper=0.27753279986288926."""
    log = _log([(run, "other") for run in range(1, 11)])

    result = event_occurrence_rate(log, "target", n_runs=10)

    assert result.n_occurred == 0
    assert result.proportion == pytest.approx(0.0)
    assert result.lower == pytest.approx(0.0)
    assert result.upper == pytest.approx(0.27753279986288926, rel=1e-6)


def test_event_name_absent_from_the_whole_log_is_a_valid_zero_result():
    """Unlike `event_durations`, a name matching nothing is not an error -
    it is the `proportion=0.0` result a genuinely rare, unobserved event
    should report."""
    log = _log([(run, "other") for run in range(1, 4)])

    result = event_occurrence_rate(log, "never_seen", n_runs=3)

    assert result.n_occurred == 0
    assert result.proportion == pytest.approx(0.0)


def test_n_runs_defaults_to_distinct_runs_in_the_whole_log_not_just_matches():
    """Without an explicit `n_runs`, the denominator comes from every run in
    the log, not just the runs that logged the target event - a run that
    logs no matching rows at all must still count."""
    rows = [(run, "other") for run in range(1, 4)]
    rows += [(1, "rare")]
    log = _log(rows)

    result = event_occurrence_rate(log, "rare")

    assert result.n_runs == 3
    assert result.n_occurred == 1


def test_explicit_n_runs_overrides_the_log_derived_count():
    """This is the wiring `TrialLogger.get_event_occurrence_rate` relies on:
    a run that logs nothing at all is invisible to any log-derived count, so
    the true run count must be passable explicitly - modelled directly on
    the historical `_summarise_durations` `n_runs` bug (see HISTORY.md)."""
    rows = [(run, "other") for run in range(1, 3)]
    rows += [(1, "rare")]
    log = _log(rows)

    # Only 2 runs appear in the log at all, but the trial actually has 3 -
    # the third run logged nothing (not even "other").
    result = event_occurrence_rate(log, "rare", n_runs=3)

    assert result.n_runs == 3
    assert result.n_occurred == 1
    assert result.proportion == pytest.approx(1 / 3)


def test_ci_level_out_of_range_raises():
    log = _log([(1, "arrival")])

    with pytest.raises(ValueError, match="ci_level"):
        event_occurrence_rate(log, "arrival", ci_level=1.5)


def test_no_low_n_warning_unlike_mean_confidence_interval():
    """A single replication is enough for a well-defined Wilson interval -
    no warning, unlike `mean_confidence_interval`'s n<2 case."""
    log = _log([(1, "arrival")])

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = event_occurrence_rate(log, "arrival", n_runs=1)

    assert result.n_runs == 1
    assert result.proportion == pytest.approx(1.0)


def test_returns_a_proportion_estimate_namedtuple():
    log = _log([(1, "arrival")])

    result = event_occurrence_rate(log, "arrival", n_runs=1)

    assert isinstance(result, ProportionEstimate)
