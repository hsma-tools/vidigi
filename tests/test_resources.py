"""Tests for cancelling pending resource requests.

`cancel_get` is what makes reneging possible - an entity that gives up waiting
must take its request out of the queue, or it will be handed a resource long
after it has left, and the entity behind it will be starved.

The wider behaviour of these classes is covered by the equivalence tests in
test_against_core_simpy.py, which check they produce the same event logs as
plain simpy resources.
"""

import simpy
import pytest

from vidigi.resources import VidigiPriorityStore, VidigiStore


@pytest.fixture(params=[VidigiStore, VidigiPriorityStore])
def store_class(request):
    """Both store types expose the same cancel_get contract."""
    return request.param


def pending_queue(store):
    """The queue of unfulfilled get requests, wherever the class keeps it."""
    if isinstance(store, VidigiStore):
        return store.store.get_queue
    return store.get_queue


def test_cancel_get_removes_the_request_from_the_queue(store_class):
    """Regression test for VidigiStore, which looked for `get_queue` on itself.

    VidigiStore wraps a simpy.Store rather than subclassing it, so the queue
    lives on the wrapped store. The lookup raised AttributeError, which the
    method's `except ValueError` did not catch - so cancel_get could not work
    at all on that class.
    """
    env = simpy.Environment()
    store = store_class(env, num_resources=1)

    # Take the only resource, so the next request has to queue.
    store.get_direct()
    env.run(until=1)
    pending = store.get_direct()
    env.run(until=2)

    assert len(pending_queue(store)) == 1

    store.cancel_get(pending)

    assert len(pending_queue(store)) == 0


def test_cancel_get_on_an_already_fulfilled_request_is_a_no_op(store_class):
    """The request may be served in the gap between timing out and cancelling."""
    env = simpy.Environment()
    store = store_class(env, num_resources=1)

    fulfilled = store.get_direct()
    env.run(until=1)

    assert fulfilled.triggered

    # Must not raise.
    store.cancel_get(fulfilled)


def test_cancel_get_leaves_other_requests_queued(store_class):
    """Cancelling one waiter must not disturb the others."""
    env = simpy.Environment()
    store = store_class(env, num_resources=1)

    store.get_direct()
    env.run(until=1)
    first_waiter = store.get_direct()
    second_waiter = store.get_direct()
    env.run(until=2)

    store.cancel_get(first_waiter)

    assert len(pending_queue(store)) == 1
    assert second_waiter in pending_queue(store)


def test_cancelled_request_does_not_consume_a_returned_resource(store_class):
    """A cancelled waiter must not be handed a resource after it has gone.

    This is the behaviour reneging depends on: the resource should go to the
    entity still waiting, not to the one that left.
    """
    env = simpy.Environment()
    store = store_class(env, num_resources=1)

    held = store.get_direct()
    env.run(until=1)
    renegers_request = store.get_direct()
    still_waiting = store.get_direct()
    env.run(until=2)

    store.cancel_get(renegers_request)

    # The holder finishes and returns the resource.
    store.put(held.value)
    env.run(until=3)

    assert not renegers_request.triggered
    assert still_waiting.triggered


def test_reneging_end_to_end(store_class):
    """A patient who waits too long leaves, and does not block the queue."""
    env = simpy.Environment()
    store = store_class(env, num_resources=1)
    outcomes = []

    def patient(name, patience, service_time):
        request = store.get_direct()
        result = yield request | env.timeout(patience)

        if request in result:
            outcomes.append((name, "served", env.now))
            yield env.timeout(service_time)
            store.put(request.value)
        else:
            store.cancel_get(request)
            outcomes.append((name, "reneged", env.now))

    # First patient is served immediately at t=0 and holds the resource for 10.
    env.process(patient("A", patience=100, service_time=10))
    # Second runs out of patience at t=2, well before A finishes.
    env.process(patient("B", patience=2, service_time=1))
    # Third is patient enough to outlast A, and is served at t=10 - which only
    # happens if B's cancelled request did not swallow the returned resource.
    env.process(patient("C", patience=100, service_time=1))
    env.run()

    assert outcomes == [
        ("A", "served", 0),
        ("B", "reneged", 2),
        # C is served the moment A returns the resource. If B's cancelled
        # request were still queued it would take this handover instead, and C
        # would never be served at all.
        ("C", "served", 10),
    ]
