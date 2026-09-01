"""Tests that VidigiStore / VidigiPriorityStore reject junk returned to the pool.

`put()` (both stores) and `VidigiPriorityStore.return_item()` raise `TypeError`
if handed a SimPy event object or `None` instead of a resource. The mistake this
guards against is a reneging / conditional-request branch that passes the
get/request event back into the pool instead of the item it yielded - see
`test_resources.py` for the reneging behaviour itself. Without the guard the
unfulfilled request sits in the pool and is handed to a later entity, so the
failure surfaces far from the mistake.

The guard must fire *before* any side effect (item stored, waiting get satisfied,
auto-log row written), so several tests here check state is untouched after a
rejected call, not just that it raised.
"""

import pytest
import simpy

from vidigi.logging import EventLogger
from vidigi.resources import VidigiPriorityStore, VidigiResource, VidigiStore

EVENT_MSG = r"SimPy event.*not the event object"
NONE_MSG = r"None, not a resource.*only return an item the store actually handed you"


@pytest.fixture(params=[VidigiStore, VidigiPriorityStore])
def store_class(request):
    """Both stores share the same return-validation contract."""
    return request.param


def return_methods(store):
    """Every bound method that returns an item to the pool."""
    names = ["put"]
    if isinstance(store, VidigiPriorityStore):
        names.append("return_item")
    return [getattr(store, name) for name in names]


def queue_snapshot(store):
    """(items, get_queue, put_queue) as shallow copies, wherever the class keeps them."""
    if isinstance(store, VidigiStore):
        return (list(store.items), list(store.store.get_queue), list(store.store.put_queue))
    return (list(store.items), list(store.get_queue), list(store.put_queue))


def sample_events(env):
    """One instance of every simpy.Event subclass a model realistically yields.

    `Condition` / `AllOf` matter most: `yield request | env.timeout(patience)` then
    passing the result (or the raw condition) back is the archetypal reneging slip.
    """

    def _noop():
        yield env.timeout(1)

    return {
        "Event": env.event(),
        "Timeout": env.timeout(1),
        "Condition": env.timeout(1) | env.timeout(2),
        "AllOf": env.all_of([env.timeout(1)]),
        "Process": env.process(_noop()),
    }


# MARK: rejection


@pytest.mark.parametrize("event_kind", list(sample_events(simpy.Environment())))
def test_returning_a_simpy_event_raises(store_class, event_kind):
    env = simpy.Environment()
    store = store_class(env, num_resources=1, label="bed")
    event = sample_events(env)[event_kind]

    for return_item in return_methods(store):
        with pytest.raises(TypeError, match=EVENT_MSG):
            return_item(event)


def test_returning_an_unfulfilled_get_request_raises(store_class):
    """The classic mistake: `store.put(request)` on the reneging branch."""
    env = simpy.Environment()
    store = store_class(env, num_resources=1, label="bed")

    store.get_direct()  # take the only resource
    env.run(until=1)
    pending = store.get_direct()  # has to queue
    env.run(until=2)
    assert not pending.triggered  # genuinely unfulfilled - the case the name promises

    for return_item in return_methods(store):
        with pytest.raises(TypeError, match=EVENT_MSG):
            return_item(pending)


def test_returning_none_raises(store_class):
    env = simpy.Environment()
    store = store_class(env, num_resources=1, label="bed")

    for return_item in return_methods(store):
        with pytest.raises(TypeError, match=NONE_MSG):
            return_item(None)


# MARK: the guard fires before any side effect


def test_rejected_return_does_not_touch_the_pool(store_class):
    """A rejected put/return_item must not enqueue, store, or satisfy anything."""
    env = simpy.Environment()
    store = store_class(env, num_resources=2, label="bed")

    store.get_direct()  # one resource out, one left in the pool
    env.run(until=1)
    waiting = store.get_direct()  # fulfilled immediately from the remaining resource
    env.run(until=2)

    before = queue_snapshot(store)
    junk = env.event()

    for return_item in return_methods(store):
        with pytest.raises(TypeError):
            return_item(junk)
        with pytest.raises(TypeError):
            return_item(None)

    assert queue_snapshot(store) == before
    assert junk not in store.items
    assert waiting.value is not junk


def test_rejected_return_writes_no_log_row(store_class):
    """Guard precedes auto-logging: a rejected call with entity_id= logs nothing.

    Mutation check for the call-ordering: moving `_reject_invalid_returned_item`
    below `_should_auto_log` / the raw put lets a rejected item be logged (and
    stored) before the TypeError - this test fails under that mutation.
    """
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=1, label="bed", logger=logger)

    for return_item in return_methods(store):
        with pytest.raises(TypeError):
            return_item(env.event(), entity_id="p1", event="bed_end")
        with pytest.raises(TypeError):
            return_item(None, entity_id="p1", event="bed_end")

    assert logger.get_log() == []


# MARK: valid returns are unaffected


def test_a_real_resource_round_trips(store_class):
    """The granted item goes back with no error, and lands in the pool."""
    env = simpy.Environment()
    store = store_class(env, num_resources=1, label="bed")

    for return_item in return_methods(store):
        got = store.get_direct()
        env.run(until=env.now + 1)
        item = got.value
        assert isinstance(item, VidigiResource)

        return_item(item)  # must not raise
        env.run(until=env.now + 1)
        assert item in store.items


def test_logger_store_still_logs_a_real_resource_release(store_class):
    """A valid get_direct/put pair on a logger store still auto-logs, guard notwithstanding."""
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, num_resources=1, label="bed", logger=logger)

    def proc(env, store):
        item = yield store.get_direct(entity_id="p1")
        yield env.timeout(5)
        store.put(item, entity_id="p1")

    env.process(proc(env, store))
    env.run()

    assert [(e["event_type"], e["event"], e["time"]) for e in logger.get_log()] == [
        ("resource_use", "bed_start", 0.0),
        ("resource_use_end", "bed_end", 5.0),
    ]


def test_context_manager_return_is_unaffected(store_class):
    """`request()` returns the granted item via the un-guarded `__exit__` path.

    `__exit__` / `_put_item` / `_return_item_raw` / `populate()` deliberately skip
    the guard. That the guard is *absent* there can't be pinned by a test: those
    paths only ever handle a real `VidigiResource`, which passes the guard anyway.
    This test just confirms the normal return still works.
    """
    env = simpy.Environment()
    store = store_class(env, num_resources=1, label="bed")
    seen = []

    def user():
        with store.request() as req:
            yield req
            seen.append(req.value)
            yield env.timeout(1)

    env.process(user())
    env.run()

    assert len(seen) == 1 and isinstance(seen[0], VidigiResource)
    assert len(store.items) == 1


def test_generic_non_resource_contents_still_allowed(store_class):
    """No VidigiResource/simpy.Resource type constraint was added.

    Pins the "generic pool, no type constraint" promise (HISTORY 2.0.0, the
    `logger=` bullet). Only SimPy events and None are rejected.
    """
    env = simpy.Environment()
    store = store_class(env, capacity=5)

    for return_item in return_methods(store):
        return_item("not-a-resource")  # must not raise
        return_item(42)  # must not raise

    assert "not-a-resource" in store.items and 42 in store.items


# MARK: interaction with cancel_get (matches the cancel_get docstring)


def test_cancel_get_then_return_the_value_not_the_event(store_class):
    """cancel_get docstring: return the item the get event yielded, not the event."""
    env = simpy.Environment()
    store = store_class(env, num_resources=1, label="bed")

    got = store.get_direct()
    env.run(until=1)
    assert got.triggered

    store.cancel_get(got)  # no-op: already fulfilled

    with pytest.raises(TypeError, match=EVENT_MSG):
        store.put(got)  # the event - the mistake the docstring warns about

    store.put(got.value)  # the item - the correct call
    env.run(until=2)
    assert got.value in store.items
