import simpy

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

    Methods
    -------
    request(*args, **kwargs)
        Request the resource. Can be overridden to include custom logic for ID assignment.
    release(*args, **kwargs)
        Release the resource. Can be overridden to include custom logic for ID handling.

    Notes
    -----
    This class inherits from simpy.Resource and overrides the request and release methods
    to allow for custom handling of the id_attribute. The actual implementation of ID
    assignment or reset logic should be added by the user as needed.

    Examples
    --------
    >>> env = simpy.Environment()
    >>> custom_resource = CustomResource(env, capacity=1, id_attribute="Resource_1")
    >>> def process(env, resource):
    ...     with resource.request() as req:
    ...         yield req
    ...         print(f"Using resource with ID: {resource.id_attribute}")
    ...         yield env.timeout(1)
    >>> env.process(process(env, custom_resource))
    >>> env.run()
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
    Populate a SimPy Store with CustomResource objects.

    This function creates a specified number of CustomResource objects and adds them to a SimPy Store.
    Each CustomResource is initialized with a capacity of 1 and a unique ID attribute.

    Parameters
    ----------
    num_resources : int
        The number of CustomResource objects to create and add to the store.
    simpy_store : simpy.Store
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
