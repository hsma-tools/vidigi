import simpy

class CustomResource(simpy.Resource):
    def __init__(self, env, capacity, id_attribute=None):
        super().__init__(env, capacity)
        self.id_attribute = id_attribute

    def request(self, *args, **kwargs):
        # Add logic to handle the ID attribute when a request is made
        # For example, you can assign an ID to the requester
        # self.id_attribute = assign_id_logic()
        return super().request(*args, **kwargs)

    def release(self, *args, **kwargs):
        # Add logic to handle the ID attribute when a release is made
        # For example, you can reset the ID attribute
        # reset_id_logic(self.id_attribute)
        return super().release(*args, **kwargs)

def populate_store(num_resources, simpy_store, sim_env):
    for i in range(num_resources):
        simpy_store.put(
            CustomResource(
                sim_env,
                capacity=1,
                id_attribute = i+1)
            )
