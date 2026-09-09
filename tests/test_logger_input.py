"""`reshape_for_animations` / `animate_activity_log` accepting logger objects.

Both entry points can take a `vidigi.logging.EventLogger` or `TrialLogger`
directly in place of a DataFrame, calling `.to_dataframe()` internally; the
`run_number` argument then picks one replication out of a `TrialLogger`.
"""

import plotly.graph_objects as go
import pytest
from pandas.testing import assert_frame_equal

from vidigi.animation import animate_activity_log
from vidigi.logging import EventLogger, TrialLogger
from vidigi.prep import reshape_for_animations

RESHAPE_KW = dict(every_x_time_units=10, limit_duration=50)


def _logger(run_number, shift=0.0):
    """One run mirroring ``simple_queue_log``: entities present across the grid.

    ``shift`` nudges every timestamp so two runs differ in their event data, not
    only in the ``run_number`` column.
    """
    logger = EventLogger(run_number=run_number)
    for entity_id, arrival, depart in [(1, 0, 25), (2, 5, 35), (3, 12, 45)]:
        logger.log_arrival(entity_id=entity_id, time=arrival + shift)
        logger.log_queue(entity_id=entity_id, event="waiting", time=arrival + shift)
        logger.log_departure(entity_id=entity_id, time=depart + shift)
    return logger


# --- reshape_for_animations --------------------------------------------------


def test_eventlogger_matches_its_dataframe():
    logger = _logger(run_number=1)
    from_logger = reshape_for_animations(logger, **RESHAPE_KW)
    from_df = reshape_for_animations(logger.to_dataframe(), **RESHAPE_KW)
    assert_frame_equal(from_logger, from_df)


def test_single_run_triallogger_matches_its_dataframe():
    trial = TrialLogger([_logger(run_number=1)])
    from_trial = reshape_for_animations(trial, **RESHAPE_KW)
    from_df = reshape_for_animations(trial.to_dataframe(), **RESHAPE_KW)
    assert_frame_equal(from_trial, from_df)


def test_multi_run_triallogger_without_run_number_is_rejected():
    trial = TrialLogger([_logger(run_number=1), _logger(run_number=2)])
    with pytest.raises(
        ValueError, match=r"TrialLogger containing multiple runs \(\[1, 2\]\)"
    ):
        reshape_for_animations(trial, **RESHAPE_KW)


def test_run_number_selects_the_named_replication():
    trial = TrialLogger([_logger(run_number=1), _logger(run_number=2, shift=3.0)])
    selected = reshape_for_animations(trial, run_number=2, **RESHAPE_KW)
    expected = reshape_for_animations(trial.get_log_by_run(2, as_df=True), **RESHAPE_KW)
    # Whole-frame equality: picking the wrong run would still produce a
    # plausible-looking frame, so a spot check could pass by coincidence.
    assert_frame_equal(selected, expected)


def test_run_number_with_a_dataframe_is_rejected(simple_queue_log):
    with pytest.raises(ValueError, match="run_number"):
        reshape_for_animations(simple_queue_log, run_number=1, **RESHAPE_KW)


def test_run_number_with_an_eventlogger_is_rejected():
    with pytest.raises(ValueError, match="run_number"):
        reshape_for_animations(_logger(run_number=1), run_number=1, **RESHAPE_KW)


def test_unsupported_type_is_rejected():
    with pytest.raises(TypeError, match="DataFrame.*EventLogger.*TrialLogger"):
        reshape_for_animations([1, 2, 3], **RESHAPE_KW)


# --- animate_activity_log ---------------------------------------------------


def test_animate_accepts_an_eventlogger(basic_event_position_df):
    logger = _logger(run_number=1)
    from_logger = animate_activity_log(logger, basic_event_position_df, **RESHAPE_KW)
    from_df = animate_activity_log(
        logger.to_dataframe(), basic_event_position_df, **RESHAPE_KW
    )
    assert isinstance(from_logger, go.Figure)
    assert len(from_logger.frames) == len(from_df.frames)


def test_animate_accepts_a_triallogger_with_run_number(basic_event_position_df):
    trial = TrialLogger([_logger(run_number=1), _logger(run_number=2)])
    fig = animate_activity_log(
        trial, basic_event_position_df, run_number=1, **RESHAPE_KW
    )
    assert isinstance(fig, go.Figure)


def test_animate_rejects_a_multi_run_triallogger_without_run_number(
    basic_event_position_df,
):
    trial = TrialLogger([_logger(run_number=1), _logger(run_number=2)])
    with pytest.raises(
        ValueError, match=r"TrialLogger containing multiple runs \(\[1, 2\]\)"
    ):
        animate_activity_log(trial, basic_event_position_df, **RESHAPE_KW)
