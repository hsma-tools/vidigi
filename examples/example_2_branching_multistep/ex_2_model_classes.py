import random
import numpy as np
import pandas as pd
import simpy
from sim_tools.distributions import Exponential, Lognormal, Uniform, Normal, Bernoulli
from vidigi.utils import populate_store
from examples.simulation_utility_functions import trace


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

    n_triage: int
        The number of triage cubicles

    n_reg: int
        The number of registration clerks

    n_exam: int
        The number of examination rooms

    n_trauma: int
        The number of trauma bays for stablisation

    n_cubicles_non_trauma_treat: int
        The number of non-trauma treatment cubicles

    n_cubicles_trauma_treat: int
        The number of trauma treatment cubicles

    triage_mean: float
        Mean duration of the triage distribution (Exponential)

    reg_mean: float
        Mean duration of the registration distribution (Lognormal)

    reg_var: float
        Variance of the registration distribution (Lognormal)

    exam_mean: float
        Mean of the examination distribution (Normal)

    exam_var: float
        Variance of the examination distribution (Normal)

    trauma_mean: float
        Mean of the trauma stabilisation distribution (Exponential)

    trauma_treat_mean: float
        Mean of the trauma cubicle treatment distribution (Lognormal)

    trauma_treat_var: float
        Variance of the trauma cubicle treatment distribution (Lognormal)

    non_trauma_treat_mean: float
        Mean of the non trauma treatment distribution

    non_trauma_treat_var: float
        Variance of the non trauma treatment distribution

    non_trauma_treat_p: float
        Probability non trauma patient requires treatment

    prob_trauma: float
        probability that a new arrival is a trauma patient.
    '''
    random_number_set = 42

    n_triage=2
    n_reg=2
    n_exam=3
    n_trauma=4
    n_cubicles_non_trauma_treat=4
    n_cubicles_trauma_treat=5

    triage_mean=6
    reg_mean=8
    reg_var=2
    exam_mean=16
    exam_var=3
    trauma_mean=90
    trauma_treat_mean=30
    trauma_treat_var=4
    non_trauma_treat_mean=13.3
    non_trauma_treat_var=2

    non_trauma_treat_p=0.6
    prob_trauma=0.12

    arrival_df="ed_arrivals.csv"

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

        # Time of arrival in model/at centre
        self.arrival = -np.inf
        # Total time in pathway
        self.total_time = -np.inf

        # Shared waits
        self.wait_triage = -np.inf
        self.wait_reg = -np.inf
        self.wait_treat = -np.inf
        # Non-trauma pathway - examination wait
        self.wait_exam = -np.inf
        # Trauma pathway - stabilisation wait
        self.wait_trauma = -np.inf

        # Shared durations
        self.triage_duration = -np.inf
        self.reg_duration = -np.inf
        self.treat_duration = -np.inf

        # Non-trauma pathway - examination duration
        self.exam_duration = -np.inf
        # Trauma pathway - stabilisation duration
        self.trauma_duration = -np.inf


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

        self.trauma_patients = []
        self.non_trauma_patients = []

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

        # create distributions

        # Triage duration
        self.triage_dist = Exponential(g.triage_mean,
                                       random_seed=self.run_number*g.random_number_set)

        # Registration duration (non-trauma only)
        self.reg_dist = Lognormal(g.reg_mean,
                                  np.sqrt(g.reg_var),
                                  random_seed=self.run_number*g.random_number_set)

        # Evaluation (non-trauma only)
        self.exam_dist = Normal(g.exam_mean,
                                np.sqrt(g.exam_var),
                                random_seed=self.run_number*g.random_number_set)

        # Trauma/stablisation duration (trauma only)
        self.trauma_dist = Exponential(g.trauma_mean,
                                       random_seed=self.run_number*g.random_number_set)

        # Non-trauma treatment
        self.nt_treat_dist = Lognormal(g.non_trauma_treat_mean,
                                       np.sqrt(g.non_trauma_treat_var),
                                       random_seed=self.run_number*g.random_number_set)

        # treatment of trauma patients
        self.treat_dist = Lognormal(g.trauma_treat_mean,
                                    np.sqrt(g.non_trauma_treat_var),
                                    random_seed=self.run_number*g.random_number_set)

        # probability of non-trauma patient requiring treatment
        self.nt_p_treat_dist = Bernoulli(g.non_trauma_treat_p,
                                         random_seed=self.run_number*g.random_number_set)

        # probability of non-trauma versus trauma patient
        self.p_trauma_dist = Bernoulli(g.prob_trauma,
                                       random_seed=self.run_number*g.random_number_set)

        # init sampling for non-stationary poisson process
        self.init_nspp()

    def init_nspp(self):

        # read arrival profile
        self.arrivals = pd.read_csv(g.arrival_df)  # pylint: disable=attribute-defined-outside-init
        self.arrivals['mean_iat'] = 60 / self.arrivals['arrival_rate']

        # maximum arrival rate (smallest time between arrivals)
        self.lambda_max = self.arrivals['arrival_rate'].max()  # pylint: disable=attribute-defined-outside-init

        # thinning exponential
        self.arrival_dist = Exponential(60.0 / self.lambda_max,  # pylint: disable=attribute-defined-outside-init
                                            random_seed=self.run_number*g.random_number_set)

        # thinning uniform rng
        self.thinning_rng = Uniform(low=0.0, high=1.0,  # pylint: disable=attribute-defined-outside-init
                                    random_seed=self.run_number*g.random_number_set)


    def init_resources(self):
        '''
        Init the number of resources
        and store in the arguments container object

        Resource list:
            1. Nurses/treatment bays (same thing in this model)

        '''
        # Shared Resources
        self.triage_cubicles = simpy.Store(self.env)
        populate_store(num_resources=g.n_triage,
                simpy_store=self.triage_cubicles,
                sim_env=self.env)

        self.registration_cubicles = simpy.Store(self.env)
        populate_store(num_resources=g.n_reg,
                       simpy_store=self.registration_cubicles,
                       sim_env=self.env)

        # Non-trauma
        self.exam_cubicles = simpy.Store(self.env)
        populate_store(num_resources=g.n_exam,
                       simpy_store=self.exam_cubicles,
                       sim_env=self.env)

        self.non_trauma_treatment_cubicles = simpy.Store(self.env)
        populate_store(num_resources=g.n_cubicles_non_trauma_treat,
                       simpy_store=self.non_trauma_treatment_cubicles,
                       sim_env=self.env)

        # Trauma
        self.trauma_stabilisation_bays = simpy.Store(self.env)
        populate_store(num_resources=g.n_trauma,
                       simpy_store=self.trauma_stabilisation_bays,
                       sim_env=self.env)

        self.trauma_treatment_cubicles = simpy.Store(self.env)
        populate_store(num_resources=g.n_cubicles_trauma_treat,
                       simpy_store=self.trauma_treatment_cubicles,
                       sim_env=self.env)

    # A generator function that represents the DES generator for patient
    # arrivals
    def generator_patient_arrivals(self):
        # We use an infinite loop here to keep doing this indefinitely whilst
        # the simulation runs
        while True:
            t = int(self.env.now // 60) % self.arrivals.shape[0]
            lambda_t = self.arrivals['arrival_rate'].iloc[t]

            # set to a large number so that at least 1 sample taken!
            u = np.Inf

            interarrival_time = 0.0
            # reject samples if u >= lambda_t / lambda_max
            while u >= (lambda_t / self.lambda_max):
                interarrival_time += self.arrival_dist.sample()
                u = self.thinning_rng.sample()

            # Freeze this instance of this function in place until the
            # inter-arrival time we sampled above has elapsed.  Note - time in
            # SimPy progresses in "Time Units", which can represent anything
            # you like (just make sure you're consistent within the model)
            yield self.env.timeout(interarrival_time)

            # Increment the patient counter by 1 (this means our first patient
            # will have an ID of 1)
            self.patient_counter += 1

            # Create a new patient - an instance of the Patient Class we
            # defined above.  Remember, we pass in the ID when creating a
            # patient - so here we pass the patient counter to use as the ID.
            p = Patient(self.patient_counter)

            trace(f'patient {self.patient_counter} arrives at: {self.env.now:.3f}')
            self.event_log.append(
                {'patient': self.patient_counter,
                 'pathway': 'Shared',
                 'event': 'arrival',
                 'event_type': 'arrival_departure',
                 'time': self.env.now}
            )

            # sample if the patient is trauma or non-trauma
            trauma = self.p_trauma_dist.sample()

            # Tell SimPy to start up the attend_clinic generator function with
            # this patient (the generator function that will model the
            # patient's journey through the system)
            # and store patient in list for later easy access
            if trauma:
                # create and store a trauma patient to update KPIs.
                self.trauma_patients.append(p)
                self.env.process(self.attend_trauma_pathway(p))

            else:
                # create and store a non-trauma patient to update KPIs.
                self.non_trauma_patients.append(p)
                self.env.process(self.attend_non_trauma_pathway(p))

    # A generator function that represents the pathway for a patient going
    # through the clinic.
    # The patient object is passed in to the generator function so we can
    # extract information from / record information to it
    def attend_non_trauma_pathway(self, patient):
        '''
        simulates the non-trauma/minor treatment process for a patient

        1. request and wait for sign-in/triage
        2. patient registration
        3. examination
        4a. percentage discharged
        4b. remaining percentage treatment then discharge
        '''
        # record the time of arrival and entered the triage queue
        patient.arrival = self.env.now
        self.event_log.append(
            {'patient': patient.identifier,
             'pathway': 'Non-Trauma',
             'event_type': 'queue',
             'event': 'triage_wait_begins',
             'time': self.env.now}
        )

        ###################################################
        # request sign-in/triage
        triage_resource = yield self.triage_cubicles.get()

        # record the waiting time for triage
        patient.wait_triage = self.env.now - patient.arrival
        trace(f'patient {patient.identifier} triaged to minors '
                f'{self.env.now:.3f}')
        self.event_log.append(
            {'patient': patient.identifier,
                'pathway': 'Non-Trauma',
                'event_type': 'resource_use',
                'event': 'triage_begins',
                'time': self.env.now,
                'resource_id': triage_resource.id_attribute
                }
        )

        # sample triage duration.
        patient.triage_duration = self.triage_dist.sample()
        yield self.env.timeout(patient.triage_duration)

        trace(f'triage {patient.identifier} complete {self.env.now:.3f}; '
                f'waiting time was {patient.wait_triage:.3f}')
        self.event_log.append(
            {'patient': patient.identifier,
                'pathway': 'Non-Trauma',
                'event_type': 'resource_use_end',
                'event': 'triage_complete',
                'time': self.env.now,
                'resource_id': triage_resource.id_attribute}
        )

        # Resource is no longer in use, so put it back in the store
        self.triage_cubicles.put(triage_resource)
        #########################################################

        # record the time that entered the registration queue
        start_wait = self.env.now
        self.event_log.append(
            {'patient': patient.identifier,
             'pathway': 'Non-Trauma',
             'event_type': 'queue',
             'event': 'MINORS_registration_wait_begins',
             'time': self.env.now}
        )

        #########################################################
        # request registration clerk
        registration_resource = yield self.registration_cubicles.get()

        # record the waiting time for registration
        patient.wait_reg = self.env.now - start_wait
        trace(f'registration of patient {patient.identifier} at '
                f'{self.env.now:.3f}')
        self.event_log.append(
            {'patient': patient.identifier,
                'pathway': 'Non-Trauma',
                'event_type': 'resource_use',
                'event': 'MINORS_registration_begins',
                'time': self.env.now,
                'resource_id': registration_resource.id_attribute
                }
        )

        # sample registration duration.
        patient.reg_duration = self.reg_dist.sample()
        yield self.env.timeout(patient.reg_duration)

        trace(f'patient {patient.identifier} registered at'
                f'{self.env.now:.3f}; '
                f'waiting time was {patient.wait_reg:.3f}')
        self.event_log.append(
            {'patient': patient.identifier,
                'pathway': 'Non-Trauma',
                'event': 'MINORS_registration_complete',
                'event_type': 'resource_use_end',
                'time': self.env.now,
                'resource_id': registration_resource.id_attribute}
        )
        # Resource is no longer in use, so put it back in the store
        self.registration_cubicles.put(registration_resource)
        ########################################################

        # record the time that entered the evaluation queue
        start_wait = self.env.now

        self.event_log.append(
            {'patient': patient.identifier,
             'pathway': 'Non-Trauma',
             'event': 'MINORS_examination_wait_begins',
             'event_type': 'queue',
             'time': self.env.now}
        )

        #########################################################
        # request examination resource
        examination_resource = yield self.exam_cubicles.get()

        # record the waiting time for examination to begin
        patient.wait_exam = self.env.now - start_wait
        trace(f'examination of patient {patient.identifier} begins '
                f'{self.env.now:.3f}')
        self.event_log.append(
            {'patient': patient.identifier,
                'pathway': 'Non-Trauma',
                'event': 'MINORS_examination_begins',
                'event_type': 'resource_use',
                'time': self.env.now,
                'resource_id': examination_resource.id_attribute
                }
        )

        # sample examination duration.
        patient.exam_duration = self.exam_dist.sample()
        yield self.env.timeout(patient.exam_duration)

        trace(f'patient {patient.identifier} examination complete '
                f'at {self.env.now:.3f};'
                f'waiting time was {patient.wait_exam:.3f}')
        self.event_log.append(
            {'patient': patient.identifier,
                'pathway': 'Non-Trauma',
                'event': 'MINORS_examination_complete',
                'event_type': 'resource_use_end',
                'time': self.env.now,
                'resource_id': examination_resource.id_attribute}
        )
        # Resource is no longer in use, so put it back in
        self.exam_cubicles.put(examination_resource)
        ############################################################################

        # sample if patient requires treatment?
        patient.require_treat = self.nt_p_treat_dist.sample()  #pylint: disable=attribute-defined-outside-init

        if patient.require_treat:

            self.event_log.append(
                {'patient': patient.identifier,
                 'pathway': 'Non-Trauma',
                 'event': 'requires_treatment',
                 'event_type': 'attribute_assigned',
                 'time': self.env.now}
            )

            # record the time that entered the treatment queue
            start_wait = self.env.now
            self.event_log.append(
                {'patient': patient.identifier,
                 'pathway': 'Non-Trauma',
                 'event': 'MINORS_treatment_wait_begins',
                 'event_type': 'queue',
                 'time': self.env.now}
            )
            ###################################################
            # request treatment cubicle

            non_trauma_treatment_resource = yield self.non_trauma_treatment_cubicles.get()

            # record the waiting time for treatment
            patient.wait_treat = self.env.now - start_wait
            trace(f'treatment of patient {patient.identifier} begins '
                    f'{self.env.now:.3f}')
            self.event_log.append(
                {'patient': patient.identifier,
                    'pathway': 'Non-Trauma',
                    'event': 'MINORS_treatment_begins',
                    'event_type': 'resource_use',
                    'time': self.env.now,
                    'resource_id': non_trauma_treatment_resource.id_attribute
                }
            )

            # sample treatment duration.
            patient.treat_duration = self.nt_treat_dist.sample()
            yield self.env.timeout(patient.treat_duration)

            trace(f'patient {patient.identifier} treatment complete '
                    f'at {self.env.now:.3f};'
                    f'waiting time was {patient.wait_treat:.3f}')
            self.event_log.append(
                {'patient': patient.identifier,
                    'pathway': 'Non-Trauma',
                    'event': 'MINORS_treatment_ends',
                    'event_type': 'resource_use_end',
                    'time': self.env.now,
                    'resource_id': non_trauma_treatment_resource.id_attribute}
            )

            # Resource is no longer in use, so put it back in the store
            self.non_trauma_treatment_cubicles.put(non_trauma_treatment_resource)
        ##########################################################################

        # Return to what happens to all patients, regardless of whether they were sampled as needing treatment
        self.event_log.append(
            {'patient': patient.identifier,
            'pathway': 'Shared',
            'event': 'depart',
            'event_type': 'arrival_departure',
            'time': self.env.now}
        )

        # total time in system
        patient.total_time = self.env.now - patient.arrival

    def attend_trauma_pathway(self, patient):
        '''
        simulates the major treatment process for a patient

        1. request and wait for sign-in/triage
        2. trauma
        3. treatment
        '''
        # record the time of arrival and entered the triage queue
        patient.arrival = self.env.now
        self.event_log.append(
            {'patient': patient.identifier,
             'pathway': 'Trauma',
             'event_type': 'queue',
             'event': 'triage_wait_begins',
             'time': self.env.now}
        )

        ###################################################
        # request sign-in/triage
        triage_resource = yield self.triage_cubicles.get()

        # record the waiting time for triage
        patient.wait_triage = self.env.now - patient.arrival

        trace(f'patient {patient.identifier} triaged to trauma '
                f'{self.env.now:.3f}')
        self.event_log.append(
            {'patient': patient.identifier,
             'pathway': 'Trauma',
             'event_type': 'resource_use',
             'event': 'triage_begins',
             'time': self.env.now,
             'resource_id': triage_resource.id_attribute
            }
        )

        # sample triage duration.
        patient.triage_duration = self.triage_dist.sample()
        yield self.env.timeout(patient.triage_duration)

        trace(f'triage {patient.identifier} complete {self.env.now:.3f}; '
              f'waiting time was {patient.wait_triage:.3f}')
        self.event_log.append(
            {'patient': patient.identifier,
             'pathway': 'Trauma',
             'event_type': 'resource_use_end',
             'event': 'triage_complete',
             'time': self.env.now,
             'resource_id': triage_resource.id_attribute}
        )

        # Resource is no longer in use, so put it back in the store
        self.triage_cubicles.put(triage_resource)
        ###################################################

        # record the time that entered the trauma queue
        start_wait = self.env.now
        self.event_log.append(
            {'patient': patient.identifier,
             'pathway': 'Trauma',
             'event_type': 'queue',
             'event': 'TRAUMA_stabilisation_wait_begins',
             'time': self.env.now}
        )

        ###################################################
        # request trauma room
        trauma_resource = yield self.trauma_stabilisation_bays.get()

        self.event_log.append(
            {'patient': patient.identifier,
                'pathway': 'Trauma',
                'event_type': 'resource_use',
                'event': 'TRAUMA_stabilisation_begins',
                'time': self.env.now,
                'resource_id': trauma_resource.id_attribute
                }
        )

        # record the waiting time for trauma
        patient.wait_trauma = self.env.now - start_wait

        # sample stablisation duration.
        patient.trauma_duration = self.trauma_dist.sample()
        yield self.env.timeout(patient.trauma_duration)

        trace(f'stabilisation of patient {patient.identifier} at '
              f'{self.env.now:.3f}')
        self.event_log.append(
            {'patient': patient.identifier,
             'pathway': 'Trauma',
             'event_type': 'resource_use_end',
             'event': 'TRAUMA_stabilisation_complete',
             'time': self.env.now,
             'resource_id': trauma_resource.id_attribute
            }
        )
        # Resource is no longer in use, so put it back in the store
        self.trauma_stabilisation_bays.put(trauma_resource)

        #######################################################

        # record the time that patient entered the treatment queue
        start_wait = self.env.now
        self.event_log.append(
            {'patient': patient.identifier,
             'pathway': 'Trauma',
             'event_type': 'queue',
             'event': 'TRAUMA_treatment_wait_begins',
             'time': self.env.now}
        )

        ########################################################
        # request treatment cubicle
        trauma_treatment_resource = yield self.trauma_treatment_cubicles.get()

        # record the waiting time for trauma
        patient.wait_treat = self.env.now - start_wait
        trace(f'treatment of patient {patient.identifier} at '
                f'{self.env.now:.3f}')
        self.event_log.append(
            {'patient': patient.identifier,
                'pathway': 'Trauma',
                'event_type': 'resource_use',
                'event': 'TRAUMA_treatment_begins',
                'time': self.env.now,
                'resource_id': trauma_treatment_resource.id_attribute
                }
        )

        # sample treatment duration.
        patient.treat_duration = self.trauma_dist.sample()
        yield self.env.timeout(patient.treat_duration)

        trace(f'patient {patient.identifier} treatment complete {self.env.now:.3f}; '
              f'waiting time was {patient.wait_treat:.3f}')
        self.event_log.append(
            {'patient': patient.identifier,
             'pathway': 'Trauma',
             'event_type': 'resource_use_end',
             'event': 'TRAUMA_treatment_complete',
             'time': self.env.now,
             'resource_id': trauma_treatment_resource.id_attribute}
        )
        self.event_log.append(
            {'patient': patient.identifier,
            'pathway': 'Shared',
            'event': 'depart',
            'event_type': 'arrival_departure',
            'time': self.env.now}
        )

        # Resource is no longer in use, so put it back in the store
        self.trauma_treatment_cubicles.put(trauma_treatment_resource)

        #########################################################

        # total time in system
        patient.total_time = self.env.now - patient.arrival


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

            print(event_log)

            self.all_event_logs.append(event_log)

        self.all_event_logs = pd.concat(self.all_event_logs)
