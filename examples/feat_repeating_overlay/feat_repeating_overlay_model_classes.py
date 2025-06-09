import random
import numpy as np
import pandas as pd
import simpy
from sim_tools.distributions import Exponential, Lognormal
from vidigi.resources import VidigiPriorityStore


# Class to store global parameter values.  We don't create an instance of this
# class - we just refer to the class blueprint itself to access the numbers
# inside.
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

    sim_duration: int
        The number of time units the simulation will run for

    number_of_runs: int
        The number of times the simulation will be run with different random number streams

    '''
    random_number_set = 42

    n_cubicles = 4
    trauma_treat_mean = 40
    trauma_treat_var = 5

    unav_time = 60 * 12 # 12 hours
    unav_freq = 60 * 12 # every 12 hours

    arrival_rate = 5

    sim_duration = 600
    number_of_runs = 100

# Class representing patients coming in to the clinic.
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

class OvernightClosure:
    def __init__(self, p_id):
        '''
        Constructor method

        Params:
        -----
        identifier: int
            a numeric identifier for the patient.
        '''
        self.identifier = "closure"

# Class representing our model of the clinic.
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

        self.waiting_patients = []

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
        self.treatment_cubicles = VidigiPriorityStore(self.env, num_resources=g.n_cubicles)

    # Generator function to obstruct all resources at specified intervals
    # for specified amounts of time
    def close_clinic_overnight(self):
        while True:
            # Wait for the defined frequency period (e.g. 12 hours = 720 mins)
            yield self.env.timeout(g.unav_freq)

            closing_time = self.env.now

            # Determine how far past the *ideal* closing time we are
            ideal_closing_time = round(closing_time / g.unav_freq) * g.unav_freq
            overrun = max(0, closing_time - ideal_closing_time)

            adjusted_unav_time = max(0, g.unav_time - overrun)
            print(f"Closing time: {closing_time}, Overrun: {overrun}, Adjusted unavailability: {adjusted_unav_time}")

            # Grab the resource at priority -1 so it waits for any in-flight patients
            with self.treatment_cubicles.request(priority=-1) as req:
                treatment_resource = yield req

                self.event_log.append({
                    'patient': "overnight_closure",
                    'pathway': 'Simplest',
                    'event': 'treatment_begins',
                    'event_type': 'resource_use',
                    'time': self.env.now,
                    'resource_id': treatment_resource.id_attribute
                })

                # Treatment bay remains unavailable for the adjusted unavailability period
                yield self.env.timeout(adjusted_unav_time)

    # A generator function that represents the DES generator for patient arrivals
    def generator_patient_arrivals(self):
        while True:
            # Sample inter-arrival time
            sampled_inter = self.patient_inter_arrival_dist.sample()
            next_arrival_time = self.env.now + sampled_inter

            # Calculate time until next closure and reopening
            time_since_last_closure = self.env.now % g.unav_freq
            time_until_closing = g.unav_freq - time_since_last_closure

            unav_start = self.env.now + time_until_closing

            # Allow people to start arriving again before the clinic opens
            unav_end = unav_start + g.unav_time

            # If the next patient would arrive during the closure period, skip forward
            if next_arrival_time >= unav_start and next_arrival_time < unav_end:
                yield self.env.timeout(unav_end - self.env.now)
                continue  # Restart loop after skipping closure period

            # Wait for inter-arrival time before generating patient
            yield self.env.timeout(sampled_inter)

            self.patient_counter += 1
            p = Patient(self.patient_counter)
            self.patients.append(p)
            self.env.process(self.attend_clinic(p))

    # A generator function that represents the pathway for a patient going
    # through the clinic.
    # The patient object is passed in to the generator function so we can
    # extract information from / record information to it
    def attend_clinic(self, patient):
        self.arrival = self.env.now
        self.event_log.append(
            {'patient': patient.identifier,
             'pathway': 'Simplest',
             'event_type': 'arrival_departure',
             'event': 'arrival',
             'time': self.env.now}
        )

        # request examination resource
        start_wait = self.env.now
        self.event_log.append(
            {'patient': patient.identifier,
             'pathway': 'Simplest',
             'event': 'treatment_wait_begins',
             'event_type': 'queue',
             'time': self.env.now}
        )

        with self.treatment_cubicles.request(priority=1) as req:
            # Seize a treatment resource when available
            current_time = self.env.now
            time_since_last_closure = current_time % g.unav_freq
            time_until_closing = g.unav_freq - time_since_last_closure

            result_of_queue = (yield req | self.env.timeout(time_until_closing))

            if req in result_of_queue:

                # record the waiting time for registration
                self.wait_treat = self.env.now - start_wait
                self.event_log.append(
                    {'patient': patient.identifier,
                        'pathway': 'Simplest',
                        'event': 'treatment_begins',
                        'event_type': 'resource_use',
                        'time': self.env.now,
                        'resource_id': result_of_queue[req].id_attribute
                        }
                )

                # sample treatment duration
                self.treat_duration = self.treat_dist.sample()
                yield self.env.timeout(self.treat_duration)

                self.event_log.append(
                    {'patient': patient.identifier,
                        'pathway': 'Simplest',
                        'event': 'treatment_complete',
                        'event_type': 'resource_use_end',
                        'time': self.env.now,
                        'resource_id': result_of_queue[req].id_attribute}
                )

        # total time in system
        self.total_time = self.env.now - self.arrival

        self.event_log.append(
            {'patient': patient.identifier,
            'pathway': 'Simplest',
            'event': 'depart',
            'event_type': 'arrival_departure',
            'time': self.env.now}
        )


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

        for i in range(g.n_cubicles):
            self.env.process(self.close_clinic_overnight())

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
