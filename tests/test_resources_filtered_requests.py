"""Tests for the optional `filter_fn` on VidigiStore / VidigiPriorityStore requests.

`filter_fn` (a predicate over pool items) lets a request be granted only a matching unit -
e.g. only a nurse whose `.grade == "senior"`. `VidigiStore` gets this by wrapping
`simpy.FilterStore`; `VidigiPriorityStore` has the matching added to its hand-rolled queue,
where a returned unit goes to the highest-priority *accepting* waiter.

The no-op case (`filter_fn=None`) is guarded here and, more strongly, by
`test_against_core_simpy.py`, which compares `VidigiStore` against a plain `simpy.Store`.

Several assertions here are mutation guards for `VidigiPriorityStore`'s queue walk: reverting
the walk to `get_queue.pop(0)` / `self.items.pop(0)` must make the named test fail.
"""

import pytest
import simpy

from vidigi.logging import EventLogger
from vidigi.resources import VidigiPriorityStore, VidigiResource, VidigiStore


@pytest.fixture(params=[VidigiStore, VidigiPriorityStore])
def store_class(request):
    """Both store types expose the same `filter_fn` contract."""
    return request.param


def _graded_store(store_class, env, grades, **kwargs):
    """A pool of ``len(grades)`` resources, resource ``i`` carrying ``.grade = grades[i]``.

    ``extra_attributes=`` can only set the *same* value on every unit, so a heterogeneous
    pool is built by populating normally and then tagging ``store.items`` in place.
    """
    store = store_class(env, num_resources=len(grades), label="nurse", **kwargs)
    for resource, grade in zip(store.items, grades):
        resource.grade = grade
    return store


def _get_queue(store):
    """The queue of unfulfilled get requests, wherever the class keeps it."""
    if isinstance(store, VidigiStore):
        return store.store.get_queue
    return store.get_queue


# MARK: no-op equivalence


def _run_contention(store_class, request_kwargs):
    """Five processes contending for two units at t=0; return the grant order."""
    env = simpy.Environment()
    store = store_class(env, num_resources=2, label="n")
    grants = []

    def proc(name, hold):
        with store.request(**request_kwargs) as req:
            resource = yield req
            grants.append((env.now, name, resource.id_attribute))
            yield env.timeout(hold)

    for i, hold in enumerate([5, 5, 3, 4, 2]):
        env.process(proc(f"p{i}", hold))
    env.run()
    return grants


def test_filter_fn_none_is_identical_to_omitting_it(store_class):
    """Passing `filter_fn=None` explicitly must not perturb anything."""
    assert _run_contention(store_class, {}) == _run_contention(store_class, {"filter_fn": None})


# MARK: item selection


def test_filter_fn_grants_a_matching_unit_not_the_front_of_the_pool(store_class):
    """A senior-only request skips the two juniors at the front of the pool.

    Mutation guard: with the item scan reverted to `self.items.pop(0)`
    (`VidigiPriorityStore`) this hands over the junior at id 1 and the assertion fails.
    """
    env = simpy.Environment()
    store = _graded_store(store_class, env, ["junior", "junior", "senior"])
    got = {}

    def patient():
        with store.request(filter_fn=lambda r: r.grade == "senior") as req:
            resource = yield req
            got["needs_senior"] = (resource.id_attribute, resource.grade)
            yield env.timeout(5)

    env.process(patient())
    env.run()

    assert got == {"needs_senior": (3, "senior")}


def test_filtered_get_queues_until_a_matching_unit_returns(store_class):
    """A non-matching unit returning does not satisfy a filtered waiter; the match does.

    Mutation guard: with `_return_item_raw` reverted to `get_queue.pop(0)`, the junior
    released at t=3 is handed to `wants_senior` and the timeline diverges.
    """
    env = simpy.Environment()
    store = _graded_store(store_class, env, ["junior", "senior"])
    timeline = []

    def hog_senior():
        with store.request(filter_fn=lambda r: r.grade == "senior") as req:
            resource = yield req
            timeline.append(("hog", "got", resource.id_attribute, env.now))
            yield env.timeout(10)
        timeline.append(("hog", "released", env.now))

    def wants_senior():
        yield env.timeout(1)  # arrives after hog has taken the senior
        with store.request(filter_fn=lambda r: r.grade == "senior") as req:
            resource = yield req
            timeline.append(("wants_senior", "got", resource.id_attribute, env.now))
            yield env.timeout(1)

    def takes_junior():
        yield env.timeout(2)
        with store.request() as req:
            resource = yield req
            timeline.append(("takes_junior", "got", resource.id_attribute, env.now))
            yield env.timeout(1)  # junior back at t=3 - must NOT satisfy wants_senior
        timeline.append(("takes_junior", "released", env.now))

    env.process(hog_senior())
    env.process(wants_senior())
    env.process(takes_junior())
    env.run()

    assert timeline == [
        ("hog", "got", 2, 0),
        ("takes_junior", "got", 1, 2),
        ("takes_junior", "released", 3),
        ("hog", "released", 10),
        ("wants_senior", "got", 2, 10),
    ]


def test_returned_item_with_no_matching_waiter_lands_back_in_the_pool(store_class):
    """A unit nobody queued wants is kept for a later request, not dropped."""
    env = simpy.Environment()
    store = _graded_store(store_class, env, ["junior", "senior"])
    seen = []

    def take_and_release_junior():
        with store.request(filter_fn=lambda r: r.grade == "junior") as req:
            resource = yield req
            seen.append(("held", resource.id_attribute))
            yield env.timeout(1)
        # junior is back in the pool; a later junior request must find it again
        with store.request(filter_fn=lambda r: r.grade == "junior") as req:
            resource = yield req
            seen.append(("held_again", resource.id_attribute))

    env.process(take_and_release_junior())
    env.run()

    assert seen == [("held", 1), ("held_again", 1)]


# MARK: priority + filter (VidigiPriorityStore)


def test_lower_priority_matching_waiter_beats_higher_priority_non_matching_waiter():
    """The point of combining `priority` and `filter_fn`.

    Mutation guard: with `_return_item_raw` reverted to `get_queue.pop(0)`, the
    higher-priority `high_prio` (front of the queue) is handed the non-isolation bed and
    the assertion fails.
    """
    env = simpy.Environment()
    store = VidigiPriorityStore(env, num_resources=1, label="bed")
    store.items[0].isolation = False  # the one bed is a normal bed
    log = []

    def holder():
        with store.request(priority=0) as req:
            yield req
            log.append(("holder", "got", env.now))
            yield env.timeout(5)
        log.append(("holder", "released", env.now))

    def high_prio_isolation():
        yield env.timeout(1)
        with store.request(priority=0, filter_fn=lambda r: r.isolation) as req:
            yield req
            log.append(("high_prio", "got", env.now))
            yield env.timeout(1)

    def low_prio_anything():
        yield env.timeout(2)
        with store.request(priority=5) as req:
            yield req
            log.append(("low_prio", "got", env.now))
            yield env.timeout(1)

    env.process(holder())
    env.process(high_prio_isolation())
    env.process(low_prio_anything())
    env.run(until=50)

    assert log == [
        ("holder", "got", 0),
        ("holder", "released", 5),
        ("low_prio", "got", 5),
    ]


def test_priority_ordering_still_holds_among_waiters_that_all_match():
    """`filter_fn` does not disturb priority order when every waiter accepts the unit."""
    env = simpy.Environment()
    store = VidigiPriorityStore(env, num_resources=1, label="bed")
    order = []

    def holder():
        with store.request(priority=0) as req:
            yield req
            yield env.timeout(5)

    def waiter(name, priority):
        yield env.timeout(1)
        with store.request(priority=priority, filter_fn=lambda r: True) as req:
            yield req
            order.append(name)
            yield env.timeout(1)

    env.process(holder())
    env.process(waiter("low", priority=9))
    env.process(waiter("high", priority=1))
    env.process(waiter("mid", priority=5))
    env.run()

    assert order == ["high", "mid", "low"]


# MARK: finite capacity (VidigiPriorityStore) - guards the _put_item restructure


def test_filtered_waiter_served_before_a_full_store_queues_the_matching_item():
    """Serving a waiter consumes no capacity slot, so it must precede the capacity check.

    Mutation guard: with `_put_item` reverted to "capacity check first", `special` is
    parked in `put_queue` behind the full store and `wants_special` is never served.
    """
    env = simpy.Environment()
    store = VidigiPriorityStore(env, capacity=1, label="widget")
    plain = VidigiResource(id_attribute=1, kind="plain")
    special = VidigiResource(id_attribute=2, kind="special")
    store.put(plain)  # items == [plain], now at capacity
    got = []

    def wants_special():
        with store.request(filter_fn=lambda w: w.kind == "special") as req:
            widget = yield req
            got.append((widget.kind, env.now))
            yield env.timeout(1)

    def putter():
        yield env.timeout(1)
        store.put(special)  # store is full, but a matching waiter is queued

    env.process(wants_special())
    env.process(putter())
    env.run(until=10)

    assert got == [("special", 1)]
    assert store.put_queue == []  # special was handed straight over, not parked
    # both units are back in the pool once the run ends - nothing lost
    assert sorted(w.kind for w in store.items) == ["plain", "special"]


# MARK: reneging / guards


def test_filtered_get_can_be_cancelled_and_does_not_swallow_a_later_match(store_class):
    """A filtered `get_direct` given up on must not consume the matching unit later."""
    env = simpy.Environment()
    store = _graded_store(store_class, env, ["junior", "senior"])
    outcome = []

    def hog_senior():
        with store.request(filter_fn=lambda r: r.grade == "senior") as req:
            yield req
            yield env.timeout(10)

    def reneger():
        yield env.timeout(1)
        pending = store.get_direct(filter_fn=lambda r: r.grade == "senior")
        result = yield pending | env.timeout(3)
        if pending in result:
            outcome.append(("reneger", "served"))
            store.put(pending.value)
        else:
            store.cancel_get(pending)
            outcome.append(("reneger", "reneged", env.now))

    def patient_seeker():
        yield env.timeout(2)
        with store.request(filter_fn=lambda r: r.grade == "senior") as req:
            resource = yield req
            outcome.append(("patient_seeker", "got", resource.id_attribute, env.now))
            yield env.timeout(1)

    env.process(hog_senior())
    env.process(reneger())
    env.process(patient_seeker())
    env.run()

    assert outcome == [
        ("reneger", "reneged", 4),
        ("patient_seeker", "got", 2, 10),
    ]
    assert list(_get_queue(store)) == []


def test_unawaited_filtered_request_returns_the_matched_unit(store_class):
    """The unawaited-`request` guard must put back the *matched* unit, not corrupt the pool."""
    env = simpy.Environment()
    store = _graded_store(store_class, env, ["junior", "junior", "senior"])

    def sloppy():
        with pytest.warns(UserWarning, match="never awaited"):
            with store.request(filter_fn=lambda r: r.grade == "senior"):
                pass  # never `yield req`
        yield env.timeout(1)
        # the senior must be back and grantable
        with store.request(filter_fn=lambda r: r.grade == "senior") as req:
            resource = yield req
            assert resource.id_attribute == 3

    env.process(sloppy())
    env.run()
    assert {r.id_attribute for r in store.items} == {1, 2, 3}


def test_unsatisfiable_filter_just_never_grants(store_class):
    """A `filter_fn` that matches nothing waits forever - the run still terminates."""
    env = simpy.Environment()
    store = _graded_store(store_class, env, ["junior", "junior"])
    served = []

    def dreamer():
        with store.request(filter_fn=lambda r: r.grade == "consultant") as req:
            yield req
            served.append("dreamer")

    env.process(dreamer())
    env.run(until=100)

    assert served == []


@pytest.mark.parametrize("bad", [5, "senior", object()])
def test_non_callable_filter_fn_raises_typeerror(store_class, bad):
    env = simpy.Environment()
    store = store_class(env, num_resources=1, label="n")

    with pytest.raises(TypeError, match="filter_fn must be callable"):
        store.get_direct(filter_fn=bad)
    with pytest.raises(TypeError, match="filter_fn must be callable"):
        store.request_direct(filter_fn=bad)
    with pytest.raises(TypeError, match="filter_fn must be callable"):
        store.request(filter_fn=bad)


# MARK: auto-logging


def test_auto_logged_resource_id_is_the_filtered_unit(store_class):
    """Auto-logging records the unit actually granted, at grant time."""
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = _graded_store(
        store_class, env, ["junior", "junior", "senior"], logger=logger
    )

    def patient():
        with store.request(
            entity_id="p1", filter_fn=lambda r: r.grade == "senior"
        ) as req:
            yield req
            yield env.timeout(5)

    env.process(patient())
    env.run()

    start, end = logger.get_log()
    assert (start["resource_id"], start["unique_resource_id"]) == (3, "nurse_3")
    assert (end["resource_id"], end["unique_resource_id"]) == (3, "nurse_3")
