import simpy
import numpy as np
import pandas as pd
# import matplotlib.pyplot as plt
import itertools
import arrow
import random
import math
import warnings
from sim_tools.distributions import Lognormal, Bernoulli, Gamma
from examples.simulation_utility_functions import trace
from vidigi.resources import VidigiResource as CustomResource

class Empirical:
    """
    for los distributions not fitting statistical distributions
    losdata: los per procedure type
    """
    def __init__(self, losdata, random_seed = None):
        self.rng = np.random.default_rng(seed = random_seed)
        self.losdata = losdata

    def sample(self, size = None):
        """
        method to generate a sample from empirical distribution
        """
        return self.rng.choice(self.losdata, size=None, replace=True)


use_empirical_data = False

start = arrow.get('2022-06-27')

# Theatre schedule
# Generates a theatre schedule from baseline settings, and optionally for a user-defined schedule.
# Baseline settings:

#     4 theatres (2-6)
#     5 day/week (5-7)
#     Each theatre has three sessions per day:
#         Morning: 1 revision OR 2 primary
#         Afternoon: 1 revision OR 2 primary
#         Evening: 1 primary

class Schedule:

    """
    Creates theatre schedule according to rules
    """
    def __init__(self,
                weekday=['Monday', 'Tuesday', 'Wednesday', 'Thursday',
               'Friday', 'Saturday', 'Sunday'],
                allocation={'Monday': ['2P_or_1R', '2P_or_1R', '1P'],
                  'Tuesday': ['2P_or_1R', '2P_or_1R', '1P'],
                  'Wednesday': ['2P_or_1R', '2P_or_1R', '1P'],
                  'Thursday': ['2P_or_1R', '2P_or_1R', '1P'],
                  'Friday': ['2P_or_1R', '2P_or_1R', '1P'],
                  'Saturday': [],
                  'Sunday': []},
                sessions_per_weekday={'Monday': 3, 'Tuesday': 3, 'Wednesday': 3, 'Thursday': 3,
                            'Friday': 3, 'Saturday': 0, 'Sunday': 0},
                theatres_per_weekday={'Monday': 4, 'Tuesday': 4, 'Wednesday': 4, 'Thursday': 4,
                            'Friday': 4, 'Saturday': 0, 'Sunday': 0}):
        """
        parameters used to create schedule defined in 'scenarios class'
        """
        self.weekday=weekday
        self.allocation=allocation
        self.sessions_per_weekday=sessions_per_weekday
        self.sessions_per_weekday_list=list(sessions_per_weekday.values())
        self.theatres_per_weekday=theatres_per_weekday

    def create_schedule(self,weekday, sessions_per_weekday_list, allocation, theatres_per_weekday):
        """
        Arguments needed:
            *weekday: a list of weekdays
            *sessions_per_weekday: a list of integers representing the number of sessions per weekday
            *allocation: a dictionary where the keys are the weekdays and the values are lists of
                        allocations for each session
            *theatres_per_weekday: a dictionary where the keys are the weekdays and the values are
                        integers representing the number of theatres per weekday
        Returns a dictionary where the keys are the weekdays and the values are lists
                        of lists of allocations for each theatre for each session.
        """
        schedule = {}
        for day, num_sessions in zip(weekday, sessions_per_weekday_list):
            schedule[day] = []
            for theatre in range(theatres_per_weekday[day]):
                schedule[day].append([])
                for session in range(num_sessions):
                    if allocation[day][session] == '1P':
                        schedule[day][theatre].append({'primary': 1})
                    elif allocation[day][session] == '1R':
                        schedule[day][theatre].append({'revision': 1})
                    elif allocation[day][session] == '2P':
                        schedule[day][theatre].append({'primary': 2})
                    elif allocation[day][session] == '2P_or_1R':
                        if random.random() > 0.5:
                            schedule[day][theatre].append({'primary': 2})
                        else:
                            schedule[day][theatre].append({'revision': 1})
        return schedule

    def daily_counts(self,day_data):
        """
        day_data: called in week_schedule() function, day_data is a sample weekly dictionary from create_schedule()

        Convert dict to a pandas DataFrame with 'primary' and 'revision' as columns
        and days of the week as the index, populated with the total count of 'primary' and 'revision' in each day.
        Returns a one week schedule
        """
        #day_data = create_schedule(weekday, sessions_per_weekday, allocation, theatres_per_weekday)
        primary_slots = 0
        revision_slots = 0
        for value in day_data:
            if value:
                for sub_value in value:
                    if 'primary' in sub_value:
                        primary_slots += sub_value['primary']
                    if 'revision' in sub_value:
                        revision_slots += sub_value['revision']
        return [primary_slots, revision_slots]

    def week_schedule(self):
        """
        samples a weekly dictionary of theatres, sessions, and surgeries from create_schedule()
        counts daily number or primary and revision surgeries needed using daily_counts()
        and converts to a dataframe
        """
        week_sched = pd.DataFrame(columns=['Primary_slots', 'Revision_slots'])
        day_data = self.create_schedule(self.weekday, self.sessions_per_weekday_list,
                                   self.allocation, self.theatres_per_weekday)
        for key, value in day_data.items():
            week_sched.loc[key] = self.daily_counts(value)
        week_sched = week_sched.reset_index()
        week_sched.rename(columns = {'index':'Day'}, inplace = True)
        return week_sched

    def theatre_capacity(self):
        length_sched = int(round(2*(DEFAULT_WARM_UP_PERIOD+DEFAULT_RESULTS_COLLECTION_PERIOD)/7, 0))

        DEFAULT_SCHEDULE_AVAIL = pd.DataFrame()
        for week in range(length_sched):
            single_random_week = self.week_schedule()
            DEFAULT_SCHEDULE_AVAIL = pd.concat([DEFAULT_SCHEDULE_AVAIL, single_random_week],axis=0)
        return DEFAULT_SCHEDULE_AVAIL.reset_index()

#  Model parameterisation
# A scenarios class containing all parameters that can be varied in the model. Used for setting up scenarios, the scenarios class contains baseline parameters which can be changed at runtime.

SET_WEEKDAY = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
               'Friday', 'Saturday', 'Sunday']
SET_SESSIONS_PER_WEEKDAY = {'Monday': 3, 'Tuesday': 3, 'Wednesday': 3, 'Thursday': 3,
                            'Friday': 3, 'Saturday': 0, 'Sunday': 0}
SET_SESSIONS_PER_WEEKDAY_LIST = list(SET_SESSIONS_PER_WEEKDAY.values())
SET_ALLOCATION = {'Monday': ['2P_or_1R', '2P_or_1R', '1P'],
                  'Tuesday': ['2P_or_1R', '2P_or_1R', '1P'],
                  'Wednesday': ['2P_or_1R', '2P_or_1R', '1P'],
                  'Thursday': ['2P_or_1R', '2P_or_1R', '1P'],
                  'Friday': ['2P_or_1R', '2P_or_1R', '1P'],
                  'Saturday': [],
                  'Sunday': []}
SET_THEATRES_PER_WEEKDAY = {'Monday': 4, 'Tuesday': 4, 'Wednesday': 4, 'Thursday': 4,
                            'Friday': 4, 'Saturday': 0, 'Sunday': 0}

# simulation parameters
DEFAULT_NUMBER_OF_RUNS = 30
DEFAULT_RESULTS_COLLECTION_PERIOD = 42
results_collection_period = 70
DEFAULT_WARM_UP_PERIOD = 7
default_rng_set = None

# for returning results per day
first_obs = 1
interval = 1

# empirical los distributions for patients not delayed
los_data = pd.read_csv('https://raw.githubusercontent.com/AliHarp/HEP/main/HEP_notebooks/01_model/Test_data/los_spells_no_zero.csv')
#convert to np arrays for sampling

class Scenario:
    """
    Holds LoS dists for each patient type
    Holds delay dists
    Holds prob of delay, prob of same day dist
    Holds resources: beds
    Passed to hospital model and process classes
    """
    def __init__(self,
                 schedule,
                 schedule_avail=None,
                 random_number_set=42,
                 primary_hip_mean_los=4.433333,
                 primary_knee_mean_los=4.651163,
                 revision_hip_mean_los=6.908867,
                 revision_knee_mean_los=7.194118,
                 unicompart_knee_mean_los=2.914671,

                 delay_post_los_mean=16.521739,

                 prob_ward_delay=0.076,

                 n_beds=40,

                 primary_hip_sd_los=2.949526,
                 primary_knee_sd_los=2.828129,
                 revision_hip_sd_los=6.965812,
                 revision_knee_sd_los=7.598554,
                 unicompart_knee_sd_los=2.136334,

                 delay_post_los_sd=15.153132,

                 primary_dict={1: 'p_hip', 2: 'p_knee', 3: 'uni_knee'},
                 revision_dict={1: 'r_hip', 2: 'r_knee'},

                 primary_prob=[0.51, 0.38, 0.11],
                 revision_prob=[0.55, 0.45],

                 primary_knee_los_data = los_data['Primary Knee'].dropna().to_numpy(),
                 unicompart_knee_los_data = los_data['Unicompart Knee'].dropna().to_numpy(),
                 revision_knee_los_data = los_data['Revision Knee'].dropna().to_numpy(),
                 primary_hip_los_data = los_data['Primary Hip'].dropna().to_numpy(),
                 revision_hip_los_data = los_data['Revision Hip'].dropna().to_numpy()):

        """
        controls initial seeds of each RNS used in model
        """
        self.schedule = schedule
        if schedule_avail is None:
            self.schedule_avail = schedule.theatre_capacity()

        else:
            self.schedule_avail = schedule_avail
        #self.schedule_avail = schedule_avail
        self.random_number_set = random_number_set
        self.primary_hip_mean_los = primary_hip_mean_los
        self.primary_knee_mean_los = primary_knee_mean_los
        self.revision_hip_mean_los = revision_hip_mean_los
        self.revision_knee_mean_los = revision_knee_mean_los
        self.unicompart_knee_mean_los = unicompart_knee_mean_los
        self.n_beds = n_beds
        self.prob_ward_delay = prob_ward_delay
        self.primary_hip_sd_los = primary_hip_sd_los
        self.primary_knee_sd_los = primary_knee_sd_los
        self.revision_hip_sd_los = revision_hip_sd_los
        self.revision_knee_sd_los = revision_knee_sd_los
        self.unicompart_knee_sd_los = unicompart_knee_sd_los
        self.delay_post_los_mean = delay_post_los_mean
        self.delay_post_los_sd = delay_post_los_sd
        self.primary_dict = primary_dict
        self.revision_dict = revision_dict
        self.primary_prob = primary_prob
        self.revision_prob = revision_prob
        self.primary_knee_los_data = primary_knee_los_data
        self.unicompart_knee_los_data = unicompart_knee_los_data
        self.revision_knee_los_data = revision_knee_los_data
        self.primary_hip_los_data = primary_hip_los_data
        self.revision_hip_los_data = revision_hip_los_data
        self.init_sampling()

    def set_random_no_set(self, random_number_set):
        """
        controls random sampling for each distribution used in simulations"""
        self.random_number_set = random_number_set
        self.init_sampling()

    def init_sampling(self):
        """
        distribs used in model and initialise seed"""
        rng_streams = np.random.default_rng(self.random_number_set)
        self.seeds = rng_streams.integers(0,99999999999, size = 20)

        #######  Distributions ########
        # LNorm LoS distribution for each surgery patient type
        self.primary_hip_dist = Lognormal(self.primary_hip_mean_los, self.primary_hip_sd_los,
                                          random_seed=self.seeds[0])
        self.primary_knee_dist = Lognormal(self.primary_knee_mean_los, self.primary_knee_sd_los,
                                          random_seed=self.seeds[1])
        self.revision_hip_dist = Lognormal(self.revision_hip_mean_los, self.revision_hip_sd_los,
                                          random_seed=self.seeds[2])
        self.revision_knee_dist = Lognormal(self.revision_knee_mean_los, self.revision_knee_sd_los,
                                          random_seed=self.seeds[3])
        self.unicompart_knee_dist = Lognormal(self.unicompart_knee_mean_los, self.unicompart_knee_sd_los,
                                          random_seed=self.seeds[4])

        # Empirical LoS distributions for each surgery patient type
        self.primary_hip_dist_emp = Empirical(self.primary_hip_los_data,
                                            random_seed=self.seeds[5])
        self.primary_knee_dist_emp = Empirical(self.primary_knee_los_data,
                                            random_seed=self.seeds[6])
        self.revision_hip_dist_emp = Empirical(self.revision_hip_los_data,
                                            random_seed=self.seeds[7])
        self.revision_knee_dist_emp = Empirical(self.revision_knee_los_data,
                                            random_seed=self.seeds[8])
        self.unicompart_knee_dist_emp = Empirical(self.unicompart_knee_los_data,
                                            random_seed=self.seeds[9])

        # distribution for delayed LoS
        self.los_delay_dist = Lognormal(self.delay_post_los_mean, self.delay_post_los_sd,
                                       random_seed=self.seeds[10])

        #probability of having LoS delayed on ward
        self.los_delay = Bernoulli(self.prob_ward_delay, random_seed=self.seeds[11])

    def number_slots(self, schedule_avail):
        """
        convert to np arrays for each surgery type for patient generators
        """
        self.schedule_avail_primary = self.schedule_avail['Primary_slots'].to_numpy()
        self.schedule_avail_revision = self.schedule_avail['Revision_slots'].to_numpy()
        return(self.schedule_avail_primary, self.schedule_avail_revision)

    def primary_types(self,prob):
        """
        randomly select primary surgical type from custom distribution: primary_prop
        prob = primary_prop
        used for generating primary patients of each surgical type
        """
        self.primary_surgery = np.random.choice(np.arange(1,4), p=prob)
        return(self.primary_surgery)

    def revision_types(self,prob):
        """
        randomly select revision surgical type from custom distribution: revision_prop
        prob = revision_prop
        used for generating revision patients of each surgical type
        """
        self.revision_surgery = np.random.choice(np.arange(1,3), p=prob)
        return(self.revision_surgery)

    def label_types(self, prop, dict):
        """
        return label for each surgery type
        """
        return np.vectorize(dict.__getitem__)(prop)

# Patient Pathway process logic
# Patient journeys for two classes: PrimaryPatient and RevisionPatient

class PrimaryPatient:
    """
    The process a patient needing primary hip or knee surgery will undergo
    from scheduled admission for surgery to discharge

    day = simulation day
    id = patient id
    args: Scenario parameter class
    """
    def __init__(self, day, id, env, args, event_log):

        self.day = day
        self.id = id
        self.env = env
        self.args = args
        self.event_log = event_log

        self.arrival = -np.inf
        self.queue_beds = -np.inf
        self.primary_los = 0
        self.total_time = -np.inf
        self.depart = -np.inf

        self.lost_slots_bool = False
        self.delayed_los_bool = False
        self.weekday = 0
        self.patient_class = 'primary'

    def service(self):
        """
        Arrive according to theatres schedule
        Some patients will leave on day of surgery and the slot is lost
        Some patients will have their surgery cancelled due to lack of beds
        Otherwise, patient is admitted and stays in a bed
        Some patients will have a post-bed request delay to their LoS
        Patient is discharged
        """

        self.arrival = self.env.now
        self.event_log.append(
            {'patient': self.id,
             'pathway': 'Primary',
             'event_type': 'arrival_departure',
             'event': 'arrival',
             'time': self.env.now}
        )
        self.patient_class = 'primary'
        self.weekday = start.shift(days=self.env.now).weekday()

        # set los for primary surgery types
        self.types = int(self.args.primary_types(self.args.primary_prob))
        if self.types == 1:
            if use_empirical_data:
                self.primary_los = self.args.primary_hip_dist_emp.sample()
            else:
                self.primary_los = self.args.primary_hip_dist.sample()
            self.primary_label = 'p_hip'
        elif self.types == 2:
            if use_empirical_data:
                self.primary_los = self.args.primary_knee_dist_emp.sample()
            else:
                self.primary_los = self.args.primary_knee_dist.sample()
            self.primary_label = 'p_knee'
        else:
            if use_empirical_data:
                self.primary_los = self.args.unicompart_knee_dist_emp.sample()
            else:
                self.primary_los = self.args.unicompart_knee_dist.sample()
            self.primary_label = 'uni_knee'

        #vectorize according to dict key to get surgical type
        #self.primary_label = self.args.label_types(primary_prop, primary_dict)

        #sample if need for delayed discharge
        self.need_for_los_delay = self.args.los_delay.sample()

        #Patients who have a delayed discharge follow this pathway
        if self.need_for_los_delay:

            #request a bed on ward - if none available within 0.5-1 day,
            # patient has surgery cancelled
            with self.args.beds.get() as req:

                self.event_log.append(
                    {'patient': self.id,
                    'pathway': 'Primary',
                    'event_type': 'queue',
                    'event': 'enter_queue_for_bed',
                    'time': self.env.now}
                )

                admission = random.uniform(0.5,1)
                admit = yield req | self.env.timeout(admission)

                # Logic for if wait for bed is less than threshold (so patient goes ahead
                # and has surgery, and is then put into bed)
                if req in admit:
                    #record queue time for primary patients -- if > admission,
                    # this patient will leave the system and the slot is lost

                    self.queue_beds = self.env.now - self.arrival
                    trace(f'primary patient {self.id} {self.primary_label}'
                            f'has been allocated a bed at {self.env.now:.3f}'
                            f'and queued for {self.queue_beds:.3f}')

                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Primary',
                        'event_type': 'resource_use',
                        'event': 'post_surgery_stay_begins',
                        'time': self.env.now,
                        # Syntax from https://stackoverflow.com/questions/74842300/how-to-get-the-item-name-and-not-its-address-when-requesting-with-a-condition-e
                        'resource_id': admit[req].id_attribute}
                    )

                    # NOTE: SR TWEAKED THIS LINE COMPARED TO ORIGINAL MODEL
                    # DOUBLE CHECK INTENDED ACTION HAS BEEN CORRECTLY UNDERSTOOD
                    self.primary_los = self.primary_los + self.args.los_delay_dist.sample()
                    yield self.env.timeout(self.primary_los)
                    self.lost_slots_bool = False
                    self.delayed_los_bool = True
                    self.depart = self.env.now
                    trace(f'los of primary patient {self.id} completed at {self.env.now:.3f}')
                    self.total_time = self.env.now - self.arrival
                    trace(f'primary patient {self.id} {self.primary_label}'
                            f'total los = {self.total_time:.3f} with delayed discharge')

                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Primary',
                        'event_type': 'resource_use_end',
                        'event': 'post_surgery_stay_ends',
                        'time': self.env.now,
                        'resource_id': admit[req].id_attribute}
                    )

                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Primary',
                        'event_type': 'queue',
                        'event': 'discharged_after_stay',
                        'time': self.env.now}
                    )

                    # Resource is no longer in use, so put it back in the store
                    self.args.beds.put(admit[req])

                    # Patient's LOS is complete - they leave the hospital
                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Primary',
                        'event_type': 'arrival_departure',
                        'event': 'depart',
                        'time': self.env.now+1}
                    )

                else:
                    #patient had to leave as no beds were available on ward

                    # Put the bed back in to the store
                    # req = yield req
                    # self.args.beds.put(req)

                    self.no_bed_cancellation = self.env.now - self.arrival
                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Primary',
                        'event': 'no_bed_available',
                        'event_type': 'queue',
                        'time': self.env.now}
                    )
                    trace(f'primary patient {self.id} {self.primary_label}'
                            f'had surgery cancelled after {self.no_bed_cancellation:.3f}')
                    self.queue_beds = self.env.now - self.arrival
                    self.total_time = self.env.now - self.arrival
                    self.primary_los = 0
                    self.lost_slots_bool = True
                    self.delayed_los_bool = False
                    self.depart = self.env.now
                    trace(f'primary patient {self.id} {self.primary_label}'
                            f'recorded {self.lost_slots_bool}')
                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Primary',
                        'event': 'depart',
                        'event_type': 'arrival_departure',
                        'time': self.env.now+1}
                    )

        #Pathway for no delayed los
        else:
            #request a bed on ward - if none available within 0.5-1 day, patient has surgery cancelled
            with self.args.beds.get() as req:

                self.event_log.append(
                    {'patient': self.id,
                    'pathway': 'Primary',
                    'event_type': 'queue',
                    'event': 'enter_queue_for_bed',
                    'time': self.env.now}
            )

                admission = random.uniform(0.5,1)
                admit = yield req | self.env.timeout(admission)
                self.no_bed_cancellation = self.env.now - self.arrival

                if req in admit:
                    #record queue time for primary patients -- if >1, this patient will leave the system and the slot is lost
                    self.queue_beds = self.env.now - self.arrival
                    trace(f'primary patient {self.id} {self.primary_label}'
                            f'has been allocated a bed at {self.env.now:.3f}'
                            f'and queued for {self.queue_beds:.3f}')
                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Primary',
                        'event_type': 'resource_use',
                        'event': 'post_surgery_stay_begins',
                        'time': self.env.now,
                        'resource_id': admit[req].id_attribute}
                        )
                    # self.primary_los = self.primary_los
                    yield self.env.timeout(self.primary_los)
                    self.lost_slots_bool = False
                    self.delayed_los_bool = False
                    self.depart = self.env.now
                    trace(f'los of primary patient {self.id} {self.primary_label}'
                            f'completed at {self.env.now:.3f}')
                    self.total_time = self.env.now - self.arrival
                    trace(f'primary patient {self.id} {self.primary_label}'
                            f'total los = {self.total_time:.3f}')
                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Primary',
                        'event_type': 'resource_use_end',
                        'event': 'post_surgery_stay_ends',
                        'time': self.env.now,
                        'resource_id': admit[req].id_attribute}
                        )
                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Primary',
                        'event_type': 'queue',
                        'event': 'discharged_after_stay',
                        'time': self.env.now}
                    )
                    # Resource is no longer in use, so put it back in the store
                    self.args.beds.put(admit[req])

                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Primary',
                        'event': 'depart',
                        'event_type': 'arrival_departure',
                        'time': self.env.now+1}
                    )

                else:
                    #patient had to leave as no beds were available on ward
                    # Put the bed back in to the store
                    # req = yield req
                    # self.args.beds.put(req)

                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Primary',
                        'event': 'no_bed_available',
                        'event_type': 'queue',
                        'time': self.env.now}
                    )

                    trace(f'primary patient {self.id} {self.primary_label}'
                            f'had surgery cancelled after {self.no_bed_cancellation:.3f}')
                    self.queue_beds = self.env.now - self.arrival
                    self.total_time = self.env.now - self.arrival
                    self.primary_los = 0
                    self.lost_slots_bool = True
                    self.delayed_los_bool = False
                    self.depart = self.env.now
                    trace(f'primary patient {self.id} {self.primary_label}'
                            f'recorded {self.lost_slots_bool}')

                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Primary',
                        'event': 'depart',
                        'event_type': 'arrival_departure',
                        'time': self.env.now+1}
                    )

class RevisionPatient:
    """
    The process a patient needing revision hip or knee surgery will undergo
    from scheduled admission for surgery to discharge

    day = simulation day
    id = patient id
    args: Scenario parameter class
    """
    def __init__(self, day, id, env, args, event_log):

        self.day = day
        self.id = id
        self.env = env
        self.args = args
        self.event_log = event_log

        self.arrival = -np.inf
        self.queue_beds = -np.inf
        self.revision_los = 0
        self.total_time = -np.inf
        self.depart = -np.inf

        self.lost_slots_bool = False
        self.delayed_los_bool = False
        self.weekday = 0
        self.patient_class = 'revision'

    def service(self):
        """
        Arrive according to theatres schedule
        Some patients will leave on day of surgery and the slot is lost
        Some patients will have their surgery cancelled due to lack of beds
        Otherwise, patient is admitted and stays in a bed
        Some patients will have a post-bed request delay to their LoS
        Patient is discharged
        """

        self.arrival = self.env.now
        self.event_log.append(
            {'patient': self.id,
             'pathway': 'Revision',
             'event_type': 'arrival_departure',
             'event': 'arrival',
             'time': self.env.now}
        )
        self.patient_class = 'revision'
        self.weekday = start.shift(days=self.env.now).weekday()

        # set los for revision surgery types
        self.types = int(self.args.revision_types(self.args.revision_prob))
        if self.types == 1:
            if use_empirical_data:
                self.revision_los = self.args.revision_hip_dist_emp.sample()
            else:
                self.revision_los = self.args.revision_hip_dist.sample()
            self.revision_label = 'r_hip'
        else:
            if use_empirical_data:
                self.revision_los = self.args.revision_knee_dist_emp.sample()
            else:
                self.revision_los = self.args.revision_knee_dist.sample()
            self.revision_label = 'r_knee'

        #vectorize according to dict key to get surgical type
        #self.revision_label = self.args.label_types(revision_prop, revision_dict)

        #sample if need for delayed discharge
        self.need_for_los_delay = self.args.los_delay.sample()

        if self.need_for_los_delay:

        #request bed on ward - if none available within 0.5-1  day, patient has surgery cancelled
            with self.args.beds.get() as req:
                admission = random.uniform(0.5, 1)
                admit = yield req | self.env.timeout(admission)

                if req in admit:
                    #record queue time for primary patients -- if >admission, this patient will leave the system and the slot is lost
                    self.queue_beds = self.env.now - self.arrival
                    trace(f'revision patient {self.id} {self.revision_label}'
                          f'has been allocated a bed at {self.env.now:.3f}'
                          f'and queued for {self.queue_beds:.3f}')
                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Revision',
                        'event_type': 'resource_use',
                        'event': 'post_surgery_stay_begins',
                        'time': self.env.now,
                        'resource_id': admit[req].id_attribute}
                    )
                    # NOTE: SR TWEAKED THIS LINE COMPARED TO ORIGINAL MODEL
                    # DOUBLE CHECK INTENDED ACTION HAS BEEN CORRECTLY UNDERSTOOD
                    self.revision_los = self.revision_los + self.args.los_delay_dist.sample()
                    yield self.env.timeout(self.revision_los)
                    self.lost_slots_bool = False
                    self.delayed_los_bool = True
                    self.depart = self.env.now
                    trace(f'los of revision patient {self.id} {self.revision_label}'
                          f'completed at {self.env.now:.3f}')
                    self.total_time = self.env.now - self.arrival
                    trace(f'revision patient {self.id} {self.revision_label}'
                          f'total los = {self.total_time:.3f} with delayed discharge')
                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Revision',
                        'event_type': 'resource_use_end',
                        'event': 'post_surgery_stay_ends',
                        'time': self.env.now,
                        'resource_id': admit[req].id_attribute}
                    )

                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Revision',
                        'event_type': 'queue',
                        'event': 'discharged_after_stay',
                        'time': self.env.now}
                    )
                    # Resource is no longer in use, so put it back in the store
                    self.args.beds.put(admit[req])

                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Revision',
                        'event': 'depart',
                        'event_type': 'arrival_departure',
                        'time': self.env.now+1}
                    )

                else:
                    #patient had to leave as no beds were available on ward

                    # Put the bed back in to the store
                    # req = yield req
                    # self.args.beds.put(req)

                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Revision',
                        'event': 'no_bed_available',
                        'event_type': 'queue',
                        'time': self.env.now}
                    )

                    self.no_bed_cancellation = self.env.now - self.arrival
                    trace(f'revision patient {self.id}'
                          f'had surgery cancelled after {self.no_bed_cancellation:.3f}')
                    self.queue_beds = self.env.now - self.arrival
                    self.total_time = self.env.now - self.arrival
                    self.revision_los = 0
                    self.lost_slots_bool = True
                    self.delayed_los_bool = False
                    self.depart = self.env.now
                    trace(f'revision patient {self.id} {self.revision_label}'
                          f'recorded {self.lost_slots_bool}')

                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Revision',
                        'event': 'depart',
                        'event_type': 'arrival_departure',
                        'time': self.env.now+1}
                    )

        #no need for delayed discharge
        else:
            #request bed on ward - if none available within 0.5-1  day, patient has surgery cancelled
            with self.args.beds.get() as req:
                admission = random.uniform(0.5, 1)
                admit = yield req | self.env.timeout(admission)
                self.no_bed_cancellation = self.env.now - self.arrival

                if req in admit:
                    #record queue time for primary patients -- if >1, this patient will leave the system and the slot is lost
                    self.queue_beds = self.env.now - self.arrival
                    trace(f'revision patient {self.id} {self.revision_label}'
                          f'has been allocated a bed at {self.env.now:.3f}'
                          f'and queued for {self.queue_beds:.3f}')
                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Revision',
                        'event_type': 'resource_use',
                        'event': 'post_surgery_stay_begins',
                        'time': self.env.now,
                        'resource_id': admit[req].id_attribute}
                    )
                    self.revision_los = self.revision_los
                    yield self.env.timeout(self.revision_los)
                    self.lost_slots_bool = False
                    self.delayed_los_bool = False
                    self.depart = self.env.now

                    trace(f'los of revision patient {self.id} completed at {self.env.now:.3f}')
                    self.total_time = self.env.now - self.arrival
                    trace(f'revision patient {self.id} total los = {self.total_time:.3f}')
                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Revision',
                        'event_type': 'resource_use_end',
                        'event': 'post_surgery_stay_ends',
                        'time': self.env.now,
                        'resource_id': admit[req].id_attribute}
                        )
                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Revision',
                        'event_type': 'queue',
                        'event': 'discharged_after_stay',
                        'time': self.env.now}
                    )
                    # Resource is no longer in use, so put it back in the store
                    self.args.beds.put(admit[req])

                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Revision',
                        'event': 'depart',
                        'event_type': 'arrival_departure',
                        'time': self.env.now+1}
                    )

                else:
                    # Put the bed back in to the store
                    # req = yield req
                    # self.args.beds.put(req)

                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Revision',
                        'event': 'no_bed_available',
                        'event_type': 'queue',
                        'time': self.env.now}
                    )

                    #patient had to leave as no beds were available on ward
                    trace(f'revision patient {self.id} {self.revision_label}'
                          f'had surgery cancelled after {self.no_bed_cancellation:.3f}')
                    self.queue_beds = self.env.now - self.arrival
                    self.total_time = self.env.now - self.arrival
                    self.revision_los = 0
                    self.lost_slots_bool = True
                    self.delayed_los_bool = False
                    self.depart = self.env.now
                    trace(f'revision patient {self.id} {self.revision_label}'
                          f'recorded {self.lost_slots_bool}')

                    self.event_log.append(
                        {'patient': self.id,
                        'pathway': 'Revision',
                        'event': 'depart',
                        'event_type': 'arrival_departure',
                        'time': self.env.now+1}
                    )


# The model class
# The Hospital class generates primary and revision patients and implements a method to run the model.
# Collects patient-level results and audits daily results

class Hospital:
    """
    The orthopaedic hospital model
    """
    def __init__(self, args):
        self.env = simpy.Environment()
        self.args = args
        self.init_resources()

        #patient generator lists
        self.patients = []
        self.primary_patients = []
        self.revision_patients = []
        self.primary_patients_id = []
        self.revision_patients_id = []
        self.cum_primary_patients = []
        self.cum_revision_patients = []

        self.event_log = []

        self.DEFAULT_RESULTS_COLLECTION_PERIOD = None
        self.summary_results = None
        self.audit_interval = interval

        #lists used for daily audit_frame for summary results per day
        self.audit_time = []
        self.audit_day_of_week = []
        self.audit_beds_used_primary = []
        self.audit_beds_used_revision = []
        self.audit_beds_used = []
        self.audit_primary_arrival = []
        self.audit_revision_arrival = []
        self.audit_primary_queue_beds = []
        self.audit_revision_queue_beds = []
        self.audit_primary_los = []
        self.audit_revision_los = []

        self.results = pd.DataFrame()

    def audit_frame(self):
        """
        Dataframe with results summarised per day
        """
        self.results = pd.DataFrame({'sim_time':self.audit_time,
                                     'weekday': self.audit_day_of_week,
                                     'bed_utilisation_primary': self.audit_beds_used_primary,
                                     'bed_utilisation_revision': self.audit_beds_used_revision,
                                     'bed_utilisation':self.audit_beds_used,
                                     'primary_arrivals': self.audit_primary_arrival,
                                     'revision_arrivals': self.audit_revision_arrival,
                                     'primary_bed_queue': self.audit_primary_queue_beds,
                                     'revision_bed_queue': self.audit_revision_queue_beds,
                                     'primary_mean_los': self.audit_primary_los,
                                     'revision_mean_los': self.audit_revision_los
                                    })

    def patient_results(self):
        """
        Dataframes to hold individual results per patient per day per run
        Attributes from patient classes
        """

        results_primary_pt = pd.DataFrame({'Day':np.array([getattr(p, 'day') for p in self.cum_primary_patients]),
                             'weekday':np.array([getattr(p, 'weekday') for p in self.cum_primary_patients]),
                             'ID':np.array([getattr(p, 'id') for p in self.cum_primary_patients]),
                             'arrival time':np.array([getattr(p, 'arrival') for p in self.cum_primary_patients]),
                             'patient class':np.array([getattr(p, 'patient_class') for p in self.cum_primary_patients]),
                             'surgery type':np.array([getattr(p, 'primary_label') for p in self.cum_primary_patients]),
                             'lost slots':np.array([getattr(p, 'lost_slots_bool') for p in self.cum_primary_patients]),
                             'queue time':np.array([getattr(p, 'queue_beds') for p in self.cum_primary_patients]),
                             'los':np.array([getattr(p, 'primary_los') for p in self.cum_primary_patients]),
                             'delayed discharge':np.array([getattr(p, 'delayed_los_bool') for p in self.cum_primary_patients]),
                             'depart':np.array([getattr(p, 'depart') for p in self.cum_primary_patients])
                            })

        results_revision_pt = pd.DataFrame({'Day':np.array([getattr(p, 'day') for p in self.cum_revision_patients]),
                             'ID':np.array([getattr(p, 'id') for p in self.cum_revision_patients]),
                             'weekday':np.array([getattr(p, 'weekday') for p in self.cum_revision_patients]),
                             'arrival time':np.array([getattr(p, 'arrival') for p in self.cum_revision_patients]),
                             'patient class':np.array([getattr(p, 'patient_class') for p in self.cum_revision_patients]),
                             'surgery type':np.array([getattr(p, 'revision_label') for p in self.cum_revision_patients]),
                             'lost slots':np.array([getattr(p, 'lost_slots_bool') for p in self.cum_revision_patients]),
                             'queue time':np.array([getattr(p, 'queue_beds') for p in self.cum_revision_patients]),
                             'los':np.array([getattr(p, 'revision_los') for p in self.cum_revision_patients]),
                             'delayed discharge':np.array([getattr(p, 'delayed_los_bool') for p in self.cum_revision_patients]),
                             'depart':np.array([getattr(p, 'depart') for p in self.cum_revision_patients])
                            })
        return(results_primary_pt, results_revision_pt)

    def plots(self):
        """
        plot results at end of run
        """
    def perform_audit(self):
        """
        Results per day
        monitor ED each day and return daily results for metrics in audit_frame
        """
        yield self.env.timeout(DEFAULT_WARM_UP_PERIOD)

        while True:
            #simulation time
            t = self.env.now
            self.audit_time.append(t)

            #weekday
            self.audit_day_of_week.append(start.shift(days=self.env.now -1).weekday())

            ##########  bed utilisation - primary, revision, total
            primary_beds = (self.args.beds.capacity - len(self.args.beds.items)) in self.cum_primary_patients
            (self.audit_beds_used_primary.append(primary_beds / self.args.n_beds))

            revision_beds = (self.args.beds.capacity - len(self.args.beds.items)) in self.cum_revision_patients
            (self.audit_beds_used_revision.append(revision_beds / self.args.n_beds))

            (self.audit_beds_used.append((self.args.beds.capacity - len(self.args.beds.items)) / self.args.n_beds))

            ###########  lost slots
            patients = self.cum_revision_patients + self.cum_primary_patients

            # deal with lost slots on zero arrival days
            """
            lost_slots = []
            def zero_days(ls):
                if not zero_days:
                    return 1
                else:
                    return 0

            ls = (np.array([getattr(p, 'lost_slots_int') for p in patients]))
            if zero_days(ls):
                lost_slots = 0
            else:

            lost_slots = len(np.array([getattr(p,'lost_slots_int') for p in patients / len(patients)
            self.audit_slots_lost.append(lost_slots)
            """
            ######### arrivals
            pp = len(np.array([p.id for p in self.cum_primary_patients]))
            rp = len(np.array([p.id for p in self.cum_revision_patients]))
            self.audit_primary_arrival.append(len(self.primary_patients))
            self.audit_revision_arrival.append(len(self.revision_patients))

            #queue times
            primary_q = np.array([getattr(p, 'queue_beds') for p in self.cum_primary_patients
                                           if getattr(p, 'queue_beds') > -np.inf]).mean()
            self.audit_primary_queue_beds.append(primary_q)

            revision_q = np.array([getattr(p, 'queue_beds') for p in self.cum_revision_patients
                                           if getattr(p, 'queue_beds') > -np.inf]).mean()
            self.audit_revision_queue_beds.append(revision_q)

            #mean lengths of stay
            primarylos = np.array([getattr(p, 'primary_los') for p in self.cum_primary_patients
                                           if getattr(p, 'primary_los') > -np.inf]).mean().round(2)
            self.audit_primary_los.append(primarylos)

            revisionlos = np.array([getattr(p, 'revision_los') for p in self.cum_revision_patients
                                           if getattr(p, 'revision_los') > -np.inf]).mean().round(2)
            self.audit_revision_los.append(revisionlos)

            yield self.env.timeout(self.audit_interval)

    def init_resources(self):
        """
        ward beds initialised and stored in args
        """
        # self.args.beds = simpy.Resource(self.env,
        #                                 capacity=self.args.n_beds)

        self.args.beds = simpy.Store(self.env)

        for i in range(self.args.n_beds):
            self.args.beds.put(
                CustomResource(
                    self.env,
                    capacity=1,
                    id_attribute = i+1)
                )

    def run(self, results_collection = DEFAULT_RESULTS_COLLECTION_PERIOD+DEFAULT_WARM_UP_PERIOD):
        """
        single run of model
        """
        self.env.process(self.patient_arrivals_generator_primary())
        self.env.process(self.patient_arrivals_generator_revision())
        self.env.process(self.perform_audit())
        self.results_collection = results_collection
        self.env.run(until=results_collection)
        audit_frame = self.audit_frame()
        return audit_frame

    def patient_arrivals_generator_primary(self):
        """
        Primary patients arrive according to daily theatre schedule
        ------------------
        """
        #sched = args.number_slots(self.args.schedule_avail)[0]
        sched = self.args.schedule_avail['Primary_slots']
        pt_count = 1
        for day in range(len(sched)):

            primary_arrivals = sched[day]
            trace(f'--------- {primary_arrivals} primary patients are scheduled on Day {day} -------')
            for i in range(primary_arrivals):

                new_primary_patient = PrimaryPatient(day=day, id=pt_count, env=self.env,
                                                     args=self.args, event_log=self.event_log)
                self.cum_primary_patients.append(new_primary_patient)
                self.primary_patients.append(new_primary_patient)
                #for debuggng
                self.primary_patients_id.append(new_primary_patient.id)
                trace(f'primary patient {pt_count} arrived on day {day:.3f}')
                self.env.process(new_primary_patient.service())
                pt_count += 1
                trace(f'primary ids: {self.primary_patients_id}')
            yield self.env.timeout(1)
            self.primary_patients *= 0


    def patient_arrivals_generator_revision(self):
        """
        Revision patients arrive according to daily theatre schedule
        ------------------
        """
        # sched = self.args.number_slots(self.args.schedule_avail)[1]
        sched = self.args.schedule_avail['Revision_slots']
        pt_count = 1
        for day in range(len(sched)):

            revision_arrivals = sched[day]
            trace(f'--------- {revision_arrivals} revision patients are scheduled on Day {day} -------')
            for i in range(revision_arrivals):
                new_revision_patient = RevisionPatient(day=day, id=pt_count, env=self.env,
                                                       args=self.args, event_log=self.event_log)
                self.cum_revision_patients.append(new_revision_patient)
                self.revision_patients.append(new_revision_patient)
                #for debugging
                self.revision_patients_id.append(new_revision_patient.id)
                trace(f'revision patient {pt_count} arrived on day {day:.3f}')
                self.env.process(new_revision_patient.service())
                pt_count += 1
                trace(f'revision ids: {self.revision_patients_id}')
            yield self.env.timeout(1)
            self.revision_patients *= 0
