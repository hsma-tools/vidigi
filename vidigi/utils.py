import simpy
import pandas as pd
from simpy.core import BoundClass
from contextlib import contextmanager

class CustomResource(simpy.Resource):
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
    custom_resource = CustomResource(env, capacity=1, id_attribute="Resource_1")
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

class PriorityGet(simpy.resources.base.Get):
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

class VidigiPriorityStore(simpy.resources.store.Store):
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

    get = BoundClass(PriorityGet)

def populate_store(num_resources, simpy_store, sim_env):
    """
    Populate a SimPy Store (or VidigiPriorityStore) with CustomResource objects.

    This function creates a specified number of CustomResource objects and adds them to
    a SimPy Store, a VidigiStore, or VidigiPriorityStore.

    Each CustomResource is initialized with a capacity of 1 and a unique ID attribute,
    which is crucial for animation functions where you wish to show an individual entity
    consistently using the same resource.

    If using VidigiPriorityStore, you will need to pass the relevant priority in to the
    .get() argument when pulling a resource out of the store.

    Parameters
    ----------
    num_resources : int
        The number of CustomResource objects to create and add to the store.
    simpy_store : simpy.Store or vidigi.utils.VidigiPriorityStore
        The SimPy Store object to populate with resources.
    sim_env : simpy.Environment
        The SimPy environment in which the resources and store exist.

    Returns
    -------
    None

    Notes
    -----
    - Each CustomResource is created with a capacity of 1.
    - The ID attribute of each CustomResource is set to its index in the creation loop plus one,
      ensuring unique IDs starting from 1.
    - This function is typically used to initialize a pool of resources at the start of a simulation.

    Examples
    --------
    >>> import simpy
    >>> env = simpy.Environment()
    >>> resource_store = simpy.Store(env)
    >>> populate_store(5, resource_store, env)
    >>> len(resource_store.items)  # The store now contains 5 CustomResource objects
    5
    """
    for i in range(num_resources):

        simpy_store.put(
            CustomResource(
                sim_env,
                capacity=1,
                id_attribute = i+1)
            )


def event_log_from_ciw_recs(ciw_recs_obj, node_name_list):
    """
    Given the ciw recs object, return a dataframe in the format expected by the vidigi
    functions
    - reshape_for_animation
    OR
    - animate_activity_log

    Parameters
    ----------
    ciw_recs_obj: list of tuples
        The output of the .get_all_records() method run on the ciw simulation object.
        This is a list of named tuples.
        See https://ciw.readthedocs.io/en/latest/Tutorial/GettingStarted/part_3.html
        and https://ciw.readthedocs.io/en/latest/Reference/results.html for more details.


    node_name_list: list of strings
        User-defined list of strings where each string relates to the resource or activity
        that will take place at that ciw node

    Returns
    -------
    pd.DataFrame

    Notes
    -----
    Given the ciw recs object, if we know the nodes and what they relate to,
    we can build up a picture  the arrival date for the first tuple
    for a given user ID is the arrival

    Then, for each node:
    - the arrival date for a given node is when they start queueing
    - the service start date is when they stop queueing
    - the service start date is when they begin using the resource
    - the service end date is when the resource use ends
    - the server ID is the equivalent of a simpy resource use ID

    A more complex multi-node example can be found in https://github.com/Bergam0t/ciw-example-animation
    in the files
    - **ciw_model.py**
    - **vidigi_experiments.py**

    Examples
    ------
    # Example taken from https://ciw.readthedocs.io/en/latest/Tutorial/GettingStarted/part_3.html
    # Let us interpret the servers as workers at aa bank, who can see one customer at a time

    import ciw

    N = ciw.create_network(
        arrival_distributions=[ciw.dists.Exponential(rate=0.2)],
        service_distributions=[ciw.dists.Exponential(rate=0.1)],
        number_of_servers=[3]
    )

    ciw.seed(1)

    Q = ciw.Simulation(N)

    Q.simulate_until_max_time(1440)

    recs = Q.get_all_records()

    event_log_from_ciw_recs(ciw_recs_obj=recs, node_name_list=["bank_server"])

    """
    entity_ids = list(set([log.id_number for log in ciw_recs_obj]))

    event_logs = []

    for entity_id in entity_ids:
        entity_tuples = [log for log in ciw_recs_obj if log.id_number==entity_id]

        total_steps = len(entity_tuples)

        # If first entry, record the arrival time
        for i, event in enumerate(entity_tuples):
            if i==0:
                event_logs.append(
                    {'patient': entity_id,
                    'pathway': 'Model',
                    'event_type': 'arrival_departure',
                    'event': 'arrival',
                    'time': event.arrival_date}
                )

            event_logs.append(
            {'patient': entity_id,
             'pathway': 'Model',
             'event_type': 'queue',
             'event': f"{node_name_list[event.node-1]}_wait_begins",
             'time': event.arrival_date
                }
            )

            event_logs.append(
                {'patient': entity_id,
                'pathway': 'Model',
                'event_type': 'resource_use',
                'event': f"{node_name_list[event.node-1]}_begins",
                'time': event.service_start_date,
                'resource_id': event.server_id}
            )

            event_logs.append(
                {'patient': entity_id,
                'pathway': 'Model',
                'event_type': 'resource_use',
                'event': f"{node_name_list[event.node-1]}_ends",
                'time': event.service_end_date,
                'resource_id': event.server_id}
            )


            if i==total_steps-1:
                event_logs.append(
                    {'patient': entity_id,
                    'pathway': 'Model',
                    'event_type': 'arrival_departure',
                    'event': 'depart',
                    'time': event.exit_date}
                )

    return pd.DataFrame(event_logs)

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



import simpy
from contextlib import contextmanager

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

    def __init__(self, env, capacity=float('inf'), init_items=None):
        """
        Initialize the VidigiStore.

        Args:
            env: SimPy environment
            capacity: Maximum capacity of the store
            init_items: Initial items to put in the store
        """
        self.env = env
        self.store = simpy.Store(env, capacity)

        # Initialize with items if provided
        if init_items:
            for item in init_items:
                self.store.put(item)

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
