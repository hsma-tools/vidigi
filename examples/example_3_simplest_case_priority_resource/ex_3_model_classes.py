import random
import numpy as np
import pandas as pd
import simpy
from sim_tools.distributions import Exponential, Lognormal
from vidigi.resources import populate_store, VidigiPriorityStoreLegacy as VidigiPriorityStore

class g:
    '''
    Create a scenario to parameterise the simulation model

    Parameters:
    -----------
    random_number_set: int, optional (default=DEFAULT_RNG_SET)
        Set to control the initial seeds of each stream of pseudo
        random numbers used in the model.

    n_cubicles: int
        The number of treatment cubicles

    trauma_treat_mean: float
        Mean of the trauma cubicle treatment distribution (Lognormal)

    trauma_treat_var: float
        Variance of the trauma cubicle treatment distribution (Lognormal)

        arrival_rate: float
        Set the mean of the exponential distribution that is used to sample the
        inter-arrival time of patients

    '''
    random_number_set = 42

    n_cubicles = 4
    trauma_treat_mean = 40
    trauma_treat_var = 5

    arrival_rate = 5
    sim_duration = 600
    number_of_runs = 100

class Patient:
    '''
    Class defining details for a patient entity
    '''
    def __init__(self, p_id):
        '''
        Constructor method

        Params:
        -----
        identifier: int
            a numeric identifier for the patient.
        '''
        self.identifier = p_id
        self.arrival = -np.inf
        self.wait_treat = -np.inf
        self.total_time = -np.inf
        self.treat_duration = -np.inf

        # Randomly initialise a patient priority value
        # Lower values will be prioritised - so priority 1 will be seen before priority 2
        if random.uniform(0, 1) < 0.2:
            self.priority = 1
        else:
            self.priority = 2

class Model:
    '''
    Simulates the simplest minor treatment process for a patient

    1. Arrive
    2. Examined/treated by nurse when one available
    3. Discharged
    '''
    # Constructor to set up the model for a run.  We pass in a run number when
    # we create a new model.
    def __init__(self, run_number):
        # Create a SimPy environment in which everything will live
        self.env = simpy.Environment()

        self.event_log = []

        # Create a patient counter (which we'll use as a patient ID)
        self.patient_counter = 0

        self.patients = []

        # Create our resources
        self.init_resources()

        # Store the passed in run number
        self.run_number = run_number

        # Create a new Pandas DataFrame that will store some results against
        # the patient ID (which we'll use as the index).
        self.results_df = pd.DataFrame()
        self.results_df["Patient ID"] = [1]
        self.results_df["Queue Time Cubicle"] = [0.0]
        self.results_df["Time with Nurse"] = [0.0]
        self.results_df.set_index("Patient ID", inplace=True)

        # Create an attribute to store the mean queuing times across this run of
        # the model
        self.mean_q_time_cubicle = 0

        self.patient_inter_arrival_dist = Exponential(mean = g.arrival_rate,
                                                      random_seed = self.run_number*g.random_number_set)
        self.treat_dist = Lognormal(mean = g.trauma_treat_mean,
                                    stdev = g.trauma_treat_var,
                                    random_seed = self.run_number*g.random_number_set)

    def init_resources(self):
        '''
        Init the number of resources
        and store in the arguments container object

        Resource list:
            1. Nurses/treatment bays (same thing in this model)

        '''
        self.treatment_cubicles = VidigiPriorityStore(self.env)

        populate_store(num_resources=g.n_cubicles,
                       simpy_store=self.treatment_cubicles,
                       sim_env=self.env)

    # A generator function that represents the DES generator for patient arrivals
    def generator_patient_arrivals(self):
        # Use an infinite loop here to keep doing this indefinitely while the simulation runs
        while True:
            # Increment the patient counter by 1 (first patient will have an ID of 1)
            self.patient_counter += 1

            p = Patient(self.patient_counter)

            # Store patient in list for later easy access
            self.patients.append(p)

            # Tell SimPy to start up the attend_clinic generator function with this patient
            # (the generator function that will model the patient's journey through the system)
            self.env.process(self.attend_clinic(p))

            # Randomly sample the time to the next patient arriving
            sampled_inter = self.patient_inter_arrival_dist.sample()

            # Freeze this instance of this function in place until the inter-arrival time
            # sampled above has elapsed
            yield self.env.timeout(sampled_inter)

    def attend_clinic(self, patient):
        """
        A generator function that represents the pathway for a patient going through the clinic.

        The patient object is passed in to the generator function so we can extract information
        from / record information to it
        """
        self.arrival = self.env.now

        # ===== LOGGING FOR VIDIGI ANIMATION  ===== #
        self.event_log.append(
            {'patient': patient.identifier,
             'pathway': patient.priority,
             'event_type': 'arrival_departure',
             'event': 'arrival',
             'time': self.env.now}
        )
        # ========================================= #

        # request examination resource
        start_wait = self.env.now

        # ===== LOGGING FOR VIDIGI ANIMATION  ===== #
        self.event_log.append(
            {'patient': patient.identifier,
             'pathway': patient.priority,
             'event': 'treatment_wait_begins',
             'event_type': 'queue',
             'time': self.env.now}
        )
        # ========================================= #

        # Seize a treatment resource when available
        # Note that we must pass in the patient priority
        treatment_resource = yield self.treatment_cubicles.get(priority=patient.priority)

        # record the waiting time for registration
        self.wait_treat = self.env.now - start_wait

        # ===== LOGGING FOR VIDIGI ANIMATION  ===== #
        self.event_log.append(
            {'patient': patient.identifier,
                'pathway': patient.priority,
                'event': 'treatment_begins',
                'event_type': 'resource_use',
                'time': self.env.now,
                'resource_id': treatment_resource.id_attribute
                }
        )
        # ========================================= #

        # sample treatment duration
        self.treat_duration = self.treat_dist.sample()
        yield self.env.timeout(self.treat_duration)

        # ===== LOGGING FOR VIDIGI ANIMATION  ===== #
        self.event_log.append(
            {'patient': patient.identifier,
                'pathway': patient.priority,
                'event': 'treatment_complete',
                'event_type': 'resource_use_end',
                'time': self.env.now,
                'resource_id': treatment_resource.id_attribute}
        )
        # ========================================= #

        # Resource is no longer in use, so put it back in
        self.treatment_cubicles.put(treatment_resource)

        # total time in system
        self.total_time = self.env.now - self.arrival

        # ===== LOGGING FOR VIDIGI ANIMATION  ===== #
        self.event_log.append(
            {'patient': patient.identifier,
            'pathway': patient.priority,
            'event': 'depart',
            'event_type': 'arrival_departure',
            'time': self.env.now}
        )
        # ========================================= #


    # This method calculates results over a single run.  Here we just calculate
    # a mean, but in real world models you'd probably want to calculate more.
    def calculate_run_results(self):
        # Take the mean of the queuing times across patients in this run of the
        # model.
        self.mean_q_time_cubicle = self.results_df["Queue Time Cubicle"].mean()

    # The run method starts up the DES entity generators, runs the simulation,
    # and in turns calls anything we need to generate results for the run
    def run(self):
        # Start up our DES entity generators that create new patients.  We've
        # only got one in this model, but we'd need to do this for each one if
        # we had multiple generators.
        self.env.process(self.generator_patient_arrivals())

        # Run the model for the duration specified in g class
        self.env.run(until=g.sim_duration)

        # Now the simulation run has finished, call the method that calculates
        # run results
        self.calculate_run_results()

        self.event_log = pd.DataFrame(self.event_log)

        self.event_log["run"] = self.run_number

        return {'results': self.results_df, 'event_log': self.event_log}

# Class representing a Trial for our simulation - a batch of simulation runs.
class Trial:
    # The constructor sets up a pandas dataframe that will store the key
    # results from each run against run number, with run number as the index.
    def  __init__(self):
        self.df_trial_results = pd.DataFrame()
        self.df_trial_results["Run Number"] = [0]
        self.df_trial_results["Arrivals"] = [0]
        self.df_trial_results["Mean Queue Time Cubicle"] = [0.0]
        self.df_trial_results.set_index("Run Number", inplace=True)

        self.all_event_logs = []

    # Method to run a trial
    def run_trial(self):
        print(f"{g.n_cubicles} nurses")
        print("") ## Print a blank line

        # Run the simulation for the number of runs specified in g class.
        # For each run, we create a new instance of the Model class and call its
        # run method, which sets everything else in motion.  Once the run has
        # completed, we grab out the stored run results (just mean queuing time
        # here) and store it against the run number in the trial results
        # dataframe.
        for run in range(g.number_of_runs):
            random.seed(run)

            my_model = Model(run)
            model_outputs = my_model.run()
            patient_level_results = model_outputs["results"]
            event_log = model_outputs["event_log"]

            self.df_trial_results.loc[run] = [
                len(patient_level_results),
                my_model.mean_q_time_cubicle,
            ]

            # print(event_log)

            self.all_event_logs.append(event_log)

        self.all_event_logs = pd.concat(self.all_event_logs)
