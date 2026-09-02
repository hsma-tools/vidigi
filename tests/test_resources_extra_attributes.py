"""Tests for `extra_attributes=` on the bulk populate paths (issue #115).

`VidigiResource.__init__` has always accepted arbitrary keyword attributes, but
`populate_store()` / `VidigiStore(num_resources=...)` / `.populate()` (and the
`VidigiPriorityStore` equivalents) built resources internally with no way to pass
them through - the documented workaround was monkeypatching `VidigiResource.__init__`.
`extra_attributes={...}` threads a pool-uniform dict of attributes onto every
resource. Keys the pool manages itself (`id_attribute`/`id`/`label`/
`unique_id_attribute`/`unique_id`) are rejected with `ValueError`.

`VidigiStore.populate` and `VidigiPriorityStore.populate` run identical code for
this feature (both `_check_extra_attributes` then `_new_pool_resource(...,
extra_attributes=...)` in a loop), so `store_class` is only parametrized where the
two genuinely differ - the happy path and the top-up path (`store.put` vs
`_put_item`).
"""

import warnings

import pytest
import simpy

from vidigi.resources import VidigiPriorityStore, VidigiStore, populate_store


def _make_env():
    return simpy.Environment()


@pytest.fixture(params=[VidigiStore, VidigiPriorityStore])
def store_class(request):
    return request.param


def _resources(store):
    """Both store types expose their pool differently."""
    return store.store.items if isinstance(store, VidigiStore) else store.items


# --------------------------------------------------------------------------- #
# happy path: attributes reach every resource
# --------------------------------------------------------------------------- #


def test_constructor_sets_extra_attributes_on_whole_pool(store_class):
    store = store_class(
        _make_env(), num_resources=3, label="nurse",
        extra_attributes={"staff_type": "nurse", "band": 5},
    )
    resources = _resources(store)
    assert [(r.staff_type, r.band) for r in resources] == [("nurse", 5)] * 3
    # the pool-managed attributes still come from the index / label, unclobbered
    assert [r.id for r in resources] == [1, 2, 3]
    assert [r.unique_id for r in resources] == ["nurse_1", "nurse_2", "nurse_3"]


def test_populate_store_threads_extra_attributes():
    env = _make_env()
    store = simpy.Store(env)
    populate_store(2, store, env, label="rad", extra_attributes={"modality": "CT"})
    assert [r.modality for r in store.items] == ["CT", "CT"]
    assert [r.unique_id_attribute for r in store.items] == ["rad_1", "rad_2"]


def test_populate_topup_applies_to_new_resources_only(store_class):
    store = store_class(_make_env(), num_resources=2, label="nurse",
                        extra_attributes={"staff_type": "substantive"})
    with warnings.catch_warnings():
        # a no-label top-up warns that label will become mandatory - expected here,
        # covered by test_resources_label.py; not what this test is about.
        warnings.simplefilter("ignore", DeprecationWarning)
        store.populate(2, extra_attributes={"staff_type": "agency"})
    assert [r.staff_type for r in _resources(store)] == [
        "substantive", "substantive", "agency", "agency",
    ]


def test_extra_attributes_without_label():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        store = VidigiStore(_make_env(), num_resources=2,
                            extra_attributes={"staff_type": "nurse"})
    resources = store.store.items
    assert [r.staff_type for r in resources] == ["nurse", "nurse"]
    for r in resources:
        assert not hasattr(r, "unique_id_attribute")


# --------------------------------------------------------------------------- #
# default is a true no-op
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("extra_attributes", [None, {}])
def test_none_and_empty_dict_add_no_attributes(extra_attributes):
    """Pins a deliberately-unchanged behaviour: with no attributes to add, a pool
    is indistinguishable from one built before `extra_attributes` existed. Keys
    only - the two pools are built on different environments, so `env` and other
    simpy internals will not compare equal by value.
    """
    store = VidigiStore(_make_env(), num_resources=3, label="nurse",
                        extra_attributes=extra_attributes)
    plain = VidigiStore(_make_env(), num_resources=3, label="nurse")
    assert len(store.store.items) == len(plain.store.items) == 3  # not a vacuous zip
    for a, b in zip(store.store.items, plain.store.items):
        assert set(vars(a)) == set(vars(b))


# --------------------------------------------------------------------------- #
# pool-managed keys are rejected
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "build",
    [
        lambda env: VidigiStore(env, num_resources=1, label="x",
                                extra_attributes={"id_attribute": 9}),
        lambda env: VidigiPriorityStore(env, num_resources=1, label="x",
                                        extra_attributes={"id_attribute": 9}),
        lambda env: populate_store(1, simpy.Store(env), env, label="x",
                                   extra_attributes={"id_attribute": 9}),
    ],
)
def test_all_entrypoints_reject_a_reserved_key(build):
    with pytest.raises(ValueError, match="pool manages these"):
        build(_make_env())


@pytest.mark.parametrize(
    "reserved",
    [
        {"id_attribute": 9},
        {"id": 9},
        {"label": "y"},
        {"unique_id_attribute": "x_9"},
        {"unique_id": "x_9"},
    ],
)
def test_reserved_key_variants_rejected(reserved):
    """Every name in `_RESERVED_POOL_ATTRS`, not a sample - each is a distinct
    clobber vector (duplicate kwarg for `id_attribute`; property setter for the
    `id`/`unique_id` aliases; dict overwrite for `label`/`unique_id_attribute`),
    and the guard has to reject the whole set.
    """
    with pytest.raises(ValueError, match="pool manages these"):
        VidigiStore(_make_env(), num_resources=1, label="x", extra_attributes=reserved)


def test_reserved_key_rejected_before_any_resource_created():
    store = VidigiStore(_make_env(), label="x")
    with pytest.raises(ValueError):
        store.populate(3, extra_attributes={"label": "y"})
    assert store.items == []
