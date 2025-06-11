import pandas as pd
from sim_tools.distributions import Exponential, Lognormal, Uniform
from vidigi.resources import VidigiStore
from vidigi.logging import EventLogger
import simpy

class g:
    # Simulation Duration Parameters (time units are hours)
    sim_duration_weeks = 52
    sim_duration = sim_duration_weeks * 7 * 24
    warm_up_weeks = 3
    warm_up_period = warm_up_weeks * 7 * 24

    # Resource Numbers
    number_of_beds_ash = 18
    number_of_beds_oak = 5
    number_of_beds_maple = 8

    # Inter-Arrival Times (in hours)
    patient_inter_arrival_time = 4

    # Mean Activity Times (in hours)
    mean_time_in_bed = 72
    sd_time_in_bed = 18

    # Simulation and Trial Parameters
    number_of_runs = 100  # Number of simulation runs in a trial [5, 6, 8, 19]


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
        self.id = p_id

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
            mean = g.patient_inter_arrival_time,
            random_seed = (abs(self.run_number) + 1) * 1
            )

        self.treat_dist = Lognormal(
            mean = g.mean_time_in_bed,
            stdev = g.sd_time_in_bed,
            random_seed = (abs(self.run_number) + 1) * 2
            )

        self.ward_choice_dist = Uniform(
            low=1,
            high=4,
            random_seed = (abs(self.run_number) + 1) * 2
            )

    def init_resources(self):
        '''
        Init the number of resources

        Resource list:
            1. Nurses/treatment bays (same thing in this model)

        '''
        self.beds_ward_ash = VidigiStore(self.env, num_resources=g.number_of_beds_ash)
        self.beds_ward_oak = VidigiStore(self.env, num_resources=g.number_of_beds_oak)
        self.beds_ward_maple = VidigiStore(self.env, num_resources=g.number_of_beds_maple)

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
            self.env.process(self.attend_ward(p))

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
    def attend_ward(self, patient):
        self.logger.log_arrival(
            entity_id=patient.id
            )

        self.logger.log_queue(
            entity_id=patient.id,
            event="bed_wait_begins"
            )

        ward_choice = int(self.ward_choice_dist.sample())

        if ward_choice == 1:
            ward="ash"
            beds = self.beds_ward_ash
        elif ward_choice == 2:
            ward="oak"
            beds = self.beds_ward_oak
        else:
            ward="maple"
            beds = self.beds_ward_maple

        with beds.request() as req:

            # Seize a treatment resource when available
            bed_resource = yield req

            self.logger.log_resource_use_start(
                entity_id=patient.id,
                event=f"{ward}_stay_begins",
                resource_id=bed_resource.id_attribute
                )

            # sample treatment duration
            yield self.env.timeout(self.treat_dist.sample())

            self.logger.log_resource_use_end(
                entity_id=patient.id,
                event=f"{ward}_stay_complete",
                resource_id=bed_resource.id_attribute
                )

        self.logger.log_departure(
            entity_id=patient.id
            )

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
    def  __init__(self):
        self.all_event_logs = []
        self.trial_results_df = pd.DataFrame()

        self.run_trial()

    # Method to run a trial
    def run_trial(self):
        # Run the simulation for the number of runs specified in g class.
        # For each run, we create a new instance of the Model class and call its
        # run method, which sets everything else in motion.  Once the run has
        # completed, we grab out the stored run results (just mean queuing time
        # here) and store it against the run number in the trial results
        # dataframe.
        for run in range(1, g.number_of_runs + 1):
            my_model = Model(run)
            my_model.run()

            self.all_event_logs.append(my_model.logger)

        self.trial_results = pd.concat(
            [run_results.to_dataframe() for run_results in self.all_event_logs]
            )
