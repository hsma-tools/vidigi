"""
Resource and Store code has been adapted from SimPy. Licence code for SimPy is provided below.

The MIT License (MIT)

Copyright (c) 2013 Ontje Lünsdorf and Stefan Scherfke (also see AUTHORS.txt)

Permission is hereby granted, free of charge, to any person obtaining a copy of this software
and associated documentation files (the “Software”), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge, publish, distribute,
sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

"""

import warnings
import weakref
from typing import Optional

import simpy
from simpy.core import BoundClass

from vidigi.logging import EventLogger

# {env: {labels already used for a pool on that env}}. Keyed on the
# environment (not a bare module-level set) because reusing a label across
# separate replications - a fresh `simpy.Environment` per run, the normal
# case - is correct and must not warn; only two pools sharing a label on the
# *same* env is a real collision. A WeakKeyDictionary lets a finished run's
# entry be freed once its env is garbage collected, instead of growing for
# the life of the process across many replications.
_seen_pool_labels: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _check_label_not_reused(env, label, *, stacklevel):
    """Warn if `label` was already used for another pool on this `env`.

    Two pools sharing a label produce colliding `unique_id_attribute` values,
    silently reproducing the exact `resource_id` collision `label=` exists to
    prevent - and unlike the bare `resource_id` collision, nothing else
    catches it unless the two pools' resources happen to be busy at the same
    instant (see `vidigi.analysis._check_no_overlapping_resource_bouts`).
    """
    if label is None:
        return
    seen = _seen_pool_labels.setdefault(env, set())
    if label in seen:
        warnings.warn(
            f"label={label!r} was already used for another resource pool on "
            "this simpy.Environment. Resources from different pools sharing "
            "a label get colliding unique_id_attribute values, silently "
            "reproducing the resource_id collision label= exists to prevent "
            "- give each pool on the same environment a distinct label.",
            UserWarning,
            stacklevel=stacklevel,
        )
    seen.add(label)


# MARK: VidigiResource Class
class VidigiResource:
    """
    A simple resource class with an ID attribute for use in VidigiStore and VidigiPriorityStore.

    This represents a resource that can be stored and retrieved from a store,
    with an identifier for tracking purposes.

    Accepts additional attributes as kwargs.
    """

    def __init__(self, id_attribute=None, **kwargs):
        self.id_attribute = id_attribute

        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self):
        return f"VidigiResource(id={self.id_attribute})"


def _new_pool_resource(env, index, label=None, *, stacklevel=3):
    """Build one `VidigiResource` for a `populate()`-style loop.

    `id_attribute` is always `index + 1`, unchanged from every prior release -
    `vidigi.prep`'s animation icon positioning does arithmetic directly on it,
    so it must stay a small per-pool index. When `label` is given, the
    resource additionally gets `.label` (the raw label) and
    `.unique_id_attribute` (`f"{label}_{index + 1}"`, unique across pools when
    every pool is given a distinct label) - two separate attributes rather
    than one, so a consumer never needs to parse the combined string back
    apart. Omitting `label` adds neither attribute at all (a true no-op), but
    warns once that `label` will become mandatory at vidigi 3.0 - see
    `pending_fixes.md`.

    `stacklevel` must count frames from here up to the *caller's* call site -
    `populate_store()` and a direct `.populate()` call are both one frame
    away (the default, 3, is correct for both), but `VidigiStore`/
    `VidigiPriorityStore.__init__` call `.populate()` internally, adding a
    frame, so they must pass `stacklevel=4` through `.populate()`'s own
    `_stacklevel` parameter. Getting this wrong doesn't just mislabel the
    warning's reported line - it can make it vanish. Python's default warning
    filter suppresses repeats sharing the same (message, category, module,
    lineno), so two distinct unlabelled pools that both misattribute to the
    same internal line only warn once between them.
    """
    if label is None:
        warnings.warn(
            "VidigiStore/populate_store/VidigiPriorityStore was used without a "
            "`label`. Resources from different pools currently number "
            "themselves 1..capacity independently, so the same resource_id can "
            "mean different physical things in different pools - this silently "
            "breaks vidigi.analysis.resource_utilisation(by=\"resource\"). Pass "
            "label=\"...\" to give this pool's resources a collision-proof "
            "unique_id_attribute. `label` becomes mandatory in vidigi 3.0.",
            DeprecationWarning,
            stacklevel=stacklevel,
        )
        extra = {}
    else:
        extra = {"label": label, "unique_id_attribute": f"{label}_{index + 1}"}
    return VidigiResource(env=env, capacity=1, id_attribute=index + 1, **extra)


def populate_store(num_resources, simpy_store, sim_env, label=None):
    """
    Populate a SimPy Store (or VidigiPriorityStore) with VidigiResource objects.

    This function creates a specified number of VidigiResource objects and adds them to
    a SimPy Store, a VidigiStore, or VidigiPriorityStore.

    Each VidigiResource is initialized with a capacity of 1 and a unique ID attribute,
    which is crucial for animation functions where you wish to show an individual entity
    consistently using the same resource.

    If using VidigiPriorityStore, you will need to pass the relevant priority in to the
    .get() argument when pulling a resource out of the store.

    Parameters
    ----------
    num_resources : int
        The number of VidigiResource objects to create and add to the store.
    simpy_store : simpy.Store, vidigi.resources.VidigiStore or vidigi.resources.VidigiPriorityStore
        The SimPy Store object to populate with resources.
    sim_env : simpy.Environment
        The SimPy environment in which the resources and store exist.
    label : str, optional
        A name for this pool of resources, e.g. `"triage"`. When given, each
        resource also gets `.unique_id_attribute` (`f"{label}_{id_attribute}"`)
        - unique across pools when every pool is given a distinct label, unlike
        `id_attribute` alone, which restarts at 1 in every pool. Omitting it
        (the default) changes nothing about the resources produced, but warns
        that `label` will become mandatory at vidigi 3.0 - see
        `vidigi.analysis.resource_utilisation`'s `by="resource"` docs for why.

    Returns
    -------
    None

    Notes
    -----
    - Each VidigiResource is created with a capacity of 1.
    - The ID attribute of each VidigiResource is set to its index in the creation loop plus one,
      ensuring unique IDs starting from 1.
    - This function is typically used to initialize a pool of resources at the start of a simulation.

    Examples
    --------
    >>> import simpy
    >>> env = simpy.Environment()
    >>> resource_store = simpy.Store(env)
    >>> populate_store(5, resource_store, env, label="triage")
    >>> len(resource_store.items)  # The store now contains 5 VidigiResource objects
    5
    """
    _check_label_not_reused(sim_env, label, stacklevel=3)
    for i in range(num_resources):
        simpy_store.put(_new_pool_resource(sim_env, i, label))


# \\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\#
# Automatic resource-use logging helpers
# \\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\#
# Shared by VidigiStore and VidigiPriorityStore's request()/get()/get_direct()/put()/
# return_item() - see each class's `logger=` constructor parameter.


def _default_resource_event_names(label):
    """Default (start, end) event names for auto-logged resource-use events.

    Derived from the pool's `label` (`f"{label}_start"`/`f"{label}_end"`) so a labelled
    pool's auto-logged events are identifiable without an extra argument at every call site,
    falling back to the same `"start"`/`"end"` literals `EventLogger.log_resource_use_start`/
    `log_resource_use_end` themselves already default to when there is no label.
    """
    if label is None:
        return "start", "end"
    return f"{label}_start", f"{label}_end"


def _should_auto_log(store, entity_id, method_name, *, auto_log=True, stacklevel):
    """Whether an auto-logging call should proceed for this request/get/put call.

    False, silently, when `store.logger` is None - the feature is then simply unused and
    `entity_id` (if passed anyway) is ignored, so mixing auto-logging stores with
    non-logging ones in the same model needs no special-casing.

    False, silently, when the call passed `auto_log=False` - a caller opting this one
    request/get/put out of auto-logging on purpose (e.g. to bracket it with hand-written
    `EventLogger.log_resource_use_start`/`_end` calls carrying step-specific fields, while
    every other call on the same store keeps auto-logging). Distinct from simply omitting
    `entity_id`: that is treated as a probable mistake and warned about, this is not.

    False, with a one-time warning per `store`, when a logger *is* configured but neither
    `entity_id` nor `auto_log=False` was passed to this call - this is what stops a
    forgotten `entity_id=` from silently producing a quieter-than-expected log with no
    signal anything is wrong, while still not erroring on every single such call in a long
    run. Mirrors the throttled `DeprecationWarning` pattern already used for a missing
    `label` in `_new_pool_resource`.
    """
    if store.logger is None:
        return False
    if not auto_log:
        return False
    if entity_id is not None:
        return True
    if not store._warned_missing_entity_id:
        warnings.warn(
            f"{type(store).__name__} has a logger configured, but entity_id was not passed "
            f"to {method_name}() - auto-logging skipped for this call. This will not be "
            "reported again for this store.",
            UserWarning,
            stacklevel=stacklevel,
        )
        store._warned_missing_entity_id = True
    return False


def _resource_use_log_kwargs(store, item, phase, *, event, pathway, extra_fields):
    """Build the kwargs for one auto-logged `log_resource_use_start`/`_end` call.

    `resource_id` is read via `getattr(item, "id_attribute", None)` rather than assumed -
    both stores are generic pools with no type constraint on what gets `put()` into them, so
    an item lacking `id_attribute` (e.g. put in by mistake via some more complex get/put
    pattern) must degrade to an unresourced log entry rather than crash the model with an
    `AttributeError`. `EventLogger` already has a dedicated warning for a missing/invalid
    `resource_id` (`BaseEvent.warn_if_missing_resource_id`), so that case is still surfaced.

    `unique_resource_id` is added automatically, mirroring the pattern already recommended
    in `TrialLogger._resolve_resource_col_name`'s docstring, whenever the item carries a
    `unique_id_attribute` (i.e. the pool was built with `label=`).
    """
    default_start, default_end = _default_resource_event_names(store.label)
    default_event = default_start if phase == "start" else default_end

    kwargs = dict(extra_fields)
    unique_id = getattr(item, "unique_id_attribute", None)
    if unique_id is not None:
        kwargs.setdefault("unique_resource_id", unique_id)

    kwargs["resource_id"] = getattr(item, "id_attribute", None)
    kwargs["event"] = event if event is not None else default_event
    kwargs["pathway"] = pathway
    return kwargs


def _register_start_log_callback(store, get_event, entity_id, event, pathway, extra_fields):
    """Append a callback to `get_event` that logs `resource_use` once it is granted.

    A simpy `Event`'s callbacks aren't invoked until `env.step()` processes it - even when
    `.succeed()` was already called synchronously at creation time (the immediate-availability
    path in both `VidigiStore`/`VidigiPriorityStore`) - so appending here, immediately after
    the event is created and before it's returned to the caller, reliably fires once the item
    is actually granted, with `env.now` at that moment being the true grant time (not the
    request time). If the request is later cancelled via `cancel_get()`, the event is removed
    from its queue and `.succeed()` is never called on it, so this callback never fires - no
    phantom "start" is logged for a request that was given up on.
    """

    def _on_grant(triggered_event):
        if not triggered_event.ok:
            return
        kwargs = _resource_use_log_kwargs(
            store,
            triggered_event.value,
            "start",
            event=event,
            pathway=pathway,
            extra_fields=extra_fields,
        )
        store.logger.log_resource_use_start(entity_id=entity_id, **kwargs)

    get_event.callbacks.append(_on_grant)


def _log_resource_use_end_now(store, item, entity_id, event, pathway, extra_fields):
    """Log a `resource_use_end` event for `item` immediately (item already in hand)."""
    kwargs = _resource_use_log_kwargs(
        store, item, "end", event=event, pathway=pathway, extra_fields=extra_fields
    )
    store.logger.log_resource_use_end(entity_id=entity_id, **kwargs)


# \\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\#
# VidigiStore and Associated Methods
# \\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\#


# MARK: VidigiStore class
class VidigiStore:
    """
    A wrapper around SimPy's Store that allows using a context manager pattern
    similar to resource requests.

    This allows code like:

    with store.request() as req:
        yield req
        # Use the item that was obtained
        yield env.timeout(10)
        # Item is automatically returned when exiting the context

    AI USE DISCLOSURE: This code was generated by Claude 3.7 Sonnet. It has been evaluated
    and tested by a human.
    """

    def __init__(
        self,
        env,
        num_resources=None,
        capacity=float("inf"),
        label=None,
        logger: Optional[EventLogger] = None,
        #  , init_items=None
    ):
        """
        Initialize the VidigiStore.

        Args:
            env: SimPy environment
            num_resources: Number of VidigiCustomResource objects to populate the store with
            capacity: Maximum capacity of the store
            label: A name for this pool of resources - see `populate()`.
            logger: An `EventLogger` (see `vidigi.logging`), optional. When given,
                `request()`/`get()`/`get_direct()`/`put()` automatically log
                `resource_use`/`resource_use_end` events around resource acquisition and
                release whenever also passed `entity_id=` - see `request()`'s docstring for
                the full behaviour. `None` (the default) leaves logging entirely manual,
                exactly as before this parameter existed.
        """
        self.env = env
        self.store = simpy.Store(env, capacity)
        self.logger = logger
        self.label = label
        self._warned_missing_entity_id = False

        if num_resources is not None:
            self.populate(num_resources, label=label, _stacklevel=4)

        # # Initialize with items if provided
        # if init_items:
        #     for item in init_items:
        #         self.store.put(item)

    def populate(self, num_resources, label=None, *, _stacklevel=3):
        """
        Populate this VidigiStore with VidigiResource objects.

        Creates `num_resources` VidigiResource objects and adds them to this store.

        Each VidigiResource is initialized with a capacity of 1 and a unique ID starting at 1.

        Parameters
        ----------
        num_resources : int
            The number of VidigiResource objects to create and add to the store.
        label : str, optional
            A name for this pool of resources, e.g. `"triage"`. When given, each
            resource also gets `.unique_id_attribute` (`f"{label}_{id_attribute}"`)
            - unique across pools when every pool is given a distinct label,
            unlike `id_attribute` alone, which restarts at 1 in every pool.
            Omitting it (the default) changes nothing about the resources
            produced, but warns that `label` will become mandatory at vidigi
            3.0 - see `vidigi.analysis.resource_utilisation`'s `by="resource"`
            docs for why. Also updates `self.label` (used to derive automatic
            resource-use logging event names - see `__init__`'s `logger=`) when
            given - a no-arg top-up call (`store.populate(5)`, adding resources
            to an already-running pool) leaves `self.label` and therefore every
            default event name for the whole store untouched.
        _stacklevel : int, default=3
            Internal - how many frames up from `_new_pool_resource` the
            missing-`label` warning should attribute to. `__init__` calling
            this internally passes `4` to still land on the caller's
            `VidigiStore(...)` line rather than on this method.

        Returns
        -------
        None
        """
        if label is not None:
            self.label = label
        _check_label_not_reused(self.env, label, stacklevel=_stacklevel)
        for i in range(num_resources):
            # self.store.put(...) directly, not self.put(...) - populating the pool is not
            # a resource being released by an entity, so it must never trigger auto-logging
            # or the "missing entity_id" warning.
            self.store.put(_new_pool_resource(self.env, i, label, stacklevel=_stacklevel))

    def request(self, entity_id=None, start_event=None, end_event=None, pathway=None, auto_log=True, **extra_fields):
        """
        Request context manager for getting an item from the store.
        The item is automatically returned when exiting the context.

        Usage:
            with store.request() as req:
                yield req  # This yields the get event
                # Now we have the item from the store
                yield env.timeout(10)
                # Item is automatically returned when exiting the context

        Automatic resource-use logging
        -------------------------------
        If this store was constructed with `logger=` and `entity_id` is passed here, a
        `resource_use` event is logged automatically once the item is actually granted (not
        when it's requested - if the request has to queue, the logged time reflects the
        grant, not the request), and a matching `resource_use_end` event is logged
        automatically in `__exit__`, right before the item is returned to the store. This
        replaces the need to call `EventLogger.log_resource_use_start`/
        `log_resource_use_end` by hand.

        If a logger is configured on this store but `entity_id` is omitted here,
        auto-logging is silently skipped for this call (after a one-time warning per store)
        - so a model can still mix auto-logging with manual `EventLogger` calls per call.
        Pass `auto_log=False` to opt this call out deliberately, with no warning - see that
        argument below.

        Args:
            entity_id: Identifier of the entity making this request, for auto-logging. Only
                meaningful when this store was constructed with `logger=`.
            start_event: Event name for the auto-logged `resource_use` start event.
                Defaults to `f"{label}_start"` (or `"start"` if this pool has no `label`).
            end_event: Event name for the auto-logged `resource_use_end` event. Defaults to
                `f"{label}_end"` (or `"end"` if this pool has no `label`).
            pathway: Optional `pathway` value forwarded to both auto-logged events.
            auto_log: Default `True`. Set `False` to skip auto-logging for this one request
                even though the store has a `logger` - for bracketing it with hand-written
                `EventLogger.log_resource_use_start`/`log_resource_use_end` calls instead
                (for example to record a value only known when the resource is released),
                while keeping the context manager's automatic item return. Unlike simply
                omitting `entity_id`, this does not emit the "entity_id was not passed"
                warning.
            **extra_fields: Any further keyword arguments are forwarded to both auto-logged
                events as extra columns in the log, exactly as passing them to
                `EventLogger.log_resource_use_start`/`log_resource_use_end` by hand would -
                e.g. `acuity=3`, `arrival_mode="ambulance"`. The same values go on both the
                `resource_use` and the `resource_use_end` event; to put different fields on
                each side, or a value only known at release time, use `get_direct()`/`put()`
                or `auto_log=False` plus manual logging. `unique_resource_id` is added on
                top automatically when this pool has a `label`.

        Returns:
            A context manager that returns the get event and handles returning the item
        """
        return _StoreRequest(
            self,
            entity_id=entity_id,
            start_event=start_event,
            end_event=end_event,
            pathway=pathway,
            auto_log=auto_log,
            extra_fields=extra_fields,
        )

    def get(self, entity_id=None, start_event=None, end_event=None, pathway=None, auto_log=True, **extra_fields):
        """
        Alias for request() to maintain compatibility with both patterns.

        See `request()` for the full parameter list, including automatic resource-use
        logging.

        Returns:
            A context manager for getting an item
        """
        return self.request(
            entity_id=entity_id,
            start_event=start_event,
            end_event=end_event,
            pathway=pathway,
            auto_log=auto_log,
            **extra_fields,
        )

    def put(self, item, entity_id=None, event=None, pathway=None, auto_log=True, **extra_fields):
        """
        Put an item into the store.

        Automatic resource-use logging
        -------------------------------
        If this store was constructed with `logger=` and `entity_id` is passed here, a
        `resource_use_end` event is logged automatically for `item` before it's returned to
        the store - pairs with a matching `get_direct(entity_id=..., event=...)` call. If a
        logger is configured but `entity_id` is omitted, auto-logging is silently skipped
        for this call (after a one-time warning per store); pass `auto_log=False` to opt
        out deliberately with no warning.

        Args:
            item: The item to put in the store
            entity_id: Identifier of the entity releasing this item, for auto-logging.
            event: Event name for the auto-logged `resource_use_end` event. Defaults to
                `f"{label}_end"` (or `"end"` if this pool has no `label`).
            pathway: Optional `pathway` value forwarded to the auto-logged event.
            auto_log: Default `True`. Set `False` to skip auto-logging for this call even
                though the store has a `logger`, with no "entity_id was not passed"
                warning - for pairing with a hand-written `EventLogger.log_resource_use_end`
                call instead.
            **extra_fields: Any further keyword arguments are forwarded to the auto-logged
                `resource_use_end` event as extra columns in the log, the same as passing
                them to `EventLogger.log_resource_use_end` directly. Because this is a
                separate call from the paired `get_direct()`, its fields are independent of
                the start event's and are evaluated now - the place to record a value only
                known once the resource is released.
        """
        if _should_auto_log(self, entity_id, "put", auto_log=auto_log, stacklevel=3):
            _log_resource_use_end_now(self, item, entity_id, event, pathway, extra_fields)
        return self.store.put(item)

    def get_direct(self, entity_id=None, event=None, pathway=None, auto_log=True, **extra_fields):
        """
        Get an item from the store without the context manager.
        Use this if you don't want to automatically return the item.

        Automatic resource-use logging
        -------------------------------
        If this store was constructed with `logger=` and `entity_id` is passed here, a
        `resource_use` event is logged automatically once the item is actually granted (not
        when it's requested). Pair this with a matching `put(entity_id=..., event=...)` call
        to also auto-log the `resource_use_end` event when the item is returned. If a logger
        is configured but `entity_id` is omitted, auto-logging is silently skipped for this
        call (after a one-time warning per store); pass `auto_log=False` to opt out
        deliberately with no warning.

        Args:
            entity_id: Identifier of the entity making this request, for auto-logging.
            event: Event name for the auto-logged `resource_use` start event. Defaults to
                `f"{label}_start"` (or `"start"` if this pool has no `label`).
            pathway: Optional `pathway` value forwarded to the auto-logged event.
            auto_log: Default `True`. Set `False` to skip auto-logging for this call even
                though the store has a `logger`, with no "entity_id was not passed"
                warning - for pairing with a hand-written
                `EventLogger.log_resource_use_start` call instead.
            **extra_fields: Any further keyword arguments are forwarded to the auto-logged
                `resource_use` event as extra columns in the log, the same as passing them
                to `EventLogger.log_resource_use_start` directly. The paired `put()`/
                `return_item()` call takes its own separate `**extra_fields` for the end
                event.

        Returns:
            A get event that can be yielded
        """
        get_event = self.store.get()
        if _should_auto_log(self, entity_id, "get_direct", auto_log=auto_log, stacklevel=3):
            _register_start_log_callback(
                self, get_event, entity_id, event, pathway, extra_fields
            )
        return get_event

    def request_direct(self, entity_id=None, event=None, pathway=None, auto_log=True, **extra_fields):
        """
        Alias for get_direct() to maintain consistent API with SimPy resources.

        See `get_direct()` for the full parameter list, including automatic resource-use
        logging.

        Returns:
            A get event that can be yielded
        """
        return self.get_direct(
            entity_id=entity_id, event=event, pathway=pathway, auto_log=auto_log, **extra_fields
        )

    def cancel_get(self, get_event):
        """
        Cancels a pending get request by removing it from the queue.

        Useful for modelling reneging, where an entity gives up waiting.

        Note that if the request has already been fulfilled, the item has
        already left the store. Cancelling does not put it back, so the caller
        should return it with `put()` in that case.

        Parameters
        ----------
        get_event : simpy.resources.store.StoreGet
            The event returned by `get_direct()` / `request_direct()`, or
            yielded by the `request()` context manager.
        """
        try:
            # The get_event is the SimPy event object that was created
            # and placed in the queue. This class wraps a simpy.Store rather
            # than subclassing it, so the queue lives on the wrapped store.
            self.store.get_queue.remove(get_event)
        except ValueError:
            # This can happen if the request was already fulfilled between the
            # timeout and the cancellation call. It's safe to ignore.
            pass

    @property
    def items(self):
        """Get all items currently in the store"""
        return self.store.items

    @property
    def capacity(self):
        """Get the capacity of the store"""
        return self.store.capacity


class _StoreRequest:
    """
    Context manager helper class for VidigiStore.
    This class manages the resource request/release pattern.

    AI USE DISCLOSURE: This code was generated by Claude 3.7 Sonnet. It has been evaluated
    and tested by a human.
    """

    def __init__(
        self,
        store,
        *,
        entity_id=None,
        start_event=None,
        end_event=None,
        pathway=None,
        auto_log=True,
        extra_fields=None,
    ):
        self.store = store
        self.item = None
        self.entity_id = entity_id
        self.end_event = end_event
        self.pathway = pathway
        self.extra_fields = extra_fields or {}
        self.get_event = store.store.get()  # Create the get event

        # See `_register_start_log_callback`'s docstring for why appending here, before
        # returning the event, still reliably captures the true grant time.
        self._should_log = _should_auto_log(
            store, entity_id, "request", auto_log=auto_log, stacklevel=4
        )
        if self._should_log:
            _register_start_log_callback(
                store, self.get_event, entity_id, start_event, pathway, self.extra_fields
            )

    def __enter__(self):
        # Return the get event which will be yielded by the user
        return self.get_event

    def __exit__(self, exc_type, exc_val, exc_tb):
        # If the get event has been processed and we have an item, put it back. This runs
        # whether or not an exception was raised during resource use (Python always calls
        # __exit__ on the way out of the `with` block), so the end-log fires unconditionally
        # once the item was actually granted.
        if self.get_event.processed and hasattr(self.get_event, "value"):
            self.item = self.get_event.value
            if self._should_log:
                _log_resource_use_end_now(
                    self.store,
                    self.item,
                    self.entity_id,
                    self.end_event,
                    self.pathway,
                    self.extra_fields,
                )
            # Return the item to the store DIRECTLY via the wrapped simpy.Store, not
            # self.store.put() (VidigiStore's own logging-aware wrapper) - the logging above
            # already covers this; going through VidigiStore.put() would either log the end
            # event twice, or (since it wouldn't have this request's entity_id) spuriously
            # warn about a missing entity_id.
            self.store.store.put(self.item)
        return False  # Don't suppress exceptions


# \\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\#


# &&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&#
# LEGACY VidigiPriorityStore and Associated Methods
# &&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&#
# MARK: LEGACY PriorityGet
class PriorityGetLegacy(simpy.resources.base.Get):
    """
    A priority-aware request for resources in a SimPy environment.

    This class extends the SimPy `Get` class to allow prioritization of
    resource requests. Requests with a smaller `priority` value are
    served first. The request time and preemption flag are also considered
    when determining the request's order.

    Attributes:
        priority (int): The priority of the request. Lower values indicate
            higher priority. Defaults to 999.
        preempt (bool): Indicates whether the request should preempt
            another resource user. Defaults to True.
            (Ignored by `PriorityResource`.)
        time (float): The simulation time when the request was made.
        usage_since (float or None): The simulation time when the
            request succeeded, or `None` if not yet fulfilled.
        key (tuple): A tuple `(priority, time, not preempt)` used for
            sorting requests.
            Consists of
            - the priority (lower value is more important)
            - the time at which the request was made (earlier requests are more important)
            - and finally the preemption flag (preempt requests are more important)

    Notes
    -----
    Credit to arabinelli
    # https://stackoverflow.com/questions/58603000/how-do-i-make-a-priority-get-request-from-resource-store
    """

    def __init__(self, resource, priority=999, preempt=True):
        self.priority = priority

        self.preempt = preempt

        self.time = resource._env.now

        self.usage_since = None

        self.key = (self.priority, self.time, not self.preempt)

        super().__init__(resource)


# MARK: LEGACY Priority Store
class VidigiPriorityStoreLegacy(simpy.resources.store.Store):
    """
    A SimPy store that processes requests with priority.

    This class extends the SimPy `Store` to include a priority queue for
    handling requests. Requests are processed based on their priority,
    submission time, and preemption flag.

    Attributes:
        GetQueue (class): A reference to the sorted queue implementation
            used for handling prioritized requests.
        get (class): A reference to the `PriorityGet` class, which handles
            the creation of prioritized requests.

    Notes
    -----
    Credit to arabinelli
    # https://stackoverflow.com/questions/58603000/how-do-i-make-a-priority-get-request-from-resource-store

    """

    GetQueue = simpy.resources.resource.SortedQueue

    get = BoundClass(PriorityGetLegacy)


# &&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&#

# ================================================#
# VidigiPriorityStore and Associated Methods
# ================================================#


# Create the OptimizedPriorityStore by subclassing simpy.Store
class VidigiPriorityStore:
    """
    An optimized SimPy priority store that eliminates delays between resource
    release and acquisition by directly triggering waiting events.

    This implementation provides the same API as the original VidigiPriorityStore
    but with immediate resource handoff between processes.

    AI USE DISCLOSURE: This code was generated by Claude 3.7 Sonnet. It has been evaluated
    and tested by a human.
    """

    def __init__(
        self,
        env,
        num_resources=None,
        capacity=float("inf"),
        label=None,
        logger: Optional[EventLogger] = None,
        #  , init_items=None
    ):
        """
        Initialize the OptimizedVidigiPriorityStore.

        Args:
            env: The SimPy environment.
            num_resources: Number of VidigiCustomResource objects to populate the store with
            capacity: Maximum capacity of the store (default: infinite).
            label: A name for this pool of resources - see `populate()`.
            logger: An `EventLogger` (see `vidigi.logging`), optional. When given,
                `request()`/`get_direct()`/`put()`/`return_item()` automatically log
                `resource_use`/`resource_use_end` events around resource acquisition and
                release whenever also passed `entity_id=` - see `request()`'s docstring for
                the full behaviour. `None` (the default) leaves logging entirely manual,
                exactly as before this parameter existed.

        """
        self.env = env
        self.capacity = capacity
        self.items = []  # if init_items is None else list(init_items)
        self.logger = logger
        self.label = label
        self._warned_missing_entity_id = False

        # Custom priority queue for get requests
        self.get_queue = []  # We'll maintain this as a sorted list
        # Standard queue for put requests
        self.put_queue = []

        if num_resources is not None:
            self.populate(num_resources, label=label, _stacklevel=4)

    def populate(self, num_resources, label=None, *, _stacklevel=3):
        """
        Populate this VidigiPriorityStore with VidigiResource objects.

        Creates `num_resources` VidigiResource objects and adds them to this store.

        Each VidigiResource is initialized with a capacity of 1 and a unique ID starting at 1.

        Parameters
        ----------
        num_resources : int
            The number of VidigiResource objects to create and add to the store.
        label : str, optional
            A name for this pool of resources, e.g. `"triage"`. When given, each
            resource also gets `.unique_id_attribute` (`f"{label}_{id_attribute}"`)
            - unique across pools when every pool is given a distinct label,
            unlike `id_attribute` alone, which restarts at 1 in every pool.
            Omitting it (the default) changes nothing about the resources
            produced, but warns that `label` will become mandatory at vidigi
            3.0 - see `vidigi.analysis.resource_utilisation`'s `by="resource"`
            docs for why. Also updates `self.label` (used to derive automatic
            resource-use logging event names - see `__init__`'s `logger=`) when
            given - a no-arg top-up call (`store.populate(5)`, adding resources
            to an already-running pool) leaves `self.label` and therefore every
            default event name for the whole store untouched.
        _stacklevel : int, default=3
            Internal - how many frames up from `_new_pool_resource` the
            missing-`label` warning should attribute to. `__init__` calling
            this internally passes `4` to still land on the caller's
            `VidigiPriorityStore(...)` line rather than on this method.

        Returns
        -------
        None
        """
        if label is not None:
            self.label = label
        _check_label_not_reused(self.env, label, stacklevel=_stacklevel)
        for i in range(num_resources):
            # self._put_item(...) directly, not self.put(...) - populating the pool is not
            # a resource being released by an entity, so it must never trigger auto-logging
            # or the "missing entity_id" warning.
            self._put_item(_new_pool_resource(self.env, i, label, stacklevel=_stacklevel))

    def request(
        self,
        priority=0,
        entity_id=None,
        start_event=None,
        end_event=None,
        pathway=None,
        auto_log=True,
        **extra_fields,
    ):
        """
        Request context manager for getting an item from the store.
        The item is automatically returned when exiting the context.

        Automatic resource-use logging
        -------------------------------
        If this store was constructed with `logger=` and `entity_id` is passed here, a
        `resource_use` event is logged automatically once the item is actually granted (not
        when it's requested - if the request has to queue, the logged time reflects the
        grant, not the request), and a matching `resource_use_end` event is logged
        automatically in `__exit__`, right before the item is returned to the store. This
        replaces the need to call `EventLogger.log_resource_use_start`/
        `log_resource_use_end` by hand.

        If a logger is configured on this store but `entity_id` is omitted here,
        auto-logging is silently skipped for this call (after a one-time warning per store)
        - so a model can still mix auto-logging with manual `EventLogger` calls per call.
        Pass `auto_log=False` to opt this call out deliberately, with no warning - see that
        argument below.

        Args:
            priority: Lower values indicate higher priority (default: 0)
            entity_id: Identifier of the entity making this request, for auto-logging. Only
                meaningful when this store was constructed with `logger=`.
            start_event: Event name for the auto-logged `resource_use` start event.
                Defaults to `f"{label}_start"` (or `"start"` if this pool has no `label`).
            end_event: Event name for the auto-logged `resource_use_end` event. Defaults to
                `f"{label}_end"` (or `"end"` if this pool has no `label`).
            pathway: Optional `pathway` value forwarded to both auto-logged events.
            auto_log: Default `True`. Set `False` to skip auto-logging for this one request
                even though the store has a `logger` - for bracketing it with hand-written
                `EventLogger.log_resource_use_start`/`log_resource_use_end` calls instead
                (for example to record a value only known when the resource is released),
                while keeping the context manager's automatic item return. Unlike simply
                omitting `entity_id`, this does not emit the "entity_id was not passed"
                warning.
            **extra_fields: Any further keyword arguments are forwarded to both auto-logged
                events as extra columns in the log, exactly as passing them to
                `EventLogger.log_resource_use_start`/`log_resource_use_end` by hand would -
                e.g. `acuity=3`, `arrival_mode="ambulance"`. The same values go on both the
                `resource_use` and the `resource_use_end` event; to put different fields on
                each side, or a value only known at release time, use `get_direct()`/`put()`
                or `auto_log=False` plus manual logging. `unique_resource_id` is added on
                top automatically when this pool has a `label`.

        Returns:
            A context manager that yields the get event and handles item return
        """
        return _OptimizedStoreRequest(
            store=self,
            priority=priority,
            entity_id=entity_id,
            start_event=start_event,
            end_event=end_event,
            pathway=pathway,
            auto_log=auto_log,
            extra_fields=extra_fields,
        )

    def get(self, priority=0):
        """
        Create an event to get an item from the store.

        Args:
            priority: Lower values indicate higher priority (default: 0)

        Returns:
            A get event that can be yielded
        """
        if self.items:
            # Items available - get one immediately
            item = self.items.pop(0)
            event = self.env.event()
            event.succeed(item)
            return event
        else:
            # No items available - create request and add to queue
            request = self.env.event()
            request.priority = priority  # Add priority attribute to the event

            # Insert into priority queue (sorted list)
            # Find the right position to maintain sorted order
            insert_pos = 0
            for i, req in enumerate(self.get_queue):
                if priority < req.priority:  # Lower value = higher priority
                    insert_pos = i
                    break
                else:
                    insert_pos = i + 1

            self.get_queue.insert(insert_pos, request)

            # Process any waiting put requests if possible
            self._process_put_queue()

            return request

    def put(self, item, entity_id=None, event=None, pathway=None, auto_log=True, **extra_fields):
        """
        Put an item into the store.

        Automatic resource-use logging
        -------------------------------
        If this store was constructed with `logger=` and `entity_id` is passed here, a
        `resource_use_end` event is logged automatically for `item` before it's put into the
        store - pairs with a matching `get_direct(entity_id=..., event=...)` call. If a
        logger is configured but `entity_id` is omitted, auto-logging is silently skipped
        for this call (after a one-time warning per store); pass `auto_log=False` to opt
        out deliberately with no warning.

        Args:
            item: The item to put in the store
            entity_id: Identifier of the entity releasing this item, for auto-logging.
            event: Event name for the auto-logged `resource_use_end` event. Defaults to
                `f"{label}_end"` (or `"end"` if this pool has no `label`).
            pathway: Optional `pathway` value forwarded to the auto-logged event.
            auto_log: Default `True`. Set `False` to skip auto-logging for this call even
                though the store has a `logger`, with no "entity_id was not passed"
                warning - for pairing with a hand-written `EventLogger.log_resource_use_end`
                call instead.
            **extra_fields: Any further keyword arguments are forwarded to the auto-logged
                `resource_use_end` event as extra columns in the log, the same as passing
                them to `EventLogger.log_resource_use_end` directly. Independent of the
                paired `get_direct()` call's fields and evaluated now - the place to record
                a value only known once the resource is released.

        Returns:
            A put event that can be yielded
        """
        if _should_auto_log(self, entity_id, "put", auto_log=auto_log, stacklevel=3):
            _log_resource_use_end_now(self, item, entity_id, event, pathway, extra_fields)
        return self._put_item(item)

    def _put_item(self, item):
        """Raw put logic, with no auto-logging - used internally by `put()` and `populate()`.

        `populate()` seeds the pool with this directly (not through `put()`) because pool
        initialization is not a resource being released by an entity.
        """
        if len(self.items) < self.capacity:
            # Space available - try to satisfy a waiting get request
            if self.get_queue:
                # Get highest-priority waiting request (first item in sorted queue)
                request = self.get_queue.pop(
                    0
                )  # Get from front (highest priority)
                # Directly trigger the request with this item
                request.succeed(item)
                # No need to add to items list as it's immediately consumed

                # Return a pre-triggered event
                event = self.env.event()
                event.succeed()
                return event
            else:
                # No waiting get requests - add to items
                self.items.append(item)

                # Return a pre-triggered event
                event = self.env.event()
                event.succeed()
                return event
        else:
            # Store is full - create a put request
            request = self.env.event()
            # Store the item with the request
            request.item = item
            self.put_queue.append(request)
            return request

    def _process_put_queue(self):
        """Process waiting put requests if store has capacity."""
        if self.put_queue and len(self.items) < self.capacity:
            # Get oldest put request
            request = self.put_queue.pop(0)
            # Add its item to store
            self.items.append(request.item)
            # Signal success
            request.succeed()

    def _process_get_requests(self):
        """Process waiting get requests if items are available."""
        while self.get_queue and self.items:
            # Get highest priority get request (first in sorted queue)
            request = self.get_queue.pop(0)
            # Get an item
            item = self.items.pop(0)
            # Directly satisfy the get request
            request.succeed(item)

    def return_item(self, item, entity_id=None, event=None, pathway=None, auto_log=True, **extra_fields):
        """
        Return an item to the store and immediately process any waiting get requests.

        This is the key to eliminating delays - it directly triggers waiting get
        requests without going through the normal put/get mechanism.

        Automatic resource-use logging
        -------------------------------
        If this store was constructed with `logger=` and `entity_id` is passed here, a
        `resource_use_end` event is logged automatically for `item` before it's returned -
        pairs with a matching `get_direct(entity_id=..., event=...)` call. If a logger is
        configured but `entity_id` is omitted, auto-logging is silently skipped for this
        call (after a one-time warning per store); pass `auto_log=False` to opt out
        deliberately with no warning.

        Args:
            item: The item to return to the store
            entity_id: Identifier of the entity releasing this item, for auto-logging.
            event: Event name for the auto-logged `resource_use_end` event. Defaults to
                `f"{label}_end"` (or `"end"` if this pool has no `label`).
            pathway: Optional `pathway` value forwarded to the auto-logged event.
            auto_log: Default `True`. Set `False` to skip auto-logging for this call even
                though the store has a `logger`, with no "entity_id was not passed"
                warning - for pairing with a hand-written `EventLogger.log_resource_use_end`
                call instead.
            **extra_fields: Any further keyword arguments are forwarded to the auto-logged
                `resource_use_end` event as extra columns in the log, the same as passing
                them to `EventLogger.log_resource_use_end` directly. Independent of the
                paired `get_direct()` call's fields and evaluated now - the place to record
                a value only known once the resource is released.
        """
        if _should_auto_log(self, entity_id, "return_item", auto_log=auto_log, stacklevel=3):
            _log_resource_use_end_now(self, item, entity_id, event, pathway, extra_fields)
        self._return_item_raw(item)

    def _return_item_raw(self, item):
        """Raw return logic, with no auto-logging.

        Used internally by `return_item()` and by `_OptimizedStoreRequest.__exit__`, which
        already does its own logging (with the request's own event names/pathway/extra
        fields) before calling this - going through `return_item()` there would log twice.
        """
        # Check if there are waiting get requests
        if self.get_queue:
            # Get highest priority waiting request (first in sorted queue)
            request = self.get_queue.pop(0)
            # Directly trigger it with the item
            request.succeed(item)
            # Item is consumed immediately - no need to store it
        else:
            # No waiting get requests - add to items
            self.items.append(item)

    def get_direct(self, priority=0, entity_id=None, event=None, pathway=None, auto_log=True, **extra_fields):
        """
        Get an item from the store without the context manager.
        Use this if you don't want to automatically return the item.

        Automatic resource-use logging
        -------------------------------
        If this store was constructed with `logger=` and `entity_id` is passed here, a
        `resource_use` event is logged automatically once the item is actually granted (not
        when it's requested). Pair this with a matching `put(entity_id=..., event=...)` or
        `return_item(entity_id=..., event=...)` call to also auto-log the `resource_use_end`
        event when the item is returned. If a logger is configured but `entity_id` is
        omitted, auto-logging is silently skipped for this call (after a one-time warning
        per store); pass `auto_log=False` to opt out deliberately with no warning.

        Args:
            priority: Lower values indicate higher priority (default: 0)
            entity_id: Identifier of the entity making this request, for auto-logging.
            event: Event name for the auto-logged `resource_use` start event. Defaults to
                `f"{label}_start"` (or `"start"` if this pool has no `label`).
            pathway: Optional `pathway` value forwarded to the auto-logged event.
            auto_log: Default `True`. Set `False` to skip auto-logging for this call even
                though the store has a `logger`, with no "entity_id was not passed"
                warning - for pairing with a hand-written
                `EventLogger.log_resource_use_start` call instead.
            **extra_fields: Any further keyword arguments are forwarded to the auto-logged
                `resource_use` event as extra columns in the log, the same as passing them
                to `EventLogger.log_resource_use_start` directly. The paired `put()`/
                `return_item()` call takes its own separate `**extra_fields` for the end
                event.

        Returns:
            A get event that can be yielded
        """
        get_event = self.get(priority=priority)
        if _should_auto_log(self, entity_id, "get_direct", auto_log=auto_log, stacklevel=3):
            _register_start_log_callback(
                self, get_event, entity_id, event, pathway, extra_fields
            )
        return get_event

    def request_direct(self, priority=0, entity_id=None, event=None, pathway=None, auto_log=True, **extra_fields):
        """
        Alias for get_direct() to maintain consistent API.

        See `get_direct()` for the full parameter list, including automatic resource-use
        logging.

        Returns:
            A get event that can be yielded
        """
        return self.get_direct(
            priority=priority,
            entity_id=entity_id,
            event=event,
            pathway=pathway,
            auto_log=auto_log,
            **extra_fields,
        )

    def cancel_get(self, get_event):
        """
        Cancels a pending get request by removing it from the queue.
        """
        try:
            # The get_event is the SimPy event object that was created
            # and placed in the queue.
            self.get_queue.remove(get_event)
            # You might want to add a print statement for debugging:
            # print(f"{self.env.now}: Successfully cancelled and removed a get request from the queue.")
        except ValueError:
            # This can happen if the request was already fulfilled between the
            # timeout and the cancellation call. It's safe to ignore.
            # print(f"{self.env.now}: Attempted to cancel a request that was no longer in the queue (likely already fulfilled).")
            pass


# MARK: Priority Store Request
class _OptimizedStoreRequest:
    """
    Context manager helper class for OptimizedVidigiPriorityStore.
    This class manages the resource request/release pattern with
    immediate release through direct event triggering.
    """

    def __init__(
        self,
        store,
        priority=0,
        *,
        entity_id=None,
        start_event=None,
        end_event=None,
        pathway=None,
        auto_log=True,
        extra_fields=None,
    ):
        self.store = store
        self.item = None
        self.priority = priority
        self.entity_id = entity_id
        self.end_event = end_event
        self.pathway = pathway
        self.extra_fields = extra_fields or {}
        self.get_event = store.get(
            priority=self.priority
        )  # Create the get event

        # See `_register_start_log_callback`'s docstring for why appending here, before
        # returning the event, still reliably captures the true grant time - including for
        # this store's immediate-availability path, where `.succeed()` already ran
        # synchronously inside `store.get()` above.
        self._should_log = _should_auto_log(
            store, entity_id, "request", auto_log=auto_log, stacklevel=4
        )
        if self._should_log:
            _register_start_log_callback(
                store, self.get_event, entity_id, start_event, pathway, self.extra_fields
            )

    def __enter__(self):
        # Return the get event which will be yielded by the user
        return self.get_event

    def __exit__(self, exc_type, exc_val, exc_tb):
        # If the get event has been processed and we have an item, put it back. This runs
        # whether or not an exception was raised during resource use (Python always calls
        # __exit__ on the way out of the `with` block), so the end-log fires unconditionally
        # once the item was actually granted.
        if self.get_event.processed and hasattr(self.get_event, "value"):
            self.item = self.get_event.value
            if self._should_log:
                _log_resource_use_end_now(
                    self.store,
                    self.item,
                    self.entity_id,
                    self.end_event,
                    self.pathway,
                    self.extra_fields,
                )
            # Return the item to the store DIRECTLY - key optimization point. Uses the raw
            # method, not return_item(), since the logging above already covers this - going
            # through return_item() would log the end event twice.
            self.store._return_item_raw(self.item)
        return False  # Don't suppress exceptions


class VidigiResourceLegacy(simpy.Resource):
    """
    A custom resource class that extends simpy.Resource with an additional ID attribute.

    This class allows for more detailed tracking and management of resources in a simulation
    by adding an ID attribute to each resource instance.

    Parameters
    ----------
    env : simpy.Environment
        The SimPy environment in which this resource exists.
    capacity : int
        The capacity of the resource (how many units can be in use simultaneously).
    id_attribute : any, optional
        An identifier for the resource (default is None).

    Attributes
    ----------
    id_attribute : any
        An identifier for the resource, which can be used for custom tracking or logic.

    Notes
    -----
    This class inherits from simpy.Resource and overrides the request and release methods
    to allow for custom handling of the id_attribute. The actual implementation of ID
    assignment or reset logic should be added by the user as needed.

    Examples
    --------
    ```
    env = simpy.Environment()
    custom_resource = VidigiResource(env, capacity=1, id_attribute="Resource_1")
    def process(env, resource):
        with resource.request() as req:
            yield req
            print(f"Using resource with ID: {resource.id_attribute}")
            yield env.timeout(1)
    env.process(process(env, custom_resource))
    env.run()
    ```
    Using resource with ID: Resource_1
    """

    def __init__(self, env, capacity, id_attribute=None):
        super().__init__(env, capacity)
        self.id_attribute = id_attribute

    def request(self, *args, **kwargs):
        """
        Request the resource.

        This method can be customized to handle the ID attribute when a request is made.
        Currently, it simply calls the parent class's request method.

        Returns
        -------
        simpy.events.Request
            A SimPy request event.
        """
        # Add logic to handle the ID attribute when a request is made
        # For example, you can assign an ID to the requester
        # self.id_attribute = assign_id_logic()
        return super().request(*args, **kwargs)

    def release(self, *args, **kwargs):
        """
        Release the resource.

        This method can be customized to handle the ID attribute when a release is made.
        Currently, it simply calls the parent class's release method.

        Returns
        -------
        None
        """
        # Add logic to handle the ID attribute when a release is made
        # For example, you can reset the ID attribute
        # reset_id_logic(self.id_attribute)
        return super().release(*args, **kwargs)


# MARK: Archived Classes

# Create the PriorityStore by subclassing simpy.Store
# class VidigiPriorityStore(simpy.resources.store.Store):
#     """
#     A SimPy Store that processes 'get' requests based on priority.
#     Lower priority numbers represent higher priority and are processed first.
#     Supports the context manager pattern for automatic item return.

#     Inherits from simpy.Store and overrides the get queue logic and binds
#     PriorityGet to the get method.
#     """

#     GetQueue = simpy.resources.resource.SortedQueue
#     PutQueue = simpy.resources.resource.SortedQueue

#     getPriorityAware = BoundClass(PriorityGetLegacy)

#     def __init__(self, env, capacity=float('inf'), init_items=None):
#         """
#         Initialize the VidigiPriorityStore.

#         Args:
#             env: The SimPy environment.
#             capacity: Maximum capacity of the store (default: infinite).
#         """

#         self.env = env
#         self._env = env
#         self.store = simpy.Store(env, capacity)
#         self.get_queue = self.GetQueue()
#         self.put_queue = self.PutQueue()

#         # Initialize with items if provided
#         if init_items:
#             for item in init_items:
#                 self.store.put(item)

#     def request(self, priority):
#         """
#         Request context manager for getting an item from the store.
#         The item is automatically returned when exiting the context.

#         Usage:
#             with store.request() as req:
#                 yield req  # This yields the get event
#                 # Now we have the item from the store
#                 yield env.timeout(10)
#                 # Item is automatically returned when exiting the context

#         Returns:
#             A context manager that returns the get event and handles returning the item
#         """
#         return _PriorityStoreRequest(store=self, priority=priority)

#     def get(self):
#         """
#         Alias for request() to maintain compatibility with both patterns.

#         Returns:
#             A context manager for getting an item
#         """
#         return self.request()

#     def put(self, item):
#         """
#         Put an item into the store.

#         Args:
#             item: The item to put in the store
#         """
#         return self.store.put(item)

#     def get_direct(self):
#         """
#         Get an item from the store without the context manager.
#         Use this if you don't want to automatically return the item.

#         Returns:
#             A get event that can be yielded
#         """
#         return self.store.get()

#     def request_direct(self):
#         """
#         Alias for get_direct() to maintain consistent API with SimPy resources.

#         Returns:
#             A get event that can be yielded
#         """
#         return self.get_direct()

#     @property
#     def items(self):
#         """Get all items currently in the store"""
#         return self.store.items

#     @property
#     def capacity(self):
#         """Get the capacity of the store"""
#         return self.store.capacity


# class _PriorityStoreRequest:
#     """
#     Context manager helper class for VidigiStore.
#     This class manages the resource request/release pattern.

#     AI USE DISCLOSURE: This code was generated by Claude 3.7 Sonnet. It has been evaluated,
#     modified and tested by a human.
#     """

#     def __init__(self, store, priority):
#         self.store = store
#         self.item = None
#         self.priority = priority
#         self.get_event = store.getPriorityAware(priority=self.priority)  # Create the get event

#     def __enter__(self):
#         # Return the get event which will be yielded by the user
#         return self.get_event

#     def __exit__(self, exc_type, exc_val, exc_tb):
#         # If the get event has been processed and we have an item, put it back
#         if self.get_event.processed and hasattr(self.get_event, 'value'):
#             self.item = self.get_event.value
#             # Return the item to the store
#             self.store.put(self.item)
#         return False  # Don't suppress exceptions

# # class PriorityGet(simpy.resources.store.StoreGet):
# class PriorityGet(simpy.resources.base.Get):
#     """
#     Request to get an item from a priority store resource with a given priority.

#     This prioritized request class is used for implementing priority-based
#     item retrieval from a store.

#     Notes
#     -----
#     Credit to arabinelli
#     # https://stackoverflow.com/questions/58603000/how-do-i-make-a-priority-get-request-from-resource-store
#     """
#     def __init__(self, resource, priority=999, preempt=True):
#         """
#         Initialize a prioritized get request.

#         Args:
#             resource: The store resource to request from
#             priority: Priority of the request (lower value = higher priority)
#         """
#         self.priority = priority

#         self.preempt = preempt

#         self.time = resource._env.now

#         self.usage_since = None

#         self.key = (self.priority, self.time, not self.preempt)

#         super().__init__(resource)


# class VidigiPriorityStore:
#     """
#     A SimPy store that processes requests with priority and supports the context manager pattern.

#     This class extends the SimPy `Store` to include a priority queue for
#     handling requests. Requests are processed based on their priority and submission time.
#     It also supports the context manager pattern for easier resource management.

#     Usage:
#         with store.request(priority=1) as req:
#             item = yield req  # Get the item from the store
#             # Use the item
#             yield env.timeout(10)
#             # Item is automatically returned when exiting the context
#     """
#     # GetQueue = simpy.resources.resource.SortedQueue

#     # get = BoundClass(PriorityGet)

#     def __init__(self, env, capacity=float('inf'), init_items=None):
#         """
#         Initialize the VidigiStore.

#         Args:
#             env: SimPy environment
#             capacity: Maximum capacity of the store
#             init_items: Initial items to put in the store
#         """
#         self.env = env
#         self._env = env
#         self.store = simpy.Store(env, capacity)
#         self.get_queue = simpy.resources.resource.SortedQueue

#         # Initialize with items if provided
#         if init_items:
#             for item in init_items:
#                 self.store.put(item)

#     def request(self, priority=0):
#         """
#         Request context manager for getting an item from the store with priority.
#         The item is automatically returned when exiting the context.

#         Args:
#             priority: Priority of the request (lower value = higher priority)

#         Usage:
#             with store.request(priority=1) as req:
#                 yield req  # This yields the get event
#                 # Now we have the item from the store
#                 yield env.timeout(10)
#                 # Item is automatically returned when exiting the context

#         Returns:
#             A context manager that returns the get event and handles returning the item
#         """
#         return _PriorityStoreRequest(self, priority)
#         # return PriorityGet(self, priority)

#     def get(self, priority=0):
#         """
#         Alias for request() to maintain compatibility with both patterns.

#         Returns:
#             A context manager for getting an item
#         """
#         return self.request(priority)

#     def put(self, item):
#         """
#         Put an item into the store.

#         Args:
#             item: The item to put in the store
#         """
#         return self.store.put(item)

#     def get_direct(self, priority=0):
#         """
#         Get an item from the store without the context manager, with priority.
#         Use this if you don't want to automatically return the item.

#         Args:
#             priority: Priority of the request (lower value = higher priority)

#         Returns:
#             A get event that can be yielded
#         """
#         return self.get(priority=priority)

#     def request_direct(self, priority=0):
#         """
#         Alias for get_direct() to maintain consistent API with SimPy resources.

#         Args:
#             priority: Priority of the request (lower value = higher priority)

#         Returns:
#             A get event that can be yielded
#         """
#         return self.get_direct(priority=priority)

# class _PriorityStoreRequest:
#     """
#     Context manager helper class for VidigiPriorityStore.
#     This class manages the resource request/release pattern with priority.
#     """

#     def __init__(self, store, priority=0):
#         self.store = store
#         self.item = None
#         self.priority = priority
#         self.get_event = store.store.get(priority=priority)  # Create the get event with priority

#     def __enter__(self):
#         # Return the get event which will be yielded by the user
#         return self.get_event

#     def __exit__(self, exc_type, exc_val, exc_tb):
#         # If the get event has been processed and we have an item, put it back
#         if self.get_event.processed and hasattr(self.get_event, 'value'):
#             self.item = self.get_event.value
#             # Return the item to the store
#             self.store.put(self.item)
#         return False  # Don't suppress exceptions


# ================================================#
