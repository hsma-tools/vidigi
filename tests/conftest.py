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
def warm_up_log():
    """A run with a 100-time-unit warm-up worth of history before the window.

    Five entities join the queue during the warm-up and are *still queuing* well
    past it; two more join at t=110; one arrives and departs entirely within the
    warm-up. Nobody departs until t=300.

    With ``every_x_time_units=10`` and ``limit_duration=200`` the queue at
    snapshot 120 holds entities 1-7. Truncating this log with
    ``log[log["time"] >= 100]`` leaves only 6 and 7 there, because the arrival
    rows of 1-5 have been removed - the trap ``warm_up`` exists to avoid.
    """
    specs = []
    for entity_id in range(1, 6):
        specs.append((10 * entity_id, entity_id, "arrival_departure", "arrival"))
        specs.append((10 * entity_id, entity_id, "queue", "waiting"))
        specs.append((300, entity_id, "arrival_departure", "depart"))
    for entity_id in (6, 7):
        specs.append((110, entity_id, "arrival_departure", "arrival"))
        specs.append((110, entity_id, "queue", "waiting"))
        specs.append((300, entity_id, "arrival_departure", "depart"))
    # Arrives and leaves entirely within the warm-up, so must not appear at all
    # once the window starts at 100.
    specs.append((10, 8, "arrival_departure", "arrival"))
    specs.append((10, 8, "queue", "waiting"))
    specs.append((50, 8, "arrival_departure", "depart"))
    return _rows(*specs)


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
def unequal_run_loggers():
    """Three runs with different entity counts, so run means diverge from the pooled mean.

    Run 1: 2 entities x duration 4. Run 2: 4 entities x duration 5. Run 3: 2 entities x
    duration 9. Unlike ``two_run_loggers``, every duration is *not* the same value, so
    ``std`` (and every CI half-width) is non-zero, and ``across="runs"`` gives a
    genuinely different answer from ``across="entities"``.

    Hand-computed for ``event_durations(..., "arrival", "depart")``:

    ==========================  ==============
    quantity                    value
    ==========================  ==============
    run means                   [4, 5, 9]
    mean of run means           6.0
    pooled entity mean          46/8 = 5.75
    sample std (ddof=1)         sqrt(7) ~= 2.6458
    standard error (n=3)        ~= 1.5275
    t_0.975,2 (published table) 4.302653
    CI half-width               ~= 6.5724
    cumulative means            [4.0, 4.5, 6.0]
    ==========================  ==============
    """

    def _run(run_number, n_entities, duration):
        logger = EventLogger(run_number=run_number)
        for entity_id in range(1, n_entities + 1):
            logger.log_arrival(entity_id=entity_id, time=0.0)
            logger.log_departure(entity_id=entity_id, time=float(duration))
        return logger

    return [_run(1, 2, 4), _run(2, 4, 5), _run(3, 2, 9)]


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
def rework_loop_logger():
    """One entity that revisits 'assessment' before its final 'treated'.

    Entity 1 hits 'assessment' at t=1 and t=20, then 'treated' at t=5 and t=30 - a
    rework loop the old pivot-based duration calculation cannot represent (it raises,
    since `pivot` cannot place two 'assessment' times in one cell).

    ``event_durations(..., "assessment", "treated", match=...)`` gives:

    ==============  ===========
    match           duration
    ==============  ===========
    "first"         [4]   (5 - 1)
    "last"          [10]  (30 - 20)
    "occurrence"    [4, 10]
    ==============  ===========
    """
    logger = EventLogger(run_number=1)
    logger.log_custom_event(
        entity_id=1, event_type="milestone", event="assessment", time=1.0
    )
    logger.log_custom_event(
        entity_id=1, event_type="milestone", event="treated", time=5.0
    )
    logger.log_custom_event(
        entity_id=1, event_type="milestone", event="assessment", time=20.0
    )
    logger.log_custom_event(
        entity_id=1, event_type="milestone", event="treated", time=30.0
    )
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


@pytest.fixture
def resource_use_loggers():
    """Two runs, one step ("treatment_begins"/"treatment_ends"), 3 resource units,
    window 0-20 (pass ``limit_duration=20`` explicitly in tests).

    ==============  =========  =========  =========  =====
    resource_id     run 1      run 2      busy (r1)  busy (r2)
    ==============  =========  =========  =========  =====
    1               0 -> 10    (idle)     10         0
    2               0 -> 5     0 -> 20    5          20
    3               (idle)     5 -> 15    0          10
    ==============  =========  =========  =========  =====

    Hand-computed, with ``resource_capacities={"treatment_begins": 3}``:

    - run 1: busy ``{1: 10, 2: 5, 3: 0}``, total 15, ``mean_in_use`` 0.75,
      ``utilisation`` 0.25
    - run 2: busy ``{1: 0, 2: 20, 3: 10}``, total 30, ``mean_in_use`` 1.5,
      ``utilisation`` 0.5

    Resource 3 being idle in run 1 (but used in run 2) is what proves a
    resource unused in one run still reports a genuine zero there, rather than
    being silently absent - the same convention as `queue_size_over_time`.
    """
    run1 = EventLogger(run_number=1)
    run1.log_resource_use_start(
        entity_id=1, resource_id=1, time=0.0, event="treatment_begins"
    )
    run1.log_resource_use_end(
        entity_id=1, resource_id=1, time=10.0, event="treatment_ends"
    )
    run1.log_resource_use_start(
        entity_id=2, resource_id=2, time=0.0, event="treatment_begins"
    )
    run1.log_resource_use_end(
        entity_id=2, resource_id=2, time=5.0, event="treatment_ends"
    )

    run2 = EventLogger(run_number=2)
    run2.log_resource_use_start(
        entity_id=1, resource_id=2, time=0.0, event="treatment_begins"
    )
    run2.log_resource_use_end(
        entity_id=1, resource_id=2, time=20.0, event="treatment_ends"
    )
    run2.log_resource_use_start(
        entity_id=2, resource_id=3, time=5.0, event="treatment_begins"
    )
    run2.log_resource_use_end(
        entity_id=2, resource_id=3, time=15.0, event="treatment_ends"
    )

    return [run1, run2]


@pytest.fixture
def unclosed_resource_use_logger():
    """One run: a resource use starting at t=15, never closed, window end 20
    (pass ``limit_duration=20`` explicitly in tests).

    With ``unclosed="censor"`` (the default), the interval is censored at the
    window end: ``busy_time == 5`` (20 - 15), ``censored == True``, and a
    warning is raised. Asserting ``busy_time == 5`` rather than ``0`` is what
    pins that the entity is not simply dropped.
    """
    logger = EventLogger(run_number=1)
    logger.log_resource_use_start(
        entity_id=1, resource_id=1, time=15.0, event="treatment_begins"
    )
    return logger


@pytest.fixture
def resource_use_no_resource_id_logger():
    """One run: a resource use start/end pair logged with no ``resource_id`` at
    all, via `log_event` directly (the `log_resource_use_start`/`_end` helpers
    require `resource_id`, so it cannot be omitted through them).

    ``to_dataframe()`` therefore has no `resource_id` column at all - this is
    what exercises `resource_use_intervals`' `(run, entity)`-only pairing
    fallback and its warning, rather than the "some rows null, some not" error
    case. The pairing still finds the interval: entity 1, "treatment_begins" at
    t=0 to t=10, busy_time 10.
    """
    logger = EventLogger(run_number=1)
    logger.log_event(
        entity_id=1,
        event_type="resource_use",
        event="treatment_begins",
        time=0.0,
        run_number=1,
    )
    logger.log_event(
        entity_id=1,
        event_type="resource_use_end",
        event="treatment_ends",
        time=10.0,
        run_number=1,
    )
    return logger


@pytest.fixture
def colliding_pools_logger():
    """One run: two entities hold `resource_id=1` at genuinely overlapping
    times, under two different step names - simulating two independent
    resource pools (e.g. two `VidigiStore`s) that both numbered their units
    from 1. Entity 1 holds it 0->10 ("triage_begins"); entity 2 holds it
    5->15 ("registration_begins") - overlapping from t=5 to t=10, which is
    impossible for one physical unit. This is what `by="resource"`'s overlap
    check must catch.
    """
    logger = EventLogger(run_number=1)
    logger.log_resource_use_start(
        entity_id=1, resource_id=1, time=0.0, event="triage_begins"
    )
    logger.log_resource_use_end(
        entity_id=1, resource_id=1, time=10.0, event="triage_ends"
    )
    logger.log_resource_use_start(
        entity_id=2, resource_id=1, time=5.0, event="registration_begins"
    )
    logger.log_resource_use_end(
        entity_id=2, resource_id=1, time=15.0, event="registration_ends"
    )
    return logger


@pytest.fixture
def shared_pool_across_steps_logger():
    """One run: `resource_id=1` is reused *sequentially, non-overlapping*
    across two different step names - entity 1 holds it 0->5
    ("triage_begins"), entity 2 holds it 10->15 ("registration_begins"). One
    real physical resource legitimately used for more than one step. Must
    *not* trigger the overlap warning, and `by="resource"` must still return
    exactly one row for resource_id=1, not one per step - proof that the
    overlap check doesn't reintroduce the "split one physical unit" failure
    mode the grouping key was deliberately kept as-is to avoid.
    """
    logger = EventLogger(run_number=1)
    logger.log_resource_use_start(
        entity_id=1, resource_id=1, time=0.0, event="triage_begins"
    )
    logger.log_resource_use_end(
        entity_id=1, resource_id=1, time=5.0, event="triage_ends"
    )
    logger.log_resource_use_start(
        entity_id=2, resource_id=1, time=10.0, event="registration_begins"
    )
    logger.log_resource_use_end(
        entity_id=2, resource_id=1, time=15.0, event="registration_ends"
    )
    return logger
