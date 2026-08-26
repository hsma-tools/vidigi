"""Tests for the opt-in `label=` on `VidigiStore`, `populate_store` and
`VidigiPriorityStore`.

`label=None` (the default) must be a true no-op on the resources produced -
`id_attribute` unchanged, and no new attributes added at all - but now also
emits a `DeprecationWarning`, since `label` is planned to become mandatory at
vidigi 3.0 (see `pending_fixes.md`). When given, `label` produces a new,
separate `unique_id_attribute` that stays unique across pools even though
`id_attribute` itself still restarts at 1 in every pool.
"""

import warnings

import simpy
import pytest

from vidigi.resources import VidigiPriorityStore, VidigiStore, populate_store


def _make_env():
    return simpy.Environment()


# --------------------------------------------------------------------------- #
# label=None: true no-op, plus a DeprecationWarning
# --------------------------------------------------------------------------- #


def test_vidigi_store_label_none_is_a_true_noop():
    env = _make_env()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        store = VidigiStore(env, num_resources=3)

    resources = store.store.items
    assert [r.id_attribute for r in resources] == [1, 2, 3]
    for r in resources:
        assert not hasattr(r, "label")
        assert not hasattr(r, "unique_id_attribute")


def test_vidigi_priority_store_label_none_is_a_true_noop():
    env = _make_env()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        store = VidigiPriorityStore(env, num_resources=3)

    resources = store.items
    assert [r.id_attribute for r in resources] == [1, 2, 3]
    for r in resources:
        assert not hasattr(r, "label")
        assert not hasattr(r, "unique_id_attribute")


def test_populate_store_label_none_is_a_true_noop():
    env = _make_env()
    plain_store = simpy.Store(env)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        populate_store(3, plain_store, env)

    assert [r.id_attribute for r in plain_store.items] == [1, 2, 3]
    for r in plain_store.items:
        assert not hasattr(r, "label")
        assert not hasattr(r, "unique_id_attribute")


@pytest.mark.parametrize(
    "build",
    [
        lambda env: VidigiStore(env, num_resources=1),
        lambda env: VidigiPriorityStore(env, num_resources=1),
        lambda env: populate_store(1, simpy.Store(env), env),
    ],
)
def test_label_none_warns_deprecation(build):
    with pytest.warns(DeprecationWarning, match="label"):
        build(_make_env())


@pytest.mark.parametrize(
    "build",
    [
        lambda env: VidigiStore(env, num_resources=1, label="triage"),
        lambda env: VidigiPriorityStore(env, num_resources=1, label="triage"),
        lambda env: populate_store(1, simpy.Store(env), env, label="triage"),
    ],
)
def test_label_given_suppresses_the_deprecation_warning(build):
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        build(_make_env())  # must not raise


@pytest.mark.parametrize(
    "build",
    [
        lambda env: VidigiStore(env, num_resources=1),
        lambda env: VidigiPriorityStore(env, num_resources=1),
    ],
)
def test_deprecation_warning_attributes_to_the_constructor_call_site(build):
    """`__init__` calls `.populate()` internally, adding a stack frame beyond
    the direct-`.populate()`/`populate_store()` case - the warning must still
    point at the caller's `VidigiStore(...)`/`VidigiPriorityStore(...)` line
    (this file), not at the internal `.populate()` call inside `resources.py`.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        build(_make_env())

    matching = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(matching) == 1
    assert matching[0].filename == __file__


def test_two_unlabelled_pools_each_warn_under_default_filter_semantics():
    """Python's default warning filter suppresses repeats sharing the same
    (message, category, module, lineno). If the two `VidigiStore(...)` calls
    below misattributed to the same internal `resources.py` line, the second
    pool's warning would be silently swallowed here - reproduced with an
    explicit "default" filter (not "always", which pytest normally installs
    and which would mask this by showing every warning regardless of
    location).
    """
    env = _make_env()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("default")
        VidigiStore(env, num_resources=1)
        VidigiStore(env, num_resources=1)

    matching = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(matching) == 2


# --------------------------------------------------------------------------- #
# label given: unique_id_attribute
# --------------------------------------------------------------------------- #


def test_single_pool_unique_id_attribute_values():
    env = _make_env()
    store = VidigiStore(env, num_resources=3, label="triage")
    resources = store.store.items

    assert [r.id_attribute for r in resources] == [1, 2, 3]
    assert [r.label for r in resources] == ["triage", "triage", "triage"]
    assert [r.unique_id_attribute for r in resources] == [
        "triage_1",
        "triage_2",
        "triage_3",
    ]


def test_two_vidigi_stores_distinct_labels_are_disjoint():
    env = _make_env()
    triage = VidigiStore(env, num_resources=3, label="triage")
    registration = VidigiStore(env, num_resources=3, label="registration")

    triage_ids = [r.id_attribute for r in triage.store.items]
    registration_ids = [r.id_attribute for r in registration.store.items]
    # id_attribute itself still collides across pools - unchanged from every
    # prior release, since vidigi.prep's animation positioning depends on it
    # staying a small per-pool index. This is expected, not a regression.
    assert triage_ids == registration_ids == [1, 2, 3]

    triage_unique = {r.unique_id_attribute for r in triage.store.items}
    registration_unique = {r.unique_id_attribute for r in registration.store.items}
    assert triage_unique.isdisjoint(registration_unique)
    assert triage_unique == {"triage_1", "triage_2", "triage_3"}
    assert registration_unique == {"registration_1", "registration_2", "registration_3"}


def test_two_vidigi_priority_stores_distinct_labels_are_disjoint():
    env = _make_env()
    a = VidigiPriorityStore(env, num_resources=2, label="a")
    b = VidigiPriorityStore(env, num_resources=2, label="b")

    assert [r.id_attribute for r in a.items] == [r.id_attribute for r in b.items] == [1, 2]
    a_unique = {r.unique_id_attribute for r in a.items}
    b_unique = {r.unique_id_attribute for r in b.items}
    assert a_unique.isdisjoint(b_unique)


def test_two_populate_store_pools_distinct_labels_are_disjoint():
    env = _make_env()
    a_store, b_store = simpy.Store(env), simpy.Store(env)
    populate_store(2, a_store, env, label="a")
    populate_store(2, b_store, env, label="b")

    assert [r.id_attribute for r in a_store.items] == [r.id_attribute for r in b_store.items] == [1, 2]
    a_unique = {r.unique_id_attribute for r in a_store.items}
    b_unique = {r.unique_id_attribute for r in b_store.items}
    assert a_unique.isdisjoint(b_unique)


def test_mixed_usage_only_the_labelled_pool_gets_the_new_attributes():
    env = _make_env()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        unlabelled = VidigiStore(env, num_resources=2)
    labelled = VidigiStore(env, num_resources=2, label="x")

    for r in unlabelled.store.items:
        assert not hasattr(r, "label")
        assert not hasattr(r, "unique_id_attribute")
    for r in labelled.store.items:
        assert r.label == "x"
        assert r.unique_id_attribute in ("x_1", "x_2")


# --------------------------------------------------------------------------- #
# Reusing the same label for two different pools
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "build_second",
    [
        lambda env: VidigiStore(env, num_resources=1, label="triage"),
        lambda env: VidigiPriorityStore(env, num_resources=1, label="triage"),
        lambda env: populate_store(1, simpy.Store(env), env, label="triage"),
    ],
)
def test_reusing_a_label_on_the_same_env_warns(build_second):
    """Two pools given the same label on the same env reproduce the exact
    resource_id collision label= exists to prevent - and unlike a bare
    resource_id collision, nothing else catches it unless the two pools
    happen to be busy at the same instant, so this must warn on its own."""
    env = _make_env()
    VidigiStore(env, num_resources=1, label="triage")

    with pytest.warns(UserWarning, match="already used"):
        build_second(env)


def test_reusing_a_label_across_different_envs_does_not_warn():
    """Reusing a label across separate replications - a fresh
    simpy.Environment per run, the normal case - is correct and must not
    warn, or every replication after the first would falsely flag itself."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        VidigiStore(_make_env(), num_resources=1, label="triage")
        VidigiStore(_make_env(), num_resources=1, label="triage")  # must not raise


def test_distinct_labels_on_the_same_env_do_not_warn():
    env = _make_env()
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        VidigiStore(env, num_resources=1, label="triage")
        VidigiStore(env, num_resources=1, label="registration")  # must not raise


# --------------------------------------------------------------------------- #
# Integration: label= actually fixes the by="resource" collision
# --------------------------------------------------------------------------- #


def test_label_fixes_the_by_resource_collision_end_to_end():
    """Two pools both numbering from 1, logged as resource_id=id_attribute
    (animation-safe, collision-prone) and unique_resource_id=unique_id_attribute
    (collision-proof) side by side. resource_utilisation(by="resource") on the
    default column exhibits the collision this whole change is about; the same
    call pointed at unique_resource_id does not."""
    from vidigi.analysis import resource_utilisation
    from vidigi.logging import EventLogger, TrialLogger

    env = _make_env()
    triage = VidigiStore(env, num_resources=1, label="triage")
    registration = VidigiStore(env, num_resources=1, label="registration")
    triage_unit = triage.store.items[0]
    registration_unit = registration.store.items[0]

    logger = EventLogger(run_number=1)
    logger.log_resource_use_start(
        entity_id=1,
        resource_id=triage_unit.id_attribute,
        unique_resource_id=triage_unit.unique_id_attribute,
        time=0.0,
        event="triage_begins",
    )
    logger.log_resource_use_end(
        entity_id=1,
        resource_id=triage_unit.id_attribute,
        unique_resource_id=triage_unit.unique_id_attribute,
        time=10.0,
        event="triage_ends",
    )
    logger.log_resource_use_start(
        entity_id=2,
        resource_id=registration_unit.id_attribute,
        unique_resource_id=registration_unit.unique_id_attribute,
        time=5.0,
        event="registration_begins",
    )
    logger.log_resource_use_end(
        entity_id=2,
        resource_id=registration_unit.id_attribute,
        unique_resource_id=registration_unit.unique_id_attribute,
        time=15.0,
        event="registration_ends",
    )
    log = TrialLogger([logger]).to_dataframe()

    with pytest.warns(UserWarning, match="overlapping busy bouts"):
        collided = resource_utilisation(log, by="resource", limit_duration=20)
    assert len(collided) == 1  # both units pooled under resource_id=1

    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        fixed = resource_utilisation(
            log, by="resource", limit_duration=20, resource_col_name="unique_resource_id"
        )
    assert len(fixed) == 2  # each physical unit now its own row
    assert set(fixed["resource_id"]) == {"triage_1", "registration_1"}
