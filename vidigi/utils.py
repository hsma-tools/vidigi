import simpy
from simpy.core import BoundClass
from pydantic import BaseModel, Field, field_validator, model_validator, ValidationInfo
from typing import Optional, Literal, Any, List
import json
import pandas as pd
from pathlib import Path
from io import StringIO, TextIOBase
from datetime import datetime
import plotly.express as px
import warnings

class VidigiResource(simpy.Resource):
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

def populate_store(num_resources, simpy_store, sim_env):
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
    simpy_store : simpy.Store or vidigi.utils.VidigiPriorityStore
        The SimPy Store object to populate with resources.
    sim_env : simpy.Environment
        The SimPy environment in which the resources and store exist.

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
    >>> populate_store(5, resource_store, env)
    >>> len(resource_store.items)  # The store now contains 5 VidigiResource objects
    5
    """
    for i in range(num_resources):

        simpy_store.put(
            VidigiResource(
                sim_env,
                capacity=1,
                id_attribute = i+1)
            )

#\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\#
# VidigiStore and Associated Methods
#\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\#

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

    def __init__(self, env,
                 capacity=float('inf'),
                 num_resources=None
                #  , init_items=None
                 ):
        """
        Initialize the VidigiStore.

        Args:
            env: SimPy environment
            capacity: Maximum capacity of the store
        """
        self.env = env
        self.store = simpy.Store(env, capacity)

        if num_resources is not None:
            self.populate(num_resources)

        # # Initialize with items if provided
        # if init_items:
        #     for item in init_items:
        #         self.store.put(item)

    def populate(self, num_resources):
        """
        Populate this VidigiStore with VidigiResource objects.

        Creates `num_resources` VidigiResource objects and adds them to this store.

        Each VidigiResource is initialized with a capacity of 1 and a unique ID starting at 1.

        Parameters
        ----------
        num_resources : int
            The number of VidigiResource objects to create and add to the store.

        Returns
        -------
        None
        """
        for i in range(num_resources):
            self.put(
                VidigiResource(
                    self.env,
                    capacity=1,
                    id_attribute=i + 1
                )
            )

    def request(self):
        """
        Request context manager for getting an item from the store.
        The item is automatically returned when exiting the context.

        Usage:
            with store.request() as req:
                yield req  # This yields the get event
                # Now we have the item from the store
                yield env.timeout(10)
                # Item is automatically returned when exiting the context

        Returns:
            A context manager that returns the get event and handles returning the item
        """
        return _StoreRequest(self)

    def get(self):
        """
        Alias for request() to maintain compatibility with both patterns.

        Returns:
            A context manager for getting an item
        """
        return self.request()

    def put(self, item):
        """
        Put an item into the store.

        Args:
            item: The item to put in the store
        """
        return self.store.put(item)

    def get_direct(self):
        """
        Get an item from the store without the context manager.
        Use this if you don't want to automatically return the item.

        Returns:
            A get event that can be yielded
        """
        return self.store.get()

    def request_direct(self):
        """
        Alias for get_direct() to maintain consistent API with SimPy resources.

        Returns:
            A get event that can be yielded
        """
        return self.get_direct()

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

    def __init__(self, store):
        self.store = store
        self.item = None
        self.get_event = store.store.get()  # Create the get event

    def __enter__(self):
        # Return the get event which will be yielded by the user
        return self.get_event

    def __exit__(self, exc_type, exc_val, exc_tb):
        # If the get event has been processed and we have an item, put it back
        if self.get_event.processed and hasattr(self.get_event, 'value'):
            self.item = self.get_event.value
            # Return the item to the store
            self.store.put(self.item)
        return False  # Don't suppress exceptions

#\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\#


#&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&#
# LEGACY VidigiPriorityStore and Associated Methods
#&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&#
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

#&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&#

#================================================#
# VidigiPriorityStore and Associated Methods
#================================================#

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

    def __init__(self, env,
                 capacity=float('inf'),
                 num_resources=None
                #  , init_items=None
                 ):
        """
        Initialize the OptimizedVidigiPriorityStore.

        Args:
            env: The SimPy environment.
            capacity: Maximum capacity of the store (default: infinite).

        """
        self.env = env
        self.capacity = capacity
        self.items = [] #if init_items is None else list(init_items)

        # Custom priority queue for get requests
        self.get_queue = []  # We'll maintain this as a sorted list
        # Standard queue for put requests
        self.put_queue = []

        if num_resources is not None:
            self.populate(num_resources)

    def populate(self, num_resources):
        """
        Populate this VidigiPriorityStore with VidigiResource objects.

        Creates `num_resources` VidigiResource objects and adds them to this store.

        Each VidigiResource is initialized with a capacity of 1 and a unique ID starting at 1.

        Parameters
        ----------
        num_resources : int
            The number of VidigiResource objects to create and add to the store.

        Returns
        -------
        None
        """
        for i in range(num_resources):
            self.put(
                VidigiResource(
                    self.env,
                    capacity=1,
                    id_attribute=i + 1
                )
            )

    def request(self, priority=0):
        """
        Request context manager for getting an item from the store.
        The item is automatically returned when exiting the context.

        Args:
            priority: Lower values indicate higher priority (default: 0)

        Returns:
            A context manager that yields the get event and handles item return
        """
        return _OptimizedStoreRequest(store=self, priority=priority)

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

    def put(self, item):
        """
        Put an item into the store.

        Args:
            item: The item to put in the store

        Returns:
            A put event that can be yielded
        """
        if len(self.items) < self.capacity:
            # Space available - try to satisfy a waiting get request
            if self.get_queue:
                # Get highest-priority waiting request (first item in sorted queue)
                request = self.get_queue.pop(0)  # Get from front (highest priority)
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

    def return_item(self, item):
        """
        Return an item to the store and immediately process any waiting get requests.

        This is the key to eliminating delays - it directly triggers waiting get
        requests without going through the normal put/get mechanism.

        Args:
            item: The item to return to the store
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

    def get_direct(self, priority=0):
        """
        Get an item from the store without the context manager.
        Use this if you don't want to automatically return the item.

        Returns:
            A get event that can be yielded
        """
        return self.get(priority=priority)

    def request_direct(self, priority=0):
        """
        Alias for get_direct() to maintain consistent API.

        Returns:
            A get event that can be yielded
        """
        return self.get_direct(priority=priority)


class _OptimizedStoreRequest:
    """
    Context manager helper class for OptimizedVidigiPriorityStore.
    This class manages the resource request/release pattern with
    immediate release through direct event triggering.
    """

    def __init__(self, store, priority=0):
        self.store = store
        self.item = None
        self.priority = priority
        self.get_event = store.get(priority=self.priority)  # Create the get event

    def __enter__(self):
        # Return the get event which will be yielded by the user
        return self.get_event

    def __exit__(self, exc_type, exc_val, exc_tb):
        # If the get event has been processed and we have an item, put it back
        if self.get_event.processed and hasattr(self.get_event, 'value'):
            self.item = self.get_event.value
            # Return the item to the store DIRECTLY - key optimization point
            self.store.return_item(self.item)
        return False  # Don't suppress exceptions



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


#================================================#


#'''''''''''''''''''''''''''''''''''''#
# Webdev + visualisation helpers
#'''''''''''''''''''''''''''''''''''''#
def streamlit_play_all():
    try:
        from streamlit_javascript import st_javascript

        st_javascript("""new Promise((resolve, reject) => {
    console.log('You pressed the play button');

    const parentDocument = window.parent.document;

    // Define playButtons at the beginning
    const playButtons = parentDocument.querySelectorAll('g.updatemenu-button text');

    let buttonFound = false;

    // Create an array to hold the click events to dispatch later
    let clickEvents = [];

    // Loop through all found play buttons
    playButtons.forEach(button => {
        if (button.textContent.trim() === '▶') {
        console.log("Queueing click on button");
        const clickEvent = new MouseEvent('click', {
            view: window,
            bubbles: true,
            cancelable: true
        });

        // Store the click event in the array
        clickEvents.push(button.parentElement);
        buttonFound = true;
        }
    });

    // If at least one button is found, dispatch all events
    if (buttonFound) {
        console.log('Dispatching click events');
        clickEvents.forEach(element => {
        element.dispatchEvent(new MouseEvent('click', {
            view: window,
            bubbles: true,
            cancelable: true
        }));
        });

        resolve('All buttons clicked successfully');
    } else {
        reject('No play buttons found');
    }
    })
    .then((message) => {
    console.log(message);
    return 'Play clicks completed';
    })
    .catch((error) => {
    console.log(error);
    return 'Operation failed';
    })
    .then((finalMessage) => {
    console.log(finalMessage);
    });

    """)

    except ImportError:
        raise ImportError(
            "This function requires the dependency 'st_javascript', but this is not installed with vidigi by default. "
            "Install it with: pip install vidigi[helper]"
        )

RECOGNIZED_EVENT_TYPES = {'arrival_departure', 'resource_use', 'resource_use_end', 'queue'}

class BaseEvent(BaseModel):
    entity_id: Any = Field(
        ...,
        description="Identifier for the entity related to this event (e.g. patient ID, customer ID). Can be any type."
    )

    event_type: str = Field(
        ...,
        description=f"Type of event. Recommended values: {', '.join(RECOGNIZED_EVENT_TYPES)}"
    )

    event: str = Field(..., description="Name of the specific event.")

    time: float = Field(..., description="Simulation time or timestamp of event.")

    # Optional commonly-used fields
    pathway: Optional[str] = None

    run_number: Optional[int] = Field(
        default=None,
        description="A numeric value identifying the simulation run this record is associated with."
    )

    timestamp: Optional[datetime] = Field(
        default=None,
        description="Real-world timestamp of the event, if available."
    )

    resource_id: Optional[int] = Field(
        None,
        description="ID of the resource involved (required for resource use events)."
        )

    # Allow arbitrary extra fields
    model_config = {
        "extra": "allow"
    }

    @field_validator("event_type", mode="before")
    @classmethod
    def warn_if_unrecognized_event_type(cls, v: str, info: ValidationInfo):
        if v not in RECOGNIZED_EVENT_TYPES:
            warnings.warn(
                f"Unrecognized event_type '{v}'. Recommended values are: {', '.join(RECOGNIZED_EVENT_TYPES)}.",
                UserWarning,
                stacklevel=3
            )
        return v

    @field_validator("resource_id", mode="before")
    @classmethod
    def warn_if_missing_resource_id(cls, v, info: ValidationInfo):
        etype = info.data.get("event_type")  # <-- access validated fields here
        if etype in ("resource_use", "resource_use_end"):
            if v is None:
                warnings.warn(
                    f"resource_id is recommended for event_type '{etype}', but was not provided.",
                    UserWarning,
                    stacklevel=3
                )
            elif not isinstance(v, int):
                warnings.warn(
                    "resource_id should be an integer, but received type "
                    f"{type(v).__name__}.",
                    UserWarning,
                    stacklevel=3
                )
        return v


    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, value):
        if value is None or isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
        # Try other common formats
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        raise ValueError(f'Unrecognized or ambiguous datetime format for timestamp: {value}. Please use a year-first format such as "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", or "%Y-%m-%d".')

    @model_validator(mode="after")
    def validate_event_logic(self) -> 'BaseEvent':
        """
        Enforce constraints between event_type and event.
        """
        if self.event_type == 'arrival_departure':
            if self.event not in ['arrival', 'depart']:
                raise ValueError(
                    f"When event_type is 'arrival_departure', event must be 'arrival' or 'depart'. Got '{self.event}'."
                )
        # Here we could add more logic if desired

        return self

class EventLogger:
    def __init__(self, event_model=BaseEvent, env: Any = None, run_number: int = None):
        self.event_model = event_model
        self.env = env  # Optional simulation env with .now
        self.run_number = run_number
        self._log: List[dict] = []

    def log_event(self, **event_data):
        if "time" not in event_data:
            if self.env is not None and hasattr(self.env, "now"):
                event_data["time"] = self.env.now
            else:
                raise ValueError("Missing 'time' and no simulation environment provided.")

        if "run_number" not in event_data:
            if self.run_number is not None:
                event_data["run_number"] = self.run_number

        try:
            event = self.event_model(**event_data)
        except Exception as e:
            raise ValueError(f"Invalid event data: {e}")

        self._log.append(event.model_dump())

    #################################################################
    # Logging Helper Functions                                      #
    #################################################################

    def log_arrival(self, *, entity_id: Any, time: Optional[float] = None,
                    pathway: Optional[str] = None, run_number: Optional[int] = None,
                    **extra_fields):
        """
        Helper to log an arrival event with the correct event_type and event fields.
        """
        event_data = {
            "entity_id": entity_id,
            "event_type": "arrival_departure",
            "event": "arrival",
            "time": time,
            "pathway": pathway,
            "run_number": run_number,
        }
        event_data.update(extra_fields)
        self.log_event(**{k: v for k, v in event_data.items() if v is not None})

    def log_departure(self, *, entity_id: Any, time: Optional[float] = None,
                      pathway: Optional[str] = None, run_number: Optional[int] = None,
                      **extra_fields):
        """
        Helper to log a departure event with the correct event_type and event fields.
        """
        event_data = {
            "entity_id": entity_id,
            "event_type": "arrival_departure",
            "event": "depart",
            "time": time,
            "pathway": pathway,
            "run_number": run_number,
        }
        event_data.update(extra_fields)
        self.log_event(**{k: v for k, v in event_data.items() if v is not None})

    def log_queue(self, *, entity_id: Any, event: str, time: Optional[float] = None,
                  pathway: Optional[str] = None, run_number: Optional[int] = None,
                  **extra_fields):
        """
        Log a queue event. The 'event' here can be any string describing the queue event.
        """
        event_data = {
            "entity_id": entity_id,
            "event_type": "queue",
            "event": event,
            "time": time,
            "pathway": pathway,
            "run_number": run_number,
        }
        event_data.update(extra_fields)
        self.log_event(**{k: v for k, v in event_data.items() if v is not None})

    def log_resource_use_start(self, *, entity_id: Any, resource_id: int, time: Optional[float] = None,
                               pathway: Optional[str] = None, run_number: Optional[int] = None,
                               **extra_fields):
        """
        Log the start of resource use. Requires resource_id.
        """
        event_data = {
            "entity_id": entity_id,
            "event_type": "resource_use",
            "event": "start",
            "time": time,
            "resource_id": resource_id,
            "pathway": pathway,
            "run_number": run_number,
        }
        event_data.update(extra_fields)
        self.log_event(**{k: v for k, v in event_data.items() if v is not None})

    def log_resource_use_end(self, *, entity_id: Any, resource_id: int, time: Optional[float] = None,
                             pathway: Optional[str] = None, run_number: Optional[int] = None,
                             **extra_fields):
        """
        Log the end of resource use. Requires resource_id.
        """
        event_data = {
            "entity_id": entity_id,
            "event_type": "resource_use_end",
            "event": "end",
            "time": time,
            "resource_id": resource_id,
            "pathway": pathway,
            "run_number": run_number,
        }
        event_data.update(extra_fields)
        self.log_event(**{k: v for k, v in event_data.items() if v is not None})

    ####################################################
    # Accessing and exporting the resulting logs       #
    ####################################################

    @property
    def log(self):
        return self._log

    def get_log(self) -> List[dict]:
        return self._log

    def to_json_string(self, indent: int = 2) -> str:
        """Return the event log as a pretty JSON string."""
        return json.dumps(self._log, indent=indent)

    def to_json(self, path_or_buffer: str | Path | TextIOBase, indent: int = 2) -> None:
        """Write the event log to a JSON file or file-like buffer."""
        if not self._log:
            raise ValueError("Event log is empty.")
        json_str = self.to_json_string(indent=indent)

        if isinstance(path_or_buffer, (str, Path)):
            with open(path_or_buffer, 'w', encoding='utf-8') as f:
                f.write(json_str)
        else:
            # Assume it's a writable file-like object
            path_or_buffer.write(json_str)

    def to_csv(self, path_or_buffer: str | Path | TextIOBase) -> None:
        """Write the log to a CSV file."""
        if not self._log:
            raise ValueError("Event log is empty.")

        df = self.to_dataframe()
        df.to_csv(path_or_buffer, index=False)

    def to_dataframe(self) -> pd.DataFrame:
        """Convert the event log to a pandas DataFrame."""
        return pd.DataFrame(self._log)

    ####################################################
    # Summarising Logs                                 #
    ####################################################

    def summary(self) -> dict:
        if not self._log:
            return {"total_events": 0}
        df = self.to_dataframe()
        return {
            "total_events": len(df),
            "event_types": df["event_type"].value_counts().to_dict(),
            "time_range": (df["time"].min(), df["time"].max()),
            "unique_entities": df["entity_id"].nunique() if "entity_id" in df else None,
        }

    ####################################################
    # Accessing certain elements of logs               #
    ####################################################

    def get_events_by_run(self, run_number: Any, as_dataframe: bool = True):
        """Return all events associated with a specific entity_id."""
        filtered = [event for event in self._log if event.get("run_number") == run_number]
        return pd.DataFrame(filtered) if as_dataframe else filtered

    def get_events_by_entity(self, entity_id: Any, as_dataframe: bool = True):
        """Return all events associated with a specific entity_id."""
        filtered = [event for event in self._log if event.get("entity_id") == entity_id]
        return pd.DataFrame(filtered) if as_dataframe else filtered

    def get_events_by_event_type(self, event_type: str, as_dataframe: bool = True):
        """Return all events of a specific event_type."""
        filtered = [event for event in self._log if event.get("event_type") == event_type]
        return pd.DataFrame(filtered) if as_dataframe else filtered

    def get_events_by_event_name(self, event: str, as_dataframe: bool = True):
        """Return all events of a specific event_type."""
        filtered = [event for event in self._log if event.get("event") == event]
        return pd.DataFrame(filtered) if as_dataframe else filtered

    ####################################################
    # Plotting from logs                               #
    ####################################################

    def plot_entity_timeline(self, entity_id: any):
        """
        Plot a timeline of events for a specific entity_id.
        """
        if not self._log:
            raise ValueError("Event log is empty.")

        df = self.to_dataframe()
        entity_events = df[df["entity_id"] == entity_id]

        if entity_events.empty:
            raise ValueError(f"No events found for entity_id = {entity_id}")

        # Sort by time for timeline plot
        entity_events = entity_events.sort_values("time")

        fig = px.scatter(entity_events,
                         x="time",
                         y=["event_type"],  # y axis can show event_type to separate events vertically
                         color="event_type",
                         hover_data=["event", "pathway", "run_number"],
                         labels={"time": "Time", "event_type": "Event Type"},
                         title=f"Timeline of Events for Entity {entity_id}")

        # Optional: jitter y axis for better visualization if multiple events at same time
        fig.update_traces(marker=dict(size=10, line=dict(width=1, color='DarkSlateGrey')))

        fig.update_yaxes(type="category")  # treat event_type as categorical on y-axis

        fig.show()
