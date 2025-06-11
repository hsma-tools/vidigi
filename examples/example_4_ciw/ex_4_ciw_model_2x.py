'''
CiW Implementation of the 111 call centre

Time units of the simulation model are in minutes.
'''
# Imports

import numpy as np
import pandas as pd
import ciw

# Module level variables, constants, and default values

# default resources
N_OPERATORS = 13

# number of nurses available
N_NURSES = 9

# default lambda for arrival distribution
MEAN_IAT = 100.0 / 60.0

## default service time parameters (triangular)
CALL_LOW = 5.0
CALL_MODE = 7.0
CALL_HIGH = 10.0

# nurse distribution parameters
NURSE_CALL_LOW = 10.0
NURSE_CALL_HIGH = 20.0

CHANCE_CALLBACK = 0.4

# run variables
RESULTS_COLLECTION_PERIOD = 1000


# Experiment class
class Experiment:
    '''
    Parameter class for 111 simulation model
    '''
    def __init__(self, n_operators=N_OPERATORS, n_nurses=N_NURSES,
                 mean_iat=MEAN_IAT, call_low=CALL_LOW,
                 call_mode=CALL_MODE, call_high=CALL_HIGH,
                 chance_callback=CHANCE_CALLBACK,
                 nurse_call_low=NURSE_CALL_LOW,
                 nurse_call_high=NURSE_CALL_HIGH,
                 random_seed=None):
        '''
        The init method sets up our defaults.
        '''
        self.n_operators = n_operators

        # store the number of nurses in the experiment
        self.n_nurses = n_nurses

        # arrival distribution
        self.arrival_dist = ciw.dists.Exponential(mean_iat)

        # call duration
        self.call_dist = ciw.dists.Triangular(call_low,
                                              call_mode, call_high)

        # duration of call with nurse
        self.nurse_dist = ciw.dists.Uniform(nurse_call_low,
                                            nurse_call_high)

        # prob of call back
        self.chance_callback = chance_callback

        # initialise results to zero
        self.init_results_variables()

    def init_results_variables(self):
        '''
        Initialise all of the experiment variables used in results
        collection.  This method is called at the start of each run
        of the model
        '''
        # variable used to store results of experiment
        self.results = {}
        self.results['waiting_times'] = []

        # total operator usage time for utilisation calculation.
        self.results['total_call_duration'] = 0.0

        # nurse sub process results collection
        self.results['nurse_waiting_times'] = []
        self.results['total_nurse_call_duration'] = 0.0


# Model code

def get_model(args):
    '''
    Build a CiW model using the arguments provided.

    Params:
    -----
    args: Experiment
        container class for Experiment. Contains the model inputs/params

    Returns:
    --------
    ciw.network.Network
    '''
    model = ciw.create_network(arrival_distributions=[args.arrival_dist,
                                                      ciw.dists.NoArrivals()],
                               service_distributions=[args.call_dist,
                                                      args.nurse_dist],
                               routing=[[0.0, args.chance_callback],
                                        [0.0, 0.0]],
                               number_of_servers=[args.n_operators,
                                                  args.n_nurses])
    return model


# Model wrapper functions

def single_run(experiment,
               rc_period=RESULTS_COLLECTION_PERIOD,
               random_seed=None):
    '''
    Conduct a single run of the simulation model.

    Params:
    ------
    args: Scenario
        Parameter container

    random_seed: int
        Random seed to control simulation run.
    '''

    # results dictionary.  Each KPI is a new entry.
    run_results = {}

    # random seed
    ciw.seed(random_seed)

    # parameterise model
    model = get_model(experiment)

    # simulation engine
    sim_engine = ciw.Simulation(model)

    # run the model
    sim_engine.simulate_until_max_time(rc_period)

    # return processed results for run.

    # get all results
    recs = sim_engine.get_all_records()

    # operator service times
    op_servicetimes = [r.service_time for r in recs if r.node==1]
    # nurse service times
    nurse_servicetimes = [r.service_time for r in recs if r.node==2]

    # operator and nurse waiting times
    op_waits = [r.waiting_time for r in recs if r.node==1]
    nurse_waits = [r.waiting_time for r in recs if r.node==2]

    # mean measures
    run_results['01_mean_waiting_time'] = np.mean(op_waits)

    # end of run results: calculate mean operator utilisation
    run_results['02_operator_util'] = \
        (sum(op_servicetimes) / (rc_period * experiment.n_operators)) * 100.0

    # end of run results: nurse waiting time
    run_results['03_mean_nurse_waiting_time'] = np.mean(nurse_waits)

    # end of run results: calculate mean nurse utilisation
    run_results['04_nurse_util'] = \
        (sum(nurse_servicetimes) / (rc_period * experiment.n_nurses)) * 100.0

    # return the results from the run of the model
    return run_results, recs

def multiple_replications(experiment,
                          rc_period=RESULTS_COLLECTION_PERIOD,
                          n_reps=5):
    '''
    Perform multiple replications of the model.

    Params:
    ------
    experiment: Experiment
        The experiment/paramaters to use with model

    rc_period: float, optional (default=DEFAULT_RESULTS_COLLECTION_PERIOD)
        results collection period.
        the number of minutes to run the model to collect results

    n_reps: int, optional (default=5)
        Number of independent replications to run.

    Returns:
    --------
    pandas.DataFrame
    '''

    # loop over single run to generate results dicts in a python list.
    results = [single_run(experiment, rc_period)[0] for rep in range(n_reps)]
    logs = [single_run(experiment, rc_period)[1] for rep in range(n_reps)]

    # format and return results in a dataframe
    df_results = pd.DataFrame(results)
    df_results.index = np.arange(1, len(df_results)+1)
    df_results.index.name = 'rep'
    return df_results, logs
