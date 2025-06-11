'''
CiW Implementation of the 111 call centre
Time units of the simulation model are in minutes.
'''
# Imports

import numpy as np
import pandas as pd
import ciw

# Module level variables, constants, and default values

N_OPERATORS = 13
N_NURSES = 9
MEAN_IAT = 100.0 / 60.0

CALL_LOW = 5.0
CALL_MODE = 7.0
CALL_HIGH = 10.0

NURSE_CALL_LOW = 10.0
NURSE_CALL_HIGH = 20.0

CHANCE_CALLBACK = 0.4
RESULTS_COLLECTION_PERIOD = 1000


# Experiment class
class Experiment:
    def __init__(self, n_operators=N_OPERATORS, n_nurses=N_NURSES,
                 mean_iat=MEAN_IAT, call_low=CALL_LOW,
                 call_mode=CALL_MODE, call_high=CALL_HIGH,
                 chance_callback=CHANCE_CALLBACK,
                 nurse_call_low=NURSE_CALL_LOW,
                 nurse_call_high=NURSE_CALL_HIGH,
                 random_seed=None):
        self.n_operators = n_operators
        self.n_nurses = n_nurses

        self.arrival_dist = ciw.dists.Exponential(mean_iat)
        self.call_dist = ciw.dists.Triangular(call_low, call_mode, call_high)
        self.nurse_dist = ciw.dists.Uniform(nurse_call_low, nurse_call_high)

        self.chance_callback = chance_callback

        self.init_results_variables()

    def init_results_variables(self):
        self.results = {
            'waiting_times': [],
            'total_call_duration': 0.0,
            'nurse_waiting_times': [],
            'total_nurse_call_duration': 0.0,
        }


# Model code

def get_model(args):
    '''
    Build a CiW model using the arguments provided.
    '''
    network = ciw.create_network(
        arrival_distributions=[args.arrival_dist, None],
        service_distributions=[args.call_dist, args.nurse_dist],
        routing=[[0.0, args.chance_callback], [0.0, 0.0]],
        number_of_servers=[args.n_operators, args.n_nurses]
    )
    return network


# Model wrapper functions

def single_run(experiment, rc_period=RESULTS_COLLECTION_PERIOD, random_seed=None):
    run_results = {}

    ciw.seed(random_seed)

    model = get_model(experiment)

    sim_engine = ciw.Simulation(model)

    sim_engine.simulate_until_max_time(rc_period)

    recs = sim_engine.get_all_records()

    op_servicetimes = [r.service_time for r in recs if r.node == 1]
    nurse_servicetimes = [r.service_time for r in recs if r.node == 2]

    op_waits = [r.waiting_time for r in recs if r.node == 1]
    nurse_waits = [r.waiting_time for r in recs if r.node == 2]

    run_results['01_mean_waiting_time'] = np.mean(op_waits)
    run_results['02_operator_util'] = (
        sum(op_servicetimes) / (rc_period * experiment.n_operators)
    ) * 100.0
    run_results['03_mean_nurse_waiting_time'] = np.mean(nurse_waits)
    run_results['04_nurse_util'] = (
        sum(nurse_servicetimes) / (rc_period * experiment.n_nurses)
    ) * 100.0

    return run_results, recs


def multiple_replications(experiment, rc_period=RESULTS_COLLECTION_PERIOD, n_reps=5):
    results = []
    logs = []

    for rep in range(n_reps):
        run_result, log = single_run(experiment, rc_period)
        results.append(run_result)
        logs.append(log)

    df_results = pd.DataFrame(results)
    df_results.index = np.arange(1, len(df_results) + 1)
    df_results.index.name = 'rep'

    return df_results, logs
