"""Tests for automatic resource-use logging on VidigiStore/VidigiPriorityStore.

When a store is constructed with `logger=` (an `EventLogger`), `request()`/`get()`/
`get_direct()`/`put()`/`return_item()` can log `resource_use`/`resource_use_end` events
automatically, given `entity_id=` at the call site - see each method's docstring in
`vidigi.resources`. This module exercises that behaviour; the underlying acquisition/release
mechanics (cancel_get, reneging, equivalence with plain simpy) are covered by
`test_resources.py` and `test_against_core_simpy.py`.
"""

import warnings

import pytest
import simpy
from pandas.testing import assert_frame_equal

from vidigi.logging import EventLogger
from vidigi.resources import VidigiPriorityStore, VidigiStore


@pytest.fixture(params=[VidigiStore, VidigiPriorityStore])
def store_class(request):
    """Both store types expose the same auto-logging contract."""
    return request.param


def _events(logger):
    """(event_type, event, entity_id, time) tuples, in log order, for compact assertions."""
    return [
        (e["event_type"], e["event"], e["entity_id"], e["time"]) for e in logger.get_log()
    ]


# MARK: context-manager pattern (request()/get())


def test_context_manager_auto_logs_start_and_end_immediate_grant(store_class):
    """A single entity, resource free when requested - the immediate-availability path."""
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=1, label="bed", logger=logger)

    def proc(env, store):
        with store.request(entity_id="p1") as req:
            yield req
            yield env.timeout(5)

    env.process(proc(env, store))
    env.run()

    assert _events(logger) == [
        ("resource_use", "bed_start", "p1", 0.0),
        ("resource_use_end", "bed_end", "p1", 5.0),
    ]
    start, end = logger.get_log()
    assert start["resource_id"] == 1
    assert start["unique_resource_id"] == "bed_1"
    assert end["resource_id"] == 1
    assert end["unique_resource_id"] == "bed_1"


def test_context_manager_start_logs_at_grant_time_not_request_time(store_class):
    """A second entity has to queue - its start must log the grant time, not the request time.

    Regression coverage for the deferred-callback mechanism: logging synchronously inside
    request()/get() (at request time) instead of via the callback that fires when the item is
    actually granted would log the waiter's start at t=1 (when it asked) rather than t=3 (when
    it was actually handed the resource) - this test fails under that mutation (verified by
    hand during development) and passes against the real implementation.
    """
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=1, label="bed", logger=logger)

    def holder(env, store):
        with store.request(entity_id="holder") as req:
            yield req
            yield env.timeout(3)

    def waiter(env, store):
        yield env.timeout(1)  # requests at t=1, but the bed is busy until t=3
        with store.request(entity_id="waiter") as req:
            yield req
            yield env.timeout(2)

    env.process(holder(env, store))
    env.process(waiter(env, store))
    env.run()

    assert _events(logger) == [
        ("resource_use", "bed_start", "holder", 0.0),
        ("resource_use_end", "bed_end", "holder", 3.0),
        ("resource_use", "bed_start", "waiter", 3.0),
        ("resource_use_end", "bed_end", "waiter", 5.0),
    ]


def test_context_manager_exception_during_use_still_logs_end_exactly_once(store_class):
    """__exit__ always runs (exception or not), so the end-log must too."""
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=1, label="bed", logger=logger)

    class Boom(Exception):
        pass

    def proc(env, store):
        with pytest.raises(Boom):
            with store.request(entity_id="p1") as req:
                yield req
                yield env.timeout(1)
                raise Boom("kaboom")

    env.process(proc(env, store))
    env.run()

    assert _events(logger) == [
        ("resource_use", "bed_start", "p1", 0.0),
        ("resource_use_end", "bed_end", "p1", 1.0),
    ]


def test_cancelled_request_never_logs_a_start(store_class):
    """Reneging must not produce a phantom start log for the request that was given up on."""
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=1, label="bed", logger=logger)

    def holder(env, store):
        with store.request(entity_id="holder") as req:
            yield req
            yield env.timeout(10)

    def reneger(env, store):
        yield env.timeout(1)
        pending = store.get_direct(entity_id="reneger")
        result = yield pending | env.timeout(2)
        if pending not in result:
            store.cancel_get(pending)

    env.process(holder(env, store))
    env.process(reneger(env, store))
    env.run(until=5)

    assert [e["entity_id"] for e in logger.get_log()] == ["holder"]


def test_no_label_falls_back_to_start_end_event_names(store_class):
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    with pytest.warns(DeprecationWarning, match="without a `label`"):
        store = store_class(env, num_resources=1, logger=logger)

    def proc(env, store):
        with store.request(entity_id="p1") as req:
            yield req
            yield env.timeout(1)

    env.process(proc(env, store))
    env.run()

    assert [e["event"] for e in logger.get_log()] == ["start", "end"]
    assert "unique_resource_id" not in logger.get_log()[0]


def test_per_call_event_overrides(store_class):
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=1, label="bed", logger=logger)

    def proc(env, store):
        with store.request(
            entity_id="p1", start_event="treatment_begins", end_event="treatment_ends"
        ) as req:
            yield req
            yield env.timeout(1)

    env.process(proc(env, store))
    env.run()

    assert [e["event"] for e in logger.get_log()] == ["treatment_begins", "treatment_ends"]


def test_pathway_and_extra_fields_forwarded(store_class):
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=1, label="bed", logger=logger)

    def proc(env, store):
        with store.request(entity_id="p1", pathway="fast_track", priority_score=3) as req:
            yield req
            yield env.timeout(1)

    env.process(proc(env, store))
    env.run()

    start, end = logger.get_log()
    assert start["pathway"] == "fast_track"
    assert start["priority_score"] == 3
    assert end["pathway"] == "fast_track"
    assert end["priority_score"] == 3


# MARK: manual pattern (get_direct()/put()/return_item())


def test_manual_get_direct_and_put_auto_log(store_class):
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=1, label="bay", logger=logger)

    def proc(env, store):
        req = store.get_direct(entity_id="m1")
        item = yield req
        yield env.timeout(4)
        store.put(item, entity_id="m1")

    env.process(proc(env, store))
    env.run()

    assert _events(logger) == [
        ("resource_use", "bay_start", "m1", 0.0),
        ("resource_use_end", "bay_end", "m1", 4.0),
    ]


def test_return_item_direct_call_auto_logs_end():
    """VidigiPriorityStore.return_item() is public API, independent of put()."""
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = VidigiPriorityStore(env, num_resources=1, label="cub", logger=logger)

    def proc(env, store):
        req = store.get_direct(entity_id="p1")
        item = yield req
        yield env.timeout(2)
        store.return_item(item, entity_id="p1")

    env.process(proc(env, store))
    env.run()

    assert _events(logger) == [
        ("resource_use", "cub_start", "p1", 0.0),
        ("resource_use_end", "cub_end", "p1", 2.0),
    ]


# MARK: robustness - items without id_attribute


def test_item_without_id_attribute_degrades_instead_of_crashing(store_class):
    """A stray non-VidigiResource item must not crash a model with a logger configured."""
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, capacity=1, logger=logger)  # empty pool
    # Seed the store directly with a non-VidigiResource item, bypassing populate() -
    # the scenario is a stray item slipping in via some other get/put pattern, not a
    # pool built normally.
    if isinstance(store, VidigiStore):
        store.store.put("a_plain_string")
    else:
        store._put_item("a_plain_string")

    def proc(env, store):
        with store.request(entity_id="p1") as req:
            yield req
            yield env.timeout(1)

    env.process(proc(env, store))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # BaseEvent's own missing-resource_id warning
        env.run()

    assert [e["resource_id"] for e in logger.get_log()] == [None, None]


# MARK: opt-in / no-op behaviour


def test_no_logger_entity_id_is_ignored_without_error(store_class):
    env = simpy.Environment()
    store = store_class(env, num_resources=1, label="bed")  # no logger at all

    def proc(env, store):
        with store.request(entity_id="p1") as req:
            yield req
            yield env.timeout(1)
        req = store.get_direct(entity_id="p2")
        item = yield req
        store.put(item, entity_id="p2")

    env.process(proc(env, store))
    env.run()  # must not raise


def test_missing_entity_id_skips_logging_and_warns_once_per_store(store_class):
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=2, label="room", logger=logger)

    def proc(env, store):
        with store.request() as req:  # no entity_id
            yield req
            yield env.timeout(1)
        with store.request() as req:  # no entity_id again - must not warn a 2nd time
            yield req
            yield env.timeout(1)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        env.process(proc(env, store))
        env.run()

    user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
    assert len(user_warnings) == 1
    assert "entity_id was not passed" in str(user_warnings[0].message)
    assert logger.get_log() == []


# MARK: label / self.label staleness


def test_populate_top_up_without_label_leaves_default_event_names_unchanged(store_class):
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=1, label="bed", logger=logger)

    store.populate(1)  # top-up, no label passed
    assert store.label == "bed"

    def proc(env, store):
        with store.request(entity_id="p1") as req:
            yield req
            yield env.timeout(1)

    env.process(proc(env, store))
    env.run()

    assert [e["event"] for e in logger.get_log()] == ["bed_start", "bed_end"]


# MARK: equivalence with manual EventLogger calls
#
# The rest of this module checks auto-logging's *shape* in isolation. These tests instead
# run one non-trivial scenario two ways - once with hand-written
# EventLogger.log_resource_use_start/end calls (the pre-existing, still-supported pattern),
# once with logger=/entity_id= auto-logging and no manual calls at all - and assert the
# resulting logs are identical. This is the same "structurally different, logically
# equivalent models must produce the same event log" style used in
# test_against_core_simpy.py, applied to the logging layer rather than the store mechanics.


def _sorted_columns(df):
    """Column order can legitimately differ (dict/kwarg construction order); row order
    (i.e. chronological event order) must not - so only columns are normalised here."""
    return df[sorted(df.columns)]


def _run_context_manager_scenario(store_class, *, auto_logging):
    """One resource, three entities, deep enough to force queueing and (for
    VidigiPriorityStore) exercise priority ordering: holder grabs the resource immediately;
    waiter (higher priority) and late (lower priority) both queue behind it and must be
    served in priority order, not request order.
    """
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(
        env, num_resources=1, label="bed", logger=logger if auto_logging else None
    )

    def priority_kwargs(priority):
        return {"priority": priority} if store_class is VidigiPriorityStore else {}

    def entity(entity_id, priority, delay, hold):
        yield env.timeout(delay)
        kwargs = priority_kwargs(priority)
        if auto_logging:
            kwargs.update(entity_id=entity_id, pathway="scenario")
        with store.request(**kwargs) as req:
            item = yield req
            if not auto_logging:
                logger.log_resource_use_start(
                    entity_id=entity_id,
                    resource_id=item.id_attribute,
                    event="bed_start",
                    pathway="scenario",
                    unique_resource_id=item.unique_id_attribute,
                )
            yield env.timeout(hold)
            if not auto_logging:
                logger.log_resource_use_end(
                    entity_id=entity_id,
                    resource_id=item.id_attribute,
                    event="bed_end",
                    pathway="scenario",
                    unique_resource_id=item.unique_id_attribute,
                )

    env.process(entity("holder", priority=5, delay=0, hold=3))
    env.process(entity("waiter", priority=0, delay=1, hold=2))  # highest priority
    env.process(entity("late", priority=3, delay=2, hold=1))

    env.run()
    return logger.to_dataframe().reset_index(drop=True)


def _run_manual_pattern_scenario(store_class, *, auto_logging):
    """Same shape as above, but using get_direct()/put() instead of the context manager."""
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(
        env, num_resources=1, label="bay", logger=logger if auto_logging else None
    )

    def priority_kwargs(priority):
        return {"priority": priority} if store_class is VidigiPriorityStore else {}

    def entity(entity_id, priority, delay, hold):
        yield env.timeout(delay)
        get_kwargs = priority_kwargs(priority)
        if auto_logging:
            get_kwargs.update(entity_id=entity_id, pathway="scenario")
        item = yield store.get_direct(**get_kwargs)
        if not auto_logging:
            logger.log_resource_use_start(
                entity_id=entity_id,
                resource_id=item.id_attribute,
                event="bay_start",
                pathway="scenario",
                unique_resource_id=item.unique_id_attribute,
            )
        yield env.timeout(hold)
        if not auto_logging:
            logger.log_resource_use_end(
                entity_id=entity_id,
                resource_id=item.id_attribute,
                event="bay_end",
                pathway="scenario",
                unique_resource_id=item.unique_id_attribute,
            )
        put_kwargs = (
            {"entity_id": entity_id, "pathway": "scenario"} if auto_logging else {}
        )
        store.put(item, **put_kwargs)

    env.process(entity("holder", priority=5, delay=0, hold=3))
    env.process(entity("waiter", priority=0, delay=1, hold=2))
    env.process(entity("late", priority=3, delay=2, hold=1))

    env.run()
    return logger.to_dataframe().reset_index(drop=True)


def test_auto_logging_matches_manual_logging_context_manager_pattern(store_class):
    manual_df = _run_context_manager_scenario(store_class, auto_logging=False)
    auto_df = _run_context_manager_scenario(store_class, auto_logging=True)
    assert_frame_equal(_sorted_columns(manual_df), _sorted_columns(auto_df))


def test_auto_logging_matches_manual_logging_get_direct_put_pattern(store_class):
    manual_df = _run_manual_pattern_scenario(store_class, auto_logging=False)
    auto_df = _run_manual_pattern_scenario(store_class, auto_logging=True)
    assert_frame_equal(_sorted_columns(manual_df), _sorted_columns(auto_df))
