"""Tests for `TrialLogger.get_outlier_runs`.

A thin delegator over `vidigi.analysis.flag_outlier_runs` -
`test_analysis_outliers.py` covers the fencing logic itself; this file
checks the delegation: argument forwarding and the empty-result error.
"""

import pytest

from vidigi.logging import EventLogger, TrialLogger


def _run(run_number, n_entities, duration):
    logger = EventLogger(run_number=run_number)
    for entity_id in range(1, n_entities + 1):
        logger.log_arrival(entity_id=entity_id, time=0.0)
        logger.log_departure(entity_id=entity_id, time=float(duration))
    return logger


@pytest.fixture
def six_run_loggers_with_one_outlier():
    """Six runs, all mean duration ~10, except run 6 at 13.0 - matches the
    hand-computed fence in `test_analysis_outliers.py`
    (Q1=9.625, Q3=10.875, 1.5x fence=[7.75, 12.75])."""
    durations = [10.0, 11.0, 9.0, 10.5, 9.5, 13.0]
    return [_run(i + 1, 1, d) for i, d in enumerate(durations)]


def test_flags_the_same_run_the_analysis_function_would(six_run_loggers_with_one_outlier):
    trial = TrialLogger(six_run_loggers_with_one_outlier)

    result = trial.get_outlier_runs("arrival", "depart")

    assert dict(zip(result["run_number"], result["is_outlier"])) == {
        1: False,
        2: False,
        3: False,
        4: False,
        5: False,
        6: True,
    }


def test_iqr_multiplier_is_forwarded(six_run_loggers_with_one_outlier):
    trial = TrialLogger(six_run_loggers_with_one_outlier)

    result = trial.get_outlier_runs("arrival", "depart", iqr_multiplier=3.0)

    assert not result["is_outlier"].any()


def test_no_complete_pairs_raises():
    """Both events are present (so the "event not found" check passes), but
    entity 1's arrival has no matching depart and entity 2's depart has no
    matching arrival - zero complete pairs."""
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_departure(entity_id=2, time=5.0)
    trial = TrialLogger([logger])

    with pytest.raises(ValueError, match="No complete"):
        trial.get_outlier_runs("arrival", "depart")
