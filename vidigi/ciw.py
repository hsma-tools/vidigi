import pandas as pd

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

        # Sort the events for this entity by service start time
        entity_tuples.sort(key=lambda x: x.service_start_date)

        total_steps = len(entity_tuples)

        # If first entry, record the arrival time
        for i, event in enumerate(entity_tuples):
            if i==0:
                event_logs.append(
                    {'entity_id': entity_id,
                    'pathway': 'Model',
                    'event_type': 'arrival_departure',
                    'event': 'arrival',
                    'time': event.arrival_date}
                )

            event_logs.append(
            {'entity_id': entity_id,
             'pathway': 'Model',
             'event_type': 'queue',
             'event': f"{node_name_list[event.node-1]}_wait_begins",
             'time': event.arrival_date
                }
            )

            event_logs.append(
                {'entity_id': entity_id,
                'pathway': 'Model',
                'event_type': 'resource_use',
                'event': f"{node_name_list[event.node-1]}_begins",
                'time': event.service_start_date,
                'resource_id': event.server_id}
            )

            event_logs.append(
                {'entity_id': entity_id,
                'pathway': 'Model',
                'event_type': 'resource_use_end',
                'event': f"{node_name_list[event.node-1]}_ends",
                'time': event.service_end_date,
                'resource_id': event.server_id}
            )


            if i==total_steps-1:
                event_logs.append(
                    {'entity_id': entity_id,
                    'pathway': 'Model',
                    'event_type': 'arrival_departure',
                    'event': 'depart',
                    'time': event.exit_date}
                )

    return pd.DataFrame(event_logs)
