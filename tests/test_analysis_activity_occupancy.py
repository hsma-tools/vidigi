"""Tests for `vidigi.analysis.activity_occupancy_stats`.

The per-snapshot occupancy series it reduces is `queue_size_over_time` /
`resource_occupancy_over_time`, both already covered by value elsewhere; the
numbers here pin the *reduction* - mean/min/max/median, and how the two
`across_runs` modes combine several runs.
"""

import pytest

from vidigi.analysis import activity_occupancy_stats
from vidigi.logging import EventLogger, TrialLogger


def _trial_df(loggers):
    return TrialLogger(loggers).to_dataframe()


def _stats_map(stats):
    """``{event: (kind, mean, min, max, median)}`` rounded, for whole-mapping
    assertions rather than spot checks."""
    return {
        row.event: (
            row.kind,
            round(float(row.mean_occupancy), 4),
            round(float(row.min_occupancy), 4),
            round(float(row.max_occupancy), 4),
            round(float(row.median_occupancy), 4),
        )
        for row in stats.itertuples()
    }


# --------------------------------------------------------------------------- #
# across_runs: the one real decision this function makes
# --------------------------------------------------------------------------- #


@pytest.fixture
def diverging_queue_loggers():
    """Two runs whose per-run queue statistics differ.

    Snapshots 0, 10, 20 (``every_x_time_units=10``, ``limit_duration=20``):

    ====  =====  =====
    snap  run 1  run 2
    ====  =====  =====
    0     2      1
    10    1      0
    20    1      0
    ====  =====  =====

    - ``"pool"`` over [2, 1, 1, 1, 0, 0]: mean 5/6, min 0, max 2, median 1.0
    - ``"average"``: run 1 (mean 4/3, min 1, max 2, median 1) and run 2
      (mean 1/3, min 0, max 1, median 0), averaged: mean 5/6, min 0.5,
      max 1.5, median 0.5

    So the two modes agree on the mean but disagree on min, max and median -
    swapping them in the implementation fails this test three ways over.
    """
    run1 = EventLogger(run_number=1)
    run1.log_arrival(entity_id="a", time=0.0)
    run1.log_queue(entity_id="a", event="waiting", time=0.0)
    run1.log_departure(entity_id="a", time=100.0)
    run1.log_arrival(entity_id="b", time=0.0)
    run1.log_queue(entity_id="b", event="waiting", time=0.0)
    run1.log_departure(entity_id="b", time=5.0)

    run2 = EventLogger(run_number=2)
    run2.log_arrival(entity_id="c", time=0.0)
    run2.log_queue(entity_id="c", event="waiting", time=0.0)
    run2.log_departure(entity_id="c", time=5.0)
    return [run1, run2]


def test_across_runs_average_and_pool_give_different_answers(diverging_queue_loggers):
    event_log = _trial_df(diverging_queue_loggers)
    common = dict(every_x_time_units=10, limit_duration=20)

    average = activity_occupancy_stats(event_log, across_runs="average", **common)
    pooled = activity_occupancy_stats(event_log, across_runs="pool", **common)

    assert _stats_map(average) == {
        "waiting": ("queue", round(5 / 6, 4), 0.5, 1.5, 0.5)
    }
    assert _stats_map(pooled) == {
        "waiting": ("queue", round(5 / 6, 4), 0.0, 2.0, 1.0)
    }


def test_single_run_gives_the_same_answer_either_way(long_queue_logger):
    event_log = _trial_df([long_queue_logger])
    common = dict(every_x_time_units=10, limit_duration=30)

    average = _stats_map(activity_occupancy_stats(event_log, across_runs="average", **common))
    pooled = _stats_map(activity_occupancy_stats(event_log, across_runs="pool", **common))

    assert average == pooled


def test_invalid_across_runs_raises(resource_log):
    with pytest.raises(ValueError, match="across_runs"):
        activity_occupancy_stats(resource_log, across_runs="nonsense")


# --------------------------------------------------------------------------- #
# The reduction itself
# --------------------------------------------------------------------------- #


def test_empty_snapshots_count_as_real_zero(emptying_queue_loggers):
    """A queue empty for half the run pulls the mean down; it is not averaged
    only over the snapshots where somebody was waiting."""
    event_log = _trial_df(emptying_queue_loggers)

    stats = activity_occupancy_stats(
        event_log, every_x_time_units=10, limit_duration=30
    )

    assert _stats_map(stats) == {"waiting": ("queue", 0.5, 0.0, 1.0, 0.5)}


def test_queue_length_is_not_capped_at_the_animation_display_limit(long_queue_logger):
    """150 entities queue at once - the figure must be 150, not the
    `step_snapshot_max` display cap `reshape_for_animations` uses."""
    event_log = _trial_df([long_queue_logger])

    stats = activity_occupancy_stats(
        event_log, every_x_time_units=10, limit_duration=30
    )

    assert _stats_map(stats) == {"waiting": ("queue", 150.0, 150.0, 150.0, 150.0)}


def test_queue_and_resource_steps_are_both_reported_and_tagged(resource_log):
    stats = activity_occupancy_stats(
        resource_log, every_x_time_units=10, limit_duration=50
    )

    assert _stats_map(stats) == {
        "waiting": ("queue", 0.5, 0.0, 1.0, 0.5),
        "treatment_begins": ("resource", 0.6667, 0.0, 1.0, 1.0),
    }


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #


def test_event_logged_as_both_queue_and_resource_warns_and_is_queue_only():
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_queue(entity_id=1, event="triage", time=0.0)
    logger.log_resource_use_start(
        entity_id=1, resource_id=1, time=1.0, event="triage"
    )
    logger.log_resource_use_end(
        entity_id=1, resource_id=1, time=2.0, event="triage_end"
    )
    logger.log_departure(entity_id=1, time=2.0)

    with pytest.warns(UserWarning, match="both event_type 'queue' and 'resource_use'"):
        stats = activity_occupancy_stats(
            logger.to_dataframe(), every_x_time_units=1, limit_duration=2
        )

    assert list(stats["kind"]) == ["queue"]
    assert list(stats["event"]) == ["triage"]


def test_log_with_no_queue_or_resource_steps_returns_an_empty_frame():
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_departure(entity_id=1, time=5.0)

    stats = activity_occupancy_stats(
        logger.to_dataframe(), every_x_time_units=1, limit_duration=5
    )

    assert stats.empty
    assert list(stats.columns) == [
        "event",
        "kind",
        "mean_occupancy",
        "min_occupancy",
        "max_occupancy",
        "median_occupancy",
    ]


def test_include_queues_false_skips_queue_steps(resource_log):
    stats = activity_occupancy_stats(
        resource_log,
        every_x_time_units=10,
        limit_duration=50,
        include_queues=False,
    )

    assert set(stats["kind"]) == {"resource"}
    assert "waiting" not in set(stats["event"])


def test_include_resources_false_skips_resource_steps(resource_log):
    stats = activity_occupancy_stats(
        resource_log,
        every_x_time_units=10,
        limit_duration=50,
        include_resources=False,
    )

    assert set(stats["kind"]) == {"queue"}
