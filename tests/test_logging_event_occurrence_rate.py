"""Tests for `TrialLogger.get_event_occurrence_rate`.

A thin delegator over `vidigi.analysis.event_occurrence_rate` -
`test_analysis_event_occurrence_rate.py` covers the Wilson-interval
arithmetic, and separately proves that an explicit `n_runs` is needed
whenever a run logs none of the target event *and nothing else either* (the
historical `_summarise_durations` `n_runs` bug class - see HISTORY.md).
`TrialLogger.get_event_occurrence_rate` passes `n_runs=len(self._event_logs)`
explicitly as the more robust, always-correct route regardless of what any
individual run logged; this file checks that wiring, not a distinguishable
bug at this layer (every `EventLogger` in a `TrialLogger` logs at least one
event by construction, so the analysis function's own log-wide fallback
already agrees here in practice).
"""

from vidigi.logging import EventLogger, TrialLogger


def _run_with_event(run_number, log_target_event):
    logger = EventLogger(run_number=run_number)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_departure(entity_id=1, time=5.0)
    if log_target_event:
        logger.log_custom_event(
            entity_id=1, event_type="breach", event="capacity_breach", time=2.0
        )
    return logger


def test_n_runs_is_the_true_trial_run_count_not_just_runs_with_the_event():
    """3 runs total; the event occurs in only 1 of them."""
    loggers = [
        _run_with_event(1, log_target_event=True),
        _run_with_event(2, log_target_event=False),
        _run_with_event(3, log_target_event=False),
    ]
    trial = TrialLogger(loggers)

    result = trial.get_event_occurrence_rate("capacity_breach")

    assert result.n_runs == 3
    assert result.n_occurred == 1
    assert result.proportion == 1 / 3


def test_matches_the_analysis_function_called_with_the_same_n_runs():
    from vidigi.analysis import event_occurrence_rate

    loggers = [
        _run_with_event(1, log_target_event=True),
        _run_with_event(2, log_target_event=True),
        _run_with_event(3, log_target_event=False),
    ]
    trial = TrialLogger(loggers)

    result = trial.get_event_occurrence_rate("capacity_breach", ci_level=0.9)

    expected = event_occurrence_rate(
        trial.to_dataframe(), "capacity_breach", n_runs=3, ci_level=0.9
    )
    assert result == expected


def test_event_never_occurring_in_the_trial_gives_zero_not_an_error():
    loggers = [_run_with_event(1, log_target_event=False)]
    trial = TrialLogger(loggers)

    result = trial.get_event_occurrence_rate("capacity_breach")

    assert result.n_runs == 1
    assert result.n_occurred == 0
    assert result.proportion == 0.0
