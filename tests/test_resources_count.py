"""Tests for the resource-style ``count`` / ``num_resources`` / ``n_waiting`` properties
on ``VidigiStore`` and ``VidigiPriorityStore``.

These make a store used as a fixed resource pool introspectable the way
``simpy.Resource`` is. ``count`` is *computed* (pool size minus the units currently in
the store), not tracked per request, so it has to stay correct through queueing,
reneging, filtered requests and - for ``VidigiPriorityStore`` - direct
holder-to-waiter handoff.

Mutation guards (revert a mutation with the editing tool, never ``git checkout`` -
see CLAUDE.md):

  * ``count`` computed from ``len(<items>)`` (available, not in use), or with a
    ``+ 1`` / ``- 1`` fudge: ``test_count_sequence_through_a_queueing_run`` and
    ``test_count_matches_simpy_resource`` fail.
  * dropping the ``in_use < 0`` guard so ``count`` returns the negative:
    ``test_count_raises_when_pool_size_untracked`` fails.
  * ``n_waiting`` hard-wired to ``0`` or ``len(...) - 1``:
    ``test_n_waiting_sequence_through_a_queueing_run`` fails.
  * ``_reject_over_capacity_return`` body removed: the ``test_over_capacity_*`` and
    ``test_context_manager_double_return_*`` tests fail.
"""

import warnings

import pytest
import simpy

from vidigi.resources import (
    VidigiPriorityStore,
    VidigiResource,
    VidigiStore,
    populate_store,
)


@pytest.fixture(params=[VidigiStore, VidigiPriorityStore])
def store_class(request):
    """Both store types expose the same count / num_resources / n_waiting contract."""
    return request.param


def _available(store):
    """Units currently sitting in the store, wherever the class keeps them."""
    return store.items  # both classes expose `items`


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_fresh_pool_reports_zero_in_use(store_class):
    env = simpy.Environment()
    store = store_class(env, num_resources=3, label="bed")

    assert store.num_resources == 3
    assert store.count == 0
    assert store.n_waiting == 0
    assert len(_available(store)) == 3


def test_num_resources_zero_is_valid_not_an_error(store_class):
    """An empty pool is a real (if odd) state, not the untracked-pool case."""
    env = simpy.Environment()

    empty = store_class(env, num_resources=0, label="none")
    assert empty.num_resources == 0
    assert empty.count == 0

    bare = store_class(env)
    assert bare.num_resources == 0
    assert bare.count == 0  # nothing populated, nothing put -> 0, no raise


def test_num_resources_accumulates_over_top_up_populate(store_class):
    env = simpy.Environment()
    store = store_class(env, num_resources=2, label="p")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        store.populate(3)  # no-arg top up of an already-running pool

    assert store.num_resources == 5
    assert store.count == 0
    assert len(_available(store)) == 5


def test_num_resources_and_count_track_populate_method_on_bare_store(store_class):
    env = simpy.Environment()
    store = store_class(env)

    store.populate(4, label="p")

    assert store.num_resources == 4
    assert store.count == 0
    store.get_direct()
    env.run(until=1)
    assert store.count == 1


# ---------------------------------------------------------------------------
# Single acquire / release
# ---------------------------------------------------------------------------


def test_single_acquire_and_release(store_class):
    env = simpy.Environment()
    store = store_class(env, num_resources=2, label="b")

    ev = store.get_direct()
    env.run(until=1)
    assert store.count == 1
    assert store.num_resources == 2  # unchanged by use

    store.put(ev.value)
    env.run(until=2)
    assert store.count == 0


def test_count_with_context_manager(store_class):
    env = simpy.Environment()
    store = store_class(env, num_resources=1, label="b")
    seen = []

    def user():
        with store.request() as req:
            yield req
            seen.append(("holding", store.count))
            yield env.timeout(5)
        seen.append(("released", store.count))

    env.process(user())
    env.run()

    assert seen == [("holding", 1), ("released", 0)]


# ---------------------------------------------------------------------------
# Whole-sequence behaviour through a queueing run
# ---------------------------------------------------------------------------


def _run_with_sampler(store, schedule, horizon):
    """Spawn one holder per (start, hold) in ``schedule``; sample once per time unit.

    Returns the list of ``(now, count, n_waiting)`` sampled at t = 0.5, 1.5, ... The
    half-tick offset samples the *settled* state within each unit interval rather than
    a value caught mid-way through simpy's multi-substep release/grant processing at an
    event instant - which is what a model querying ``store.count`` between its own
    events sees, and keeps the two store classes (and simpy) directly comparable.
    """
    env = store.env
    samples = []

    def holder(start, hold):
        yield env.timeout(start)
        with store.request() as req:
            yield req
            yield env.timeout(hold)

    for start, hold in schedule:
        env.process(holder(start, hold))

    def sampler():
        yield env.timeout(0.5)
        while True:
            samples.append((env.now, store.count, store.n_waiting))
            yield env.timeout(1)

    env.process(sampler())
    env.run(until=horizon)
    return samples


# 3 units; 5 holders, demand exceeds supply between t=0 and the first releases.
_SCHEDULE = [(0, 8), (0, 8), (0, 8), (2, 8), (2, 8)]
_HORIZON = 14


def test_count_sequence_through_a_queueing_run(store_class):
    env = simpy.Environment()
    store = store_class(env, num_resources=3, label="s")

    samples = _run_with_sampler(store, _SCHEDULE, _HORIZON)
    counts = [c for (_t, c, _w) in samples]

    # Verified against a scratch run of this exact schedule - identical for both
    # classes. Three units taken at t=0, held to t=8; two more join the queue at
    # t=2 and are served at t=8, holding to t=10.
    # sampled at t = 0.5 .. 13.5
    assert counts == [3, 3, 3, 3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2]
    assert max(counts) == store.num_resources  # never over-subscribed


def test_n_waiting_sequence_through_a_queueing_run(store_class):
    env = simpy.Environment()
    store = store_class(env, num_resources=3, label="s")

    samples = _run_with_sampler(store, _SCHEDULE, _HORIZON)
    waiting = [w for (_t, _c, w) in samples]

    # Two holders join the queue at t=2 and are served when the first three
    # release at t=8.  sampled at t = 0.5 .. 13.5
    assert waiting == [0, 0, 2, 2, 2, 2, 2, 2, 0, 0, 0, 0, 0, 0]


# ---------------------------------------------------------------------------
# Reneging leaves count alone, drains n_waiting
# ---------------------------------------------------------------------------


def test_count_unaffected_by_reneging(store_class):
    env = simpy.Environment()
    store = store_class(env, num_resources=1, label="b")

    held = store.get_direct()
    env.run(until=1)
    assert store.count == 1

    waiter = store.get_direct()
    env.run(until=2)
    assert store.count == 1
    assert store.n_waiting == 1

    store.cancel_get(waiter)
    env.run(until=3)
    assert store.count == 1
    assert store.n_waiting == 0

    store.put(held.value)
    env.run(until=4)
    assert store.count == 0  # went to nobody, back to the pool


# ---------------------------------------------------------------------------
# Filtered requests
# ---------------------------------------------------------------------------


def test_count_with_filter_fn(store_class):
    env = simpy.Environment()
    store = store_class(env, num_resources=3, label="nurse")
    for resource, grade in zip(store.items, ["junior", "junior", "senior"]):
        resource.grade = grade

    ev = store.get_direct(filter_fn=lambda r: r.grade == "senior")
    env.run(until=1)

    assert ev.value.grade == "senior"
    assert store.count == 1
    assert store.num_resources == 3


# ---------------------------------------------------------------------------
# VidigiPriorityStore direct handoff
# ---------------------------------------------------------------------------


def test_count_constant_across_priority_store_direct_handoff():
    """A returned unit passed straight to a waiter never enters ``items``; ``count``
    must not blip while it is mid-air."""
    env = simpy.Environment()
    store = VidigiPriorityStore(env, num_resources=1, label="b")

    held = store.get_direct()
    env.run(until=1)
    assert store.count == 1

    at_grant = []
    waiter = store.get_direct()
    waiter.callbacks.append(lambda ev: at_grant.append(store.count))
    env.run(until=2)
    assert store.count == 1  # queued, holder still has the unit

    store.put(held.value)  # direct handoff to `waiter`
    env.run(until=3)

    assert at_grant == [1]  # count already 1 at the instant the waiter is granted
    assert store.count == 1
    assert store.items == []
    assert store.n_waiting == 0


# ---------------------------------------------------------------------------
# Untracked pool size
# ---------------------------------------------------------------------------


def test_count_raises_when_pool_size_untracked(store_class):
    env = simpy.Environment()
    store = store_class(env)
    store.put(VidigiResource(id_attribute=1, env=env))
    store.put(VidigiResource(id_attribute=2, env=env))

    with pytest.raises(RuntimeError, match="populate"):
        store.count

    # num_resources itself does not raise - it just reports what was tracked.
    assert store.num_resources == 0


def test_count_raises_after_populate_store_free_function(store_class):
    """``populate_store()`` deliberately does not feed the pool-size counter."""
    env = simpy.Environment()
    store = store_class(env)
    with warnings.catch_warnings():
        warnings.simplefilter(
            "ignore", DeprecationWarning
        )  # populate_store is deprecated
        populate_store(3, store, env, label="x")

    with pytest.raises(RuntimeError, match="populate_store"):
        store.count


# ---------------------------------------------------------------------------
# capacity reflects the pool size (changed in 2.0.0 - was always float("inf"))
# ---------------------------------------------------------------------------


def test_capacity_reflects_pool_size(store_class):
    env = simpy.Environment()

    # Pooled store: capacity == num_resources (was float("inf") before 2.0.0).
    pooled = store_class(env, num_resources=4, label="a")
    assert pooled.capacity == 4 == pooled.num_resources

    # Bare store: still float("inf").
    assert store_class(env, label="b").capacity == float("inf")

    # Explicit capacity= wins over the pool size.
    assert store_class(env, num_resources=2, capacity=5, label="c").capacity == 5

    # Tracks a top-up populate().
    pooled.populate(3, label="a2")
    assert pooled.capacity == 7 == pooled.num_resources

    # capacity == count + units available, at every point in a run.
    store = store_class(env, num_resources=3, label="d")
    assert store.capacity == store.count + len(_available(store))
    store.get_direct()
    env.run(until=1)
    assert store.capacity == store.count + len(_available(store)) == 3


# ---------------------------------------------------------------------------
# strict_capacity: an over-capacity return is rejected
# ---------------------------------------------------------------------------


def _drain_and_return(store, n):
    """Take all ``n`` units and put them all back, so the pool is full again."""
    env = store.env
    got = [store.get_direct() for _ in range(n)]
    env.run()
    for ev in got:
        store.put(ev.value)
    env.run()
    return got


def test_over_capacity_put_raises(store_class):
    env = simpy.Environment()
    store = store_class(env, num_resources=2, label="bay")
    got = _drain_and_return(store, 2)
    assert store.count == 0 and len(_available(store)) == 2

    with pytest.raises(ValueError, match="strict_capacity"):
        store.put(got[0].value)  # a third unit into a 2-unit pool


def test_over_capacity_return_item_raises():
    env = simpy.Environment()
    store = VidigiPriorityStore(env, num_resources=2, label="bay")
    got = _drain_and_return(store, 2)

    with pytest.raises(ValueError, match="strict_capacity"):
        store.return_item(got[0].value)


def test_strict_capacity_false_allows_the_pool_to_grow(store_class):
    env = simpy.Environment()
    store = store_class(env, num_resources=2, label="bay", strict_capacity=False)
    got = _drain_and_return(store, 2)

    store.put(got[0].value)  # must not raise
    env.run()
    assert len(_available(store)) == 3
    # count now goes negative internally -> the existing RuntimeError guard fires.
    with pytest.raises(RuntimeError):
        store.count


def test_bare_store_is_still_an_unbounded_generic_pool(store_class):
    """No num_resources -> pool size unknown -> the guard cannot and does not fire."""
    env = simpy.Environment()
    store = store_class(env)
    store.put(VidigiResource(id_attribute=1, env=env))
    store.put(VidigiResource(id_attribute=2, env=env))
    store.put(VidigiResource(id_attribute=3, env=env))  # must not raise
    env.run()
    assert len(_available(store)) == 3


def test_explicit_capacity_keeps_simpy_parking_behaviour():
    """An explicit capacity= disables the strict guard (that path is the escape hatch);
    the pre-existing finite-capacity put-queue behaviour is unchanged."""
    env = simpy.Environment()
    store = VidigiPriorityStore(env, capacity=1, label="w")
    store.put(VidigiResource(id_attribute=1, env=env))
    # Second put has nowhere to go and no waiter - parked, not raised.
    store.put(VidigiResource(id_attribute=2, env=env))
    env.run()
    assert len(store.items) == 1 and len(store.put_queue) == 1


def test_topup_populate_not_blocked_by_the_guard(store_class):
    env = simpy.Environment()
    store = store_class(env, num_resources=2, label="p")
    store.populate(3, label="p2")
    env.run()
    assert len(_available(store)) == 5 and store.num_resources == 5


def test_context_manager_double_return_raises_on_clean_exit(store_class):
    """Returning a unit by hand *and* letting __exit__ return it again is a bug."""
    env = simpy.Environment()
    store = store_class(env, num_resources=1, label="bay")
    outcome = []

    def proc():
        try:
            with store.request() as req:
                r = yield req
                store.put(r)  # premature manual return; __exit__ will return it again
                yield env.timeout(1)
        except ValueError:
            outcome.append("raised")

    env.process(proc())
    env.run()
    assert outcome == ["raised"]


def test_context_manager_return_not_masked_when_an_exception_propagates(store_class):
    """If the `with` body raises, __exit__ must not shadow it with a capacity ValueError."""
    env = simpy.Environment()
    store = store_class(env, num_resources=1, label="bay")
    seen = []

    def proc():
        try:
            with store.request() as req:
                r = yield req
                store.put(r)  # would make __exit__'s return over-capacity
                raise KeyError("the real failure")
        except KeyError:
            seen.append("keyerror")
        except ValueError:
            seen.append("valueerror")

    env.process(proc())
    env.run()
    assert seen == ["keyerror"]


# ---------------------------------------------------------------------------
# Equivalence against simpy's own Resource.count
# ---------------------------------------------------------------------------


def _sample_resource_count(make_pool, request_cm, schedule, horizon):
    env = simpy.Environment()
    pool = make_pool(env)
    samples = []

    def holder(start, hold):
        yield env.timeout(start)
        with request_cm(pool) as req:
            yield req
            yield env.timeout(hold)

    for start, hold in schedule:
        env.process(holder(start, hold))

    def sampler():
        yield env.timeout(0.5)  # settled state per interval - see _run_with_sampler
        while True:
            samples.append(pool.count)
            yield env.timeout(1)

    env.process(sampler())
    env.run(until=horizon)
    return samples


def test_count_matches_simpy_resource():
    schedule = [(0, 6), (0, 6), (1, 6), (1, 6), (3, 4)]
    horizon = 16

    simpy_counts = _sample_resource_count(
        lambda env: simpy.Resource(env, capacity=3),
        lambda res: res.request(),
        schedule,
        horizon,
    )
    vidigi_counts = _sample_resource_count(
        lambda env: VidigiStore(env, num_resources=3, label="r"),
        lambda store: store.request(),
        schedule,
        horizon,
    )

    assert vidigi_counts == simpy_counts


def test_count_matches_simpy_priority_resource():
    schedule = [(0, 6), (0, 6), (1, 6), (1, 6), (3, 4)]
    horizon = 16

    simpy_counts = _sample_resource_count(
        lambda env: simpy.PriorityResource(env, capacity=3),
        lambda res: res.request(priority=0),
        schedule,
        horizon,
    )
    vidigi_counts = _sample_resource_count(
        lambda env: VidigiPriorityStore(env, num_resources=3, label="r"),
        lambda store: store.request(priority=0),
        schedule,
        horizon,
    )

    assert vidigi_counts == simpy_counts
