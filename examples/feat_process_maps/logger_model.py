import simpy
import numpy as np
import pandas as pd
from vidigi.logging import EventLogger
from vidigi.resources import VidigiStore
from sim_tools.distributions import Lognormal, Exponential
import random


# Class to store global parameter values.  We don't create an instance of this
# class - we just refer to the class blueprint itself to access the numbers
# inside.
class g:
    """
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

    sim_duration: int
        The number of time units the simulation will run for

    number_of_runs: int
        The number of times the simulation will be run with different random number streams

    """

    random_number_set = 42

    n_cubicles = 4
    trauma_treat_mean = 40
    trauma_treat_var = 5

    arrival_rate = 5

    sim_duration = 600
    number_of_runs = 100


# | code-fold: true
# | code-summary: "Show the patient class code"
class Patient:
    """
    Class defining details for a patient entity
    """

    def __init__(self, p_id):
        """
        Constructor method

        Params:
        -----
        identifier: int
            a numeric identifier for the patient.
        """
        self.id = p_id
        self.arrival = -np.inf
        self.wait_treat = -np.inf
        self.total_time = -np.inf
        self.treat_duration = -np.inf


# Class representing our model of the clinic.
class Model:
    """
    Simulates the simplest minor treatment process for a patient

    1. Arrive
    2. Examined/treated by nurse when one available
    3. Discharged
    """

    # Constructor to set up the model for a run.  We pass in a run number when
    # we create a new model.
    def __init__(self, run_number):
        # Create a SimPy environment in which everything will live
        self.env = simpy.Environment()

        # Store the passed in run number
        self.run_number = run_number

        # By passing in the env we've created, the logger will default to the simulation
        # time when populating the time column of our event logs
        self.logger = EventLogger(env=self.env, run_number=self.run_number)

        # Create a patient counter (which we'll use as a patient ID)
        self.patient_counter = 0

        # Create an empty list to hold our patients
        self.patients = []

        # Create our distributions
        self.init_distributions()

        # Create our resources
        self.init_resources()

    def init_distributions(self):
        self.patient_inter_arrival_dist = Exponential(
            mean=g.arrival_rate, random_seed=self.run_number * g.random_number_set
        )

        self.treat_dist = Lognormal(
            mean=g.trauma_treat_mean,
            stdev=g.trauma_treat_var,
            random_seed=self.run_number * g.random_number_set,
        )

    def init_resources(self):
        """
        Init the number of resources

        Resource list:
            1. Nurses/treatment bays (same thing in this model)

        """
        self.treatment_cubicles = VidigiStore(self.env, num_resources=g.n_cubicles, label="treatment_cubicle")

    # A generator function that represents the DES generator for patient
    # arrivals
    def generator_patient_arrivals(self):
        # We use an infinite loop here to keep doing this indefinitely whilst
        # the simulation runs
        while True:
            # Increment the patient counter by 1 (this means our first patient
            # will have an ID of 1)
            self.patient_counter += 1

            # Create a new patient - an instance of the Patient Class we
            # defined above.  Remember, we pass in the ID when creating a
            # patient - so here we pass the patient counter to use as the ID.
            p = Patient(self.patient_counter)

            # Store patient in list for later easy access
            self.patients.append(p)

            # Tell SimPy to start up the attend_clinic generator function with
            # this patient (the generator function that will model the
            # patient's journey through the system)
            self.env.process(self.attend_clinic(p))

            # Randomly sample the time to the next patient arriving.  Here, we
            # sample from an exponential distribution (common for inter-arrival
            # times), and pass in a lambda value of 1 / mean.  The mean
            # inter-arrival time is stored in the g class.
            sampled_inter = self.patient_inter_arrival_dist.sample()

            # Freeze this instance of this function in place until the
            # inter-arrival time we sampled above has elapsed.  Note - time in
            # SimPy progresses in "Time Units", which can represent anything
            # you like (just make sure you're consistent within the model)
            yield self.env.timeout(sampled_inter)

    # A generator function that represents the pathway for a patient going
    # through the clinic.
    # The patient object is passed in to the generator function so we can
    # extract information from / record information to it
    def attend_clinic(self, patient):
        self.logger.log_arrival(entity_id=patient.id)

        self.arrival = self.env.now

        self.logger.log_queue(entity_id=patient.id, event="treatment_wait_begins")

        with self.treatment_cubicles.request() as req:
            # Seize a treatment resource when available
            treatment_resource = yield req

            self.logger.log_resource_use_start(
                entity_id=patient.id,
                event="treatment_begins",
                resource_id=treatment_resource.id_attribute,
            )

            # sample treatment duration
            self.treat_duration = self.treat_dist.sample()
            yield self.env.timeout(self.treat_duration)

            self.logger.log_resource_use_end(
                entity_id=patient.id,
                event="treatment_complete",
                resource_id=treatment_resource.id_attribute,
            )

        # total time in system
        self.total_time = self.env.now - self.arrival

        self.logger.log_departure(entity_id=patient.id)

    # The run method starts up the DES entity generators, runs the simulation,
    # and in turns calls anything we need to generate results for the run
    def run(self):
        # Start up our DES entity generators that create new patients.  We've
        # only got one in this model, but we'd need to do this for each one if
        # we had multiple generators.
        self.env.process(self.generator_patient_arrivals())

        # Run the model for the duration specified in g class
        self.env.run(until=g.sim_duration)


class Trial:
    def __init__(self):
        self.all_event_logs = []
        self.trial_results_df = pd.DataFrame()

        self.run_trial()

    # Method to run a trial
    def run_trial(self):
        print(f"{g.n_cubicles} nurses")
        print("")  ## Print a blank line

        # Run the simulation for the number of runs specified in g class.
        # For each run, we create a new instance of the Model class and call its
        # run method, which sets everything else in motion.  Once the run has
        # completed, we grab out the stored run results (just mean queuing time
        # here) and store it against the run number in the trial results
        # dataframe.
        for run in range(1, g.number_of_runs + 1):
            random.seed(run)

            my_model = Model(run)
            my_model.run()

            self.all_event_logs.append(my_model.logger)

        self.trial_results = pd.concat(
            [run_results.to_dataframe() for run_results in self.all_event_logs]
        )
