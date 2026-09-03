"""Guard against using ``store.request()`` as a context manager without awaiting the request.

The correct pattern is ``with store.request(...) as req: resource = yield req``. Omitting the
``as req: yield req`` - entering the ``with`` block and going straight to
``yield env.timeout(...)`` - means the entity never actually waits for or holds the resource.
Its timeout runs immediately, it logs its departure, and the still-pending request is granted
to it *later*, when a unit frees up: a phantom ``resource_use`` row is logged after the
entity's ``depart``, with no matching end, and that unit is consumed by nobody.

In an animation this shows as the entity skipping from the queue straight to the exit
(vidigi decides presence at each snapshot from arrival/depart rows, and the departure now
precedes the resource-use row). This regressed a real example notebook
(``examples/feat_synchronised_traces``).

``_StoreRequest.__exit__`` / ``_OptimizedStoreRequest.__exit__`` now detect this (the get
event is unprocessed on block exit, which is impossible under correct use) and:

* emit a ``UserWarning`` naming the fix, unless an exception is already propagating;
* detach the start-of-use log callback so no phantom ``resource_use`` is logged;
* release the abandoned request - return the unit if one was already handed over, else drop
  the queued get.

Known gap, asserted below: a lone entity with a *free* resource whose spurious timeout
outlasts the (immediate) grant is not caught, because by its ``__exit__`` the event has been
processed. That case does not produce the visible "skips to the exit" symptom.
"""

import warnings

import pytest
import simpy

from vidigi.logging import EventLogger
from vidigi.resources import VidigiPriorityStore, VidigiStore


@pytest.fixture(params=[VidigiStore, VidigiPriorityStore])
def store_class(request):
    return request.param


def _pending_queue(store):
    """The queue of unfulfilled get requests, wherever the class keeps it."""
    if isinstance(store, VidigiStore):
        return store.store.get_queue
    return store.get_queue


def _units_available(store):
    return len(store.items)


def _rows_for(logger, entity_id):
    return [e for e in logger.get_log() if e["entity_id"] == entity_id]


def _holder(env, store, logger, hold=10):
    """Well-behaved entity - grabs the single unit at t=0 and holds it."""
    with store.request(entity_id="holder", start_event="t_start", end_event="t_end") as req:
        yield req
        yield env.timeout(hold)
    logger.log_departure(entity_id="holder")


def _unawaited_patient(env, store, logger, entity_id, arrive_at, stay):
    """Buggy entity - enters the `with` block but never `yield req`s."""
    yield env.timeout(arrive_at)
    logger.log_arrival(entity_id=entity_id)
    logger.log_queue(entity_id=entity_id, event="wait")
    with store.request(entity_id=entity_id, start_event="t_start", end_event="t_end"):
        yield env.timeout(stay)
    logger.log_departure(entity_id=entity_id)


def _awaited_patient(env, store, logger, entity_id, arrive_at, stay):
    """Correct counterpart of `_unawaited_patient`."""
    yield env.timeout(arrive_at)
    logger.log_arrival(entity_id=entity_id)
    logger.log_queue(entity_id=entity_id, event="wait")
    with store.request(
        entity_id=entity_id, start_event="t_start", end_event="t_end"
    ) as req:
        yield req
        yield env.timeout(stay)
    logger.log_departure(entity_id=entity_id)


# MARK: the guard fires


def test_unawaited_request_warns(store_class):
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=1, label="nurse", logger=logger)

    env.process(_holder(env, store, logger, hold=10))
    # arrives while the unit is busy, gives up implicitly at t=6
    env.process(_unawaited_patient(env, store, logger, "p2", arrive_at=1, stay=5))

    with pytest.warns(UserWarning, match="never awaited"):
        env.run(until=30)


def test_unawaited_request_logs_no_phantom_resource_use(store_class):
    """The buggy entity must get *no* resource_use row - not one dated after its depart."""
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=1, label="nurse", logger=logger)

    env.process(_holder(env, store, logger, hold=10))
    env.process(_unawaited_patient(env, store, logger, "p2", arrive_at=1, stay=5))

    with pytest.warns(UserWarning):
        env.run(until=30)

    p2_events = [(e["event_type"], e["event"], e["time"]) for e in _rows_for(logger, "p2")]
    assert p2_events == [
        ("arrival_departure", "arrival", 1.0),
        ("queue", "wait", 1.0),
        ("arrival_departure", "depart", 6.0),
    ]
    assert not any(e["event_type"] == "resource_use" for e in _rows_for(logger, "p2"))


def test_unawaited_request_does_not_leak_the_unit(store_class):
    """After the holder releases, the unit must come back - not be swallowed by the ghost."""
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=1, label="nurse", logger=logger)

    env.process(_holder(env, store, logger, hold=10))
    env.process(_unawaited_patient(env, store, logger, "p2", arrive_at=1, stay=5))

    with pytest.warns(UserWarning):
        env.run(until=30)

    assert _units_available(store) == 1
    assert list(_pending_queue(store)) == []
    # the holder used the unit normally
    holder_events = [
        (e["event_type"], e["event"], e["time"]) for e in _rows_for(logger, "holder")
    ]
    assert holder_events == [
        ("resource_use", "t_start", 0.0),
        ("resource_use_end", "t_end", 10.0),
        ("arrival_departure", "depart", 10.0),
    ]


def test_unawaited_request_with_free_unit_returns_it_immediately(store_class):
    """The guard's 'item already in hand' path: the `with` block exits in the same step,
    before the get event is processed, so the unit must be handed straight back."""
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=1, label="nurse", logger=logger)

    def buggy(env, store):
        with store.request(entity_id="p1", start_event="t_start", end_event="t_end"):
            pass  # never yields the request
        yield env.timeout(1)

    env.process(buggy(env, store))

    with pytest.warns(UserWarning, match="never awaited"):
        env.run(until=10)

    assert _units_available(store) == 1
    assert list(_pending_queue(store)) == []
    assert not any(
        e["event_type"].startswith("resource_use") for e in logger.get_log()
    )


def test_guard_also_fires_without_a_logger(store_class):
    """The leak matters even when auto-logging is off, so the guard must not depend on it."""
    env = simpy.Environment()

    def buggy(env, store):
        with store.request():
            yield env.timeout(5)

    def holder(env, store):
        with store.request() as req:
            yield req
            yield env.timeout(10)

    store = store_class(env, num_resources=1, label="nurse")  # no logger=
    env.process(holder(env, store))
    env.process(buggy(env, store))

    with pytest.warns(UserWarning, match="never awaited"):
        env.run(until=30)

    assert _units_available(store) == 1
    assert list(_pending_queue(store)) == []


# MARK: the guard stays quiet when it should


def test_correct_usage_does_not_warn(store_class):
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=1, label="nurse", logger=logger)

    env.process(_holder(env, store, logger, hold=10))
    env.process(_awaited_patient(env, store, logger, "p2", arrive_at=1, stay=5))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        env.run(until=30)

    assert not [w for w in caught if "never awaited" in str(w.message)]

    # p2 waited for the unit and used it properly: start at grant time (t=10), one end
    p2_res = [
        (e["event_type"], e["event"], e["time"])
        for e in _rows_for(logger, "p2")
        if e["event_type"].startswith("resource_use")
    ]
    assert p2_res == [
        ("resource_use", "t_start", 10.0),
        ("resource_use_end", "t_end", 15.0),
    ]


def test_exception_before_yield_does_not_trigger_the_guard_warning(store_class):
    """An exception raised inside the `with` before `yield req` is the real failure -
    it surfaces on its own; the guard must not add a spurious 'never awaited' warning,
    but must still release the queued request."""
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=1, label="nurse", logger=logger)

    class Boom(Exception):
        pass

    def holder(env, store):
        with store.request(entity_id="holder") as req:
            yield req
            yield env.timeout(10)

    def exploder(env, store):
        yield env.timeout(1)
        with store.request(entity_id="x"):
            raise Boom("before yield")
            yield  # pragma: no cover - unreachable, makes this a generator

    env.process(holder(env, store))
    env.process(exploder(env, store))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(Boom):
            env.run(until=30)

    assert not [w for w in caught if "never awaited" in str(w.message)]
    # the queued request was dropped, so the holder's release is not consumed by a ghost
    assert list(_pending_queue(store)) == []


def test_lone_immediate_grant_without_yield_is_the_known_uncaught_gap(store_class):
    """Documents the limitation: a lone entity with a *free* unit whose spurious timeout
    outlasts the immediate grant is not caught, because by its __exit__ the get event has
    already been processed. No phantom row, no leak - just a wrong (zero) wait. If a future
    change starts catching this too, update this test rather than leaving it asserting the
    gap.
    """
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=1, label="nurse", logger=logger)

    def buggy(env, store):
        logger.log_arrival(entity_id="solo")
        with store.request(entity_id="solo", start_event="t_start", end_event="t_end"):
            yield env.timeout(5)
        logger.log_departure(entity_id="solo")

    env.process(buggy(env, store))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        env.run(until=30)

    assert not [w for w in caught if "never awaited" in str(w.message)]
    assert _units_available(store) == 1  # no leak
