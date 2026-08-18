"""Tests for the single-replication guard on the animation pipeline.

Passing an event log containing several replications used to produce a blended
animation rather than an error: the arrival/departure pivot averages an entity's
arrival times across runs, so the entity is drawn as present at a moment it
existed in no run at all. Nothing raised, nothing warned, and every downstream
invariant still held, because the resulting frame is internally consistent and
entirely fictional.

Two independent checks now reject this, because neither alone is sufficient:

* the **run column** check catches a multi-run log even when entity IDs happen to
  be unique across runs, where nothing looks structurally wrong
* the **duplicate arrival** check catches a log whose run column is named
  something unrecognised, or absent entirely - and also catches entity IDs reused
  within a single run, which is the same corruption from a different cause
"""

import pandas as pd
import plotly.graph_objects as go
import pytest

from vidigi.animation import animate_activity_log, generate_animation
from vidigi.logging import EventLogger, TrialLogger
from vidigi.prep import generate_animation_df, reshape_for_animations
from vidigi.utils import RUN_COLUMN_CANDIDATES


def reshaped_two_runs(log, event_position_df=None):
    """A reshaped frame spanning two runs, as produced by concatenating per-run output."""
    parts = [
        reshape_for_animations(
            log[log["run"] == run], every_x_time_units=10, limit_duration=150
        ).assign(run=run)
        for run in (1, 2)
    ]
    return pd.concat(parts, ignore_index=True)


def positioned_two_runs(log, event_position_df):
    """A positioned frame spanning two runs."""
    parts = []
    for run in (1, 2):
        reshaped = reshape_for_animations(
            log[log["run"] == run], every_x_time_units=10, limit_duration=150
        )
        parts.append(
            generate_animation_df(reshaped, event_position_df).assign(run=run)
        )
    return pd.concat(parts, ignore_index=True)


# --------------------------------------------------------------------------- #
# All four entry points reject a multi-replication input
# --------------------------------------------------------------------------- #


def test_reshape_rejects_multi_run_log(multi_run_log):
    with pytest.raises(ValueError, match="spans 2 replications"):
        reshape_for_animations(multi_run_log, every_x_time_units=10, limit_duration=50)


def test_animate_activity_log_rejects_multi_run_log(
    multi_run_log, basic_event_position_df
):
    with pytest.raises(ValueError, match="spans 2 replications"):
        animate_activity_log(
            multi_run_log, basic_event_position_df, limit_duration=50
        )


def test_generate_animation_df_rejects_multi_run_frame(
    multi_run_log, basic_event_position_df
):
    """Someone running the three steps by hand must not slip past the guard."""
    frame = reshaped_two_runs(multi_run_log)

    with pytest.raises(ValueError, match="spans 2 replications"):
        generate_animation_df(frame, basic_event_position_df)


def test_generate_animation_rejects_multi_run_frame(
    multi_run_log, basic_event_position_df
):
    frame = positioned_two_runs(multi_run_log, basic_event_position_df)

    with pytest.raises(ValueError, match="spans 2 replications"):
        generate_animation(frame, basic_event_position_df)


def test_error_message_is_actionable(multi_run_log):
    """The message must name the column and show a filter the user can copy."""
    with pytest.raises(ValueError) as excinfo:
        reshape_for_animations(multi_run_log, every_x_time_units=10, limit_duration=50)

    message = str(excinfo.value)

    assert "'run'" in message
    assert 'event_log[event_log["run"] == 1]' in message
    assert "get_log_by_run" in message
    assert "run_col_name" in message


# --------------------------------------------------------------------------- #
# Column name detection
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("column", RUN_COLUMN_CANDIDATES)
def test_all_candidate_column_names_are_detected(simple_queue_log, column):
    log = pd.concat(
        [simple_queue_log.assign(**{column: 1}), simple_queue_log.assign(**{column: 2})],
        ignore_index=True,
    )

    with pytest.raises(ValueError, match=f"'{column}'"):
        reshape_for_animations(log, every_x_time_units=10, limit_duration=50)


@pytest.mark.parametrize("column", ["Run", "RUN", "Run_Number", "Replication"])
def test_column_detection_is_case_insensitive(simple_queue_log, column):
    log = pd.concat(
        [simple_queue_log.assign(**{column: 1}), simple_queue_log.assign(**{column: 2})],
        ignore_index=True,
    )

    with pytest.raises(ValueError, match="replications"):
        reshape_for_animations(log, every_x_time_units=10, limit_duration=50)


def test_custom_run_column_name(simple_queue_log):
    """A column vidigi would not guess is still usable if the caller names it."""
    log = pd.concat(
        [simple_queue_log.assign(scenario_iteration=1),
         simple_queue_log.assign(scenario_iteration=2)],
        ignore_index=True,
    )

    with pytest.raises(ValueError, match="'scenario_iteration'"):
        reshape_for_animations(
            log,
            every_x_time_units=10,
            limit_duration=50,
            run_col_name="scenario_iteration",
        )


def test_named_run_column_must_exist(simple_queue_log):
    with pytest.raises(ValueError, match="not present"):
        reshape_for_animations(
            simple_queue_log,
            every_x_time_units=10,
            limit_duration=50,
            run_col_name="nonexistent",
        )


# --------------------------------------------------------------------------- #
# The structural check: duplicate arrivals
# --------------------------------------------------------------------------- #


def test_duplicate_arrivals_rejected_without_a_run_column(simple_queue_log):
    """A concatenated log with no run column at all is still caught.

    This is the check that does not depend on guessing a column name.
    """
    log = pd.concat([simple_queue_log, simple_queue_log], ignore_index=True)

    with pytest.raises(ValueError, match="more than one 'arrival' event"):
        reshape_for_animations(log, every_x_time_units=10, limit_duration=50)


def test_reused_entity_ids_within_one_run_are_rejected():
    """Same corruption, different cause: two entities sharing an ID.

    The pivot would average their arrival times together exactly as it does
    across replications.
    """
    log = pd.DataFrame(
        {
            "time": [0, 0, 10, 20, 20, 30],
            "entity_id": [1, 1, 1, 1, 1, 1],
            "event_type": [
                "arrival_departure", "queue", "arrival_departure",
                "arrival_departure", "queue", "arrival_departure",
            ],
            "event": ["arrival", "waiting", "depart", "arrival", "waiting", "depart"],
        }
    )

    with pytest.raises(ValueError, match="entity IDs are reused"):
        reshape_for_animations(log, every_x_time_units=10, limit_duration=50)


def test_structural_check_still_applies_when_run_check_disabled(simple_queue_log):
    """Disabling the run-column check must not disable the corruption check."""
    log = pd.concat(
        [simple_queue_log.assign(run=1), simple_queue_log.assign(run=2)],
        ignore_index=True,
    )

    with pytest.raises(ValueError, match="more than one 'arrival' event"):
        reshape_for_animations(
            log, every_x_time_units=10, limit_duration=50, run_col_name=None
        )


def test_run_column_check_catches_what_the_structural_check_cannot(simple_queue_log):
    """Globally unique entity IDs across runs leave no structural trace.

    Nothing is duplicated, so only the run-column check can see the problem.
    This is why both checks exist.
    """
    second = simple_queue_log.copy()
    second["entity_id"] = second["entity_id"] + 100
    log = pd.concat(
        [simple_queue_log.assign(run=1), second.assign(run=2)], ignore_index=True
    )

    # Confirm the structural check genuinely cannot fire here.
    arrivals = log[(log["event_type"] == "arrival_departure") & (log["event"] == "arrival")]
    assert (arrivals.groupby("entity_id").size() == 1).all()

    with pytest.raises(ValueError, match="spans 2 replications"):
        reshape_for_animations(log, every_x_time_units=10, limit_duration=50)


def test_pathway_column_is_part_of_the_grouping(simple_queue_log):
    """The check groups by the same keys the pivot indexes on.

    With a pathway column the pivot indexes on entity+pathway, so the duplicate
    check must too, or it would reject input the pivot handles correctly.
    """
    log = simple_queue_log.assign(pathway="A")

    result = reshape_for_animations(
        log, every_x_time_units=10, limit_duration=50, pathway_col_name="pathway"
    )

    assert not result.empty


# --------------------------------------------------------------------------- #
# False positives - the failure mode that would be worse than the bug
# --------------------------------------------------------------------------- #


def test_single_run_log_with_a_run_column_is_accepted(
    single_run_log_with_run_column, basic_event_position_df
):
    """A valid single-replication log must animate, run column and all."""
    fig = animate_activity_log(
        single_run_log_with_run_column, basic_event_position_df, limit_duration=50
    )

    assert isinstance(fig, go.Figure)


def test_log_without_any_run_column_is_accepted(
    simple_queue_log, basic_event_position_df
):
    fig = animate_activity_log(
        simple_queue_log, basic_event_position_df, limit_duration=50
    )

    assert isinstance(fig, go.Figure)


def test_run_column_with_a_single_value_across_many_rows(simple_queue_log):
    """One distinct value is one replication, however many rows carry it."""
    log = simple_queue_log.assign(run_number=7)

    result = reshape_for_animations(log, every_x_time_units=10, limit_duration=50)

    assert not result.empty


def test_null_values_in_the_run_column_do_not_trip_the_guard(simple_queue_log):
    """NaNs are ignored rather than counted as a second replication."""
    log = simple_queue_log.assign(run=1.0)
    log.loc[log.index[0], "run"] = None

    result = reshape_for_animations(log, every_x_time_units=10, limit_duration=50)

    assert not result.empty


def test_trial_logger_plot_queue_size_still_works(two_run_loggers):
    """TrialLogger reshapes one run at a time and must not trip the guard.

    Its logs carry a run_number column, so a guard checking the wrong thing
    would break multi-run plotting entirely.
    """
    trial = TrialLogger(two_run_loggers)

    fig = trial.plot_queue_size(event_list=["waiting"], limit_duration=20)

    assert isinstance(fig, go.Figure)


def test_event_logger_output_animates(basic_event_position_df):
    """A single EventLogger's own output carries run_number and must be accepted."""
    logger = EventLogger(run_number=3)
    for entity_id in (1, 2):
        logger.log_arrival(entity_id=entity_id, time=float(entity_id))
        logger.log_queue(entity_id=entity_id, event="waiting", time=float(entity_id) + 1)
        logger.log_departure(entity_id=entity_id, time=float(entity_id) + 20)

    fig = animate_activity_log(
        logger.to_dataframe(), basic_event_position_df, limit_duration=30
    )

    assert isinstance(fig, go.Figure)


# --------------------------------------------------------------------------- #
# Real data
# --------------------------------------------------------------------------- #


def test_real_trial_output_is_rejected_unfiltered_and_accepted_filtered(
    basic_event_position_df,
):
    """The repo's own sample model, which produces 100 replications.

    Unfiltered it has 148 entities carrying up to 100 arrivals each - the exact
    shape a modeller would hand over at the end of a study.
    """
    from tests.sample_models.simple_fifo_with_logging_storewrapper import Trial

    trial = Trial()
    trial.run_trial()
    log = trial.all_event_logs

    event_positions = pd.DataFrame(
        [
            {"event": "arrival", "x": 50, "y": 300, "label": "Arrival"},
            {"event": "treatment_wait_begins", "x": 205, "y": 275, "label": "Wait"},
            {
                "event": "treatment_begins", "x": 205, "y": 175,
                "resource": "n_cubicles", "label": "Treated",
            },
            {"event": "depart", "x": 270, "y": 70, "label": "Exit"},
        ]
    )

    with pytest.raises(ValueError, match="spans 100 replications"):
        animate_activity_log(log, event_positions, limit_duration=100)

    fig = animate_activity_log(
        log[log["run"] == 1], event_positions, limit_duration=100
    )
    assert isinstance(fig, go.Figure)
