"""Shared fixtures for the vidigi test suite.

The logs defined here are deliberately small and hand-computable so that tests
can assert exact positions, ranks and snapshot membership rather than just
shapes and column names.
"""

import pandas as pd
import pytest

from vidigi.logging import EventLogger
from vidigi.utils import EventPosition, create_event_position_df


def _rows(*specs):
    """Build an event log from (time, entity_id, event_type, event) tuples."""
    return pd.DataFrame(
        [
            {
                "time": time,
                "entity_id": entity_id,
                "event_type": event_type,
                "event": event,
            }
            for time, entity_id, event_type, event in specs
        ]
    )


@pytest.fixture
def simple_queue_log():
    """Three entities that arrive, wait in one queue, and depart.

    With ``every_x_time_units=10`` and ``limit_duration=50`` the snapshots are
    0, 10, 20, 30, 40, 50 and membership is fully determined:

    ==============  ==================
    snapshot_time   entities present
    ==============  ==================
    0               1
    10              1, 2
    20              1, 2, 3
    30              2, 3
    40              3
    50              (none)
    ==============  ==================
    """
    return _rows(
        (0, 1, "arrival_departure", "arrival"),
        (0, 1, "queue", "waiting"),
        (25, 1, "arrival_departure", "depart"),
        (5, 2, "arrival_departure", "arrival"),
        (5, 2, "queue", "waiting"),
        (35, 2, "arrival_departure", "depart"),
        (12, 3, "arrival_departure", "arrival"),
        (12, 3, "queue", "waiting"),
        (45, 3, "arrival_departure", "depart"),
    )


@pytest.fixture
def overflow_queue_log():
    """Twelve entities joining a single queue at t=1..12, departing at t=101..112.

    All twelve are simultaneously present at snapshot 20, which makes this
    useful for exercising ``step_snapshot_max`` and queue wrapping.
    """
    specs = []
    for entity_id in range(1, 13):
        specs.append((entity_id, entity_id, "arrival_departure", "arrival"))
        specs.append((entity_id, entity_id, "queue", "waiting"))
        specs.append((100 + entity_id, entity_id, "arrival_departure", "depart"))
    return _rows(*specs)


@pytest.fixture
def resource_log():
    """Two entities that queue, use a resource, then depart."""
    df = _rows(
        (0, 1, "arrival_departure", "arrival"),
        (0, 1, "queue", "waiting"),
        (10, 1, "resource_use", "treatment_begins"),
        (30, 1, "resource_use_end", "treatment_ends"),
        (30, 1, "arrival_departure", "depart"),
        (5, 2, "arrival_departure", "arrival"),
        (5, 2, "queue", "waiting"),
        (30, 2, "resource_use", "treatment_begins"),
        (50, 2, "resource_use_end", "treatment_ends"),
        (50, 2, "arrival_departure", "depart"),
    )
    df["resource_id"] = [None, None, 1, 1, None, None, None, 2, 2, None]
    return df


@pytest.fixture
def no_departure_log():
    """Entities that arrive and queue but never depart.

    This is what a truncated run, or a model whose entities never leave, looks
    like. The pivoted log has no ``depart`` column at all.
    """
    return _rows(
        (0, 1, "arrival_departure", "arrival"),
        (0, 1, "queue", "waiting"),
        (5, 2, "arrival_departure", "arrival"),
        (5, 2, "queue", "waiting"),
    )


@pytest.fixture
def multi_run_log(simple_queue_log):
    """The same three entities simulated twice, concatenated with a `run` column.

    This is the natural artefact at the end of a replicated DES study, and the
    shape that used to produce a silently blended animation: entity 1 arrives at
    t=0 in run 1 and t=100 in run 2, which the arrival/departure pivot would
    average to t=50 - a moment it existed in neither run.
    """
    first = simple_queue_log.assign(run=1)
    second = simple_queue_log.assign(run=2)
    second["time"] = second["time"] + 100
    return pd.concat([first, second], ignore_index=True)


@pytest.fixture
def single_run_log_with_run_column(simple_queue_log):
    """One replication that nonetheless carries a run column.

    Completely valid input. The guard must not reject it.
    """
    return simple_queue_log.assign(run=1)


@pytest.fixture
def basic_event_position_df():
    """Positions for the events used by the log fixtures.

    Built through the documented ``EventPosition`` route so the fixture
    exercises that path rather than hand-rolling the DataFrame.
    """
    return create_event_position_df(
        [
            EventPosition(event="arrival", x=50, y=300, label="Arrival"),
            EventPosition(event="waiting", x=400, y=275, label="Waiting"),
            EventPosition(
                event="treatment_begins",
                x=400,
                y=175,
                label="Being Treated",
                resource="n_cubicles",
            ),
            EventPosition(event="depart", x=270, y=70, label="Exit"),
        ]
    )


@pytest.fixture
def scenario_with_resources():
    """Minimal scenario object exposing the resource counts used above."""

    class _Scenario:
        n_cubicles = 3

    return _Scenario()


def _build_logger(run_number, unserved_entity=False):
    """One run: entities 1 and 2 arrive, wait, and depart 5 time units later."""
    logger = EventLogger(run_number=run_number)
    for entity_id in (1, 2):
        arrival = float(entity_id)
        logger.log_arrival(entity_id=entity_id, time=arrival)
        logger.log_queue(entity_id=entity_id, event="waiting", time=arrival + 1)
        logger.log_departure(entity_id=entity_id, time=arrival + 5)
    if unserved_entity:
        # Arrives and queues but never departs, so its duration is NaN.
        logger.log_arrival(entity_id=99, time=10.0)
        logger.log_queue(entity_id=99, event="waiting", time=11.0)
    return logger


@pytest.fixture
def single_run_logger():
    return _build_logger(run_number=1)


@pytest.fixture
def two_run_loggers():
    """Two runs, every arrival-to-depart duration exactly 5.0."""
    return [_build_logger(run_number=1), _build_logger(run_number=2)]


@pytest.fixture
def logger_with_unserved_entity():
    """One run where 2 of 3 entities depart, so unserved_rate is exactly 1/3."""
    return _build_logger(run_number=1, unserved_entity=True)


@pytest.fixture
def long_queue_logger():
    """One run where 150 entities queue simultaneously and none depart early.

    Deliberately far above the default ``step_snapshot_max`` of 60, so a queue
    length plot that inherits the animation's display cap saturates instead of
    reporting the queue that actually formed.
    """
    logger = EventLogger(run_number=1)
    for entity_id in range(1, 151):
        logger.log_arrival(entity_id=entity_id, time=0.0)
        logger.log_queue(entity_id=entity_id, event="waiting", time=0.0)
        logger.log_departure(entity_id=entity_id, time=100.0)
    return logger


@pytest.fixture
def emptying_queue_loggers():
    """Two runs whose single queue is occupied for opposite halves of the run.

    With ``limit_duration=30`` and ``every_x_time_units=10`` the snapshots are
    0, 10, 20, 30 and the queue length is fully determined:

    ==============  =======  =======  ======
    snapshot_time   run 1    run 2    mean
    ==============  =======  =======  ======
    0               1        0        0.5
    10              1        0        0.5
    20              0        1        0.5
    30              0        1        0.5
    ==============  =======  =======  ======

    Every zero here is a real, empty queue rather than an absence of data.
    """
    first = EventLogger(run_number=1)
    first.log_arrival(entity_id=1, time=0.0)
    first.log_queue(entity_id=1, event="waiting", time=0.0)
    first.log_departure(entity_id=1, time=15.0)

    second = EventLogger(run_number=2)
    second.log_arrival(entity_id=1, time=20.0)
    second.log_queue(entity_id=1, event="waiting", time=20.0)
    second.log_departure(entity_id=1, time=35.0)

    return [first, second]
