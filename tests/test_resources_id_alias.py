"""Tests for the `id` / `unique_id` read-write aliases on `VidigiResource`.

`id` aliases `id_attribute`, `unique_id` aliases `unique_id_attribute`: reading or setting
either name of a pair affects the same value, at construction or after. The `_attribute`
names keep working unchanged. `unique_id` is only present when the pool was built with
`label=`, exactly like `unique_id_attribute`. Passing both names of a pair with different
values raises `ValueError`.
"""

import warnings

import pytest
import simpy

from vidigi.logging import EventLogger
from vidigi.resources import VidigiPriorityStore, VidigiResource, VidigiStore


@pytest.fixture(params=[VidigiStore, VidigiPriorityStore])
def store_class(request):
    return request.param


def _resources(store):
    return store.store.items if isinstance(store, VidigiStore) else store.items


# --------------------------------------------------------------------------- #
# id <-> id_attribute
# --------------------------------------------------------------------------- #


def test_id_reads_id_attribute_after_construction():
    r = VidigiResource(id_attribute=7)
    assert r.id == 7


def test_id_kwarg_sets_id_attribute():
    r = VidigiResource(id=5)
    assert r.id_attribute == 5
    assert r.id == 5


def test_id_round_trips_both_directions():
    r = VidigiResource(id_attribute=1)
    r.id = 9
    assert r.id_attribute == 9
    r.id_attribute = 4
    assert r.id == 4


def test_id_and_id_attribute_agree_across_a_whole_pool(store_class):
    env = simpy.Environment()
    store = store_class(env, num_resources=4, label="triage")
    resources = _resources(store)
    assert [r.id for r in resources] == [r.id_attribute for r in resources] == [1, 2, 3, 4]


def test_conflicting_id_and_id_attribute_raises():
    with pytest.raises(ValueError, match="aliases of the same value"):
        VidigiResource(id_attribute=1, id=2)


def test_matching_id_and_id_attribute_is_fine():
    r = VidigiResource(id_attribute=3, id=3)
    assert r.id == r.id_attribute == 3


# --------------------------------------------------------------------------- #
# unique_id <-> unique_id_attribute
# --------------------------------------------------------------------------- #


def test_unique_id_reads_unique_id_attribute_after_construction():
    r = VidigiResource(id_attribute=1, unique_id_attribute="triage_1")
    assert r.unique_id == "triage_1"


def test_unique_id_kwarg_sets_unique_id_attribute():
    r = VidigiResource(id_attribute=1, unique_id="triage_1")
    assert r.unique_id_attribute == "triage_1"


def test_unique_id_round_trips_both_directions():
    r = VidigiResource(id_attribute=1, unique_id_attribute="a")
    r.unique_id = "b"
    assert r.unique_id_attribute == "b"
    r.unique_id_attribute = "c"
    assert r.unique_id == "c"


def test_unique_id_agrees_across_a_labelled_pool(store_class):
    env = simpy.Environment()
    store = store_class(env, num_resources=3, label="triage")
    resources = _resources(store)
    assert [r.unique_id for r in resources] == [r.unique_id_attribute for r in resources]
    assert [r.unique_id for r in resources] == ["triage_1", "triage_2", "triage_3"]


def test_unique_id_absent_on_unlabelled_pool(store_class):
    env = simpy.Environment()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        store = store_class(env, num_resources=2)
    for r in _resources(store):
        assert not hasattr(r, "unique_id_attribute")
        assert not hasattr(r, "unique_id")
        with pytest.raises(AttributeError):
            r.unique_id


def test_conflicting_unique_id_and_unique_id_attribute_raises():
    with pytest.raises(ValueError, match="aliases of the same value"):
        VidigiResource(id_attribute=1, unique_id="x_1", unique_id_attribute="x_2")


# --------------------------------------------------------------------------- #
# the alias reaches the auto-logging path (which reads the `_attribute` names)
# --------------------------------------------------------------------------- #


def test_resource_built_with_id_kwarg_logs_correct_resource_id(store_class):
    """A resource constructed via the alias still produces the right resource_id in an
    auto-logged event - proving the setter keeps `id_attribute` in sync for the code in
    `_resource_use_log_kwargs`, which reads `id_attribute` / `unique_id_attribute`."""
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=1)
    store = store_class(env, capacity=1, label="bay", logger=logger)
    store.store.put(VidigiResource(id=42, unique_id="bay_42")) if isinstance(
        store, VidigiStore
    ) else store.items.append(VidigiResource(id=42, unique_id="bay_42"))

    def proc(env, store):
        req = store.get_direct(entity_id="m1")
        item = yield req
        yield env.timeout(1)
        store.put(item, entity_id="m1")

    env.process(proc(env, store))
    env.run()

    log = logger.get_log()
    assert [e["resource_id"] for e in log] == [42, 42]
    assert [e["unique_resource_id"] for e in log] == ["bay_42", "bay_42"]
