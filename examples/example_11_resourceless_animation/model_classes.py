'''

Classes and functions for the scheduling example lab.
This is used to build a model of the queuing and scheduling
at a mental health assessment network across in Devon

'''

import pandas as pd
import numpy as np
import itertools
import simpy
import math

from sim_tools.distributions import Bernoulli, Poisson

class Discrete:
    """
    Encapsulates a discrete distribution
    """
    def __init__(self, elements, probabilities, random_seed=None):
        self.elements = elements
        self.probabilities = probabilities

        self.validate_lengths(elements, probabilities)
        self.validate_probs(probabilities)

        self.cum_probs = np.add.accumulate(probabilities)

        self.rng = np.random.default_rng(random_seed)


    def validate_lengths(self, elements, probs):
        if (len(elements) != len(probs)):
            raise ValueError('Elements and probilities arguments must be of the same length')

    def validate_probs(self, probs):
        if not math.isclose(sum(probs), 1.0):
            raise ValueError('Probabilities must sum to 1')

    def sample(self, size=None):
        return self.elements[np.digitize(self.rng.random(size), self.cum_probs)]


def generate_seed_vector(one_seed_to_rule_them_all=42, size=20):
    '''
    Return a controllable numpy array
    of integer seeds to use in simulation model.

    Values are between 1000 and 10^10

    Params:
    ------
    one_seed_to_rule_them_all: int, optional (default=42)
        seed to produce the seed vector

    size: int, optional (default=20)
        length of seed vector
    '''
    rng = np.random.default_rng(seed=one_seed_to_rule_them_all)
    return rng.integers(low=1000, high=10**10, size=size)

ANNUAL_DEMAND = 16328
LOW_PRIORITY_MIN_WAIT = 3
HIGH_PRIORITY_MIN_WAIT = 1

PROP_HIGH_PRORITY= 0.15
PROP_CARVE_OUT = 0.15

#target in working days
TARGET_HIGH = 5
TARGET_LOW = 20

class Clinic():
    '''
    A clinic has a probability of refering patients
    to another service after triage.
    '''
    def __init__(self, prob_referral_out, random_seed=None):

        #prob patient is referred to another service
        self.prob_referral_out = prob_referral_out
        self.ref_out_dist = Bernoulli(prob_referral_out, random_seed)

class Scenario():
    '''
    Arguments represent a configuration of the simulation model.
    '''
    def __init__(self, run_length, warm_up=0.0, pooling=False, prop_carve_out=0.15,
                 demand_file=None, slots_file=None, pooling_file=None,
                 seeds=None):

        if seeds is None:
            self.seeds = [None for i in range(100)]
        else:
            self.seeds = seeds

        #use default files?
        if pooling_file is None:
            pooling_file = pd.read_csv('data/partial_pooling.csv')

        if demand_file is None:
            demand_file = pd.read_csv('data/referrals.csv')

        if slots_file is None:
            slots_file = pd.read_csv('data/shifts.csv')

        #useful if you want to record anything during a model run.
        self.debug = []

        #run length and warm up period
        self.run_length = run_length
        self.warm_up_period = warm_up

        #should we pool clinics?
        self.pooling = pooling

        #proportion of carve out used
        self.prop_carve_out = prop_carve_out

        #input data from files
        self.clinic_demand = demand_file
        self.weekly_slots = slots_file
        self.pooling_np = pooling_file.to_numpy().T[1:].T

        #These represent the 'diaries' of bookings

        # 1. carve out
        self.carve_out_slots = self.create_carve_out(run_length,
                                                     self.weekly_slots)

        # 2. available slots and one for the bookings.
        self.available_slots = self.create_slots(self.run_length,
                                                 self.weekly_slots)

        # 3. the bookings which can be used to calculate slot utilisation
        self.bookings = self.create_bookings(self.run_length,
                                             len(self.weekly_slots.columns))

        #sampling distributions
        self.arrival_dist = Poisson(ANNUAL_DEMAND / 52 / 5,
                                    random_seed=self.seeds[0])
        self.priority_dist = Bernoulli(PROP_HIGH_PRORITY,
                                       random_seed=self.seeds[1])

        #create a distribution for sampling a patients local clinic.
        elements = [i for i in range(len(self.clinic_demand))]
        probs = self.clinic_demand['prop'].to_numpy()
        self.clinic_dist = Discrete(elements, probs, random_seed=self.seeds[2])

        #create a list of clinic objects
        self.clinics = []
        for i in range(len(self.clinic_demand)):
            clinic = Clinic(self.clinic_demand['referred_out'].iloc[i],
                            random_seed=self.seeds[i+3])
            self.clinics.append(clinic)

    def create_carve_out(self, run_length, capacity_template):

        #proportion of total capacity carved out for high priority patients
        priority_template = (capacity_template * self.prop_carve_out).round().astype(np.uint8)

        priority_slots = priority_template.copy()

        #longer than run length as patients will need to book ahead
        for day in range(int(run_length*1.5)):
            priority_slots = pd.concat([priority_slots, priority_template.copy()],
                                        ignore_index=True)

        priority_slots.index.rename('day', inplace=True)
        return priority_slots

    def create_slots(self, run_length, capacity_template):

        priority_template = (capacity_template * self.prop_carve_out).round().astype(np.uint8)
        open_template = capacity_template - priority_template
        available_slots = open_template.copy()

        #longer than run length as patients will need to book ahead
        for day in range(int(run_length*1.5)):
            available_slots = pd.concat([available_slots, open_template.copy()],
                                         ignore_index=True)

        available_slots.index.rename('day', inplace=True)
        return available_slots

    def create_bookings(self, run_length, clinics):
        bookings = np.zeros(shape=(5, clinics), dtype=np.uint8)

        columns = [f'clinic_{i}' for i in range(1, clinics+1)]
        bookings_template = pd.DataFrame(bookings, columns=columns)

        bookings = bookings_template.copy()

        #longer than run length as patients will need to book ahead
        for day in range(int(run_length*1.5)):
            bookings = pd.concat([bookings, bookings_template.copy()],
                                 ignore_index=True)

        bookings.index.rename('day', inplace=True)
        return bookings

class LowPriorityPooledBooker():
    '''
    Low prioity booking process for POOLED clinics.

    Low priority patients only have access to public slots and have a minimum
    waiting time (e.g. 3 days before a slot can be used.)
    '''
    def __init__(self, args):
        self.args = args
        self.min_wait = LOW_PRIORITY_MIN_WAIT
        self.priority = 1


    def find_slot(self, t, clinic_id):
        '''
        Finds a slot in a diary of available slot

        NUMPY IMPLEMENTATION.

        Params:
        ------
        t: int,
            time t in days

        clinic_id: int
            home clinic id is the index  of the clinic column in diary

        Returns:
        -------
        (int, int)
        (best_t, best_clinic_id)

        '''
        #to reduce runtime - drop down to numpy...
        available_slots_np = self.args.available_slots.to_numpy()

        #get the clinics that are pooled with this one.
        clinic_options = np.where(self.args.pooling_np[clinic_id] == 1)[0]

        #get the clinic slots t+min_wait forward for the pooled clinics
        clinic_slots = available_slots_np[t+self.min_wait:, clinic_options]

        #get the earliest day number (its the name of the series)
        best_t = np.where((clinic_slots.sum(axis=1) > 0))[0][0]

        #get the index of the best clinic option.
        best_clinic_idx = clinic_options[clinic_slots[best_t, :] > 0][0]

        #return (best_t, booked_clinic_id)
        return best_t + self.min_wait + t, best_clinic_idx


    def book_slot(self, booking_t, clinic_id):
        '''
        Book a slot on day t for clinic c

        A slot is removed from args.available_slots
        A appointment is recorded in args.bookings.iat

        Params:
        ------
        booking_t: int
            Day of booking

        clinic_id: int
            the clinic identifier
        '''
        #one less public available slot
        self.args.available_slots.iat[booking_t, clinic_id] -= 1

        #one more patient waiting
        self.args.bookings.iat[booking_t, clinic_id] += 1

class HighPriorityBooker():
    '''
    High prioity booking process

    High priority patients are a minority, but require urgent access to services.
    They booking process has access to public slots and carve out slots.  High
    priority patient still have a delay before booking, but this is typically
    small e.g. next day slots.
    '''
    def __init__(self, args):
        '''
        Constructor

        Params:
        ------
        args: Scenario
            simulation input parameters including the booking sheets
        '''
        self.args = args
        self.min_wait = 1
        self.priority = 2

    def find_slot(self, t, clinic_id):
        '''
        Finds a slot in a diary of available slots

        High priority patients have access to both
        public slots and carve out reserved slots.

        Params:
        ------
        t: int,
            time t in days

        clinic_id: int
            clinic id is the index  of the clinic column in diary

        Returns:
        -------
        (int, int)
        (best_t, best_clinic_id)
        '''

        #to reduce runtime - maybe...
        available_slots_np = self.args.available_slots.to_numpy()
        carve_out_slots_np = self.args.carve_out_slots.to_numpy()

        #get the clinic slots from t+min_wait days forward
        #priority slots
        priority_slots = carve_out_slots_np[t+self.min_wait:, clinic_id]

        #public slots
        public_slots = available_slots_np[t+self.min_wait:, clinic_id]

        #total slots
        clinic_slots = priority_slots + public_slots

        #(best_t, best_clinic_id)
        return np.argmax(clinic_slots > 0) + self.min_wait + t, clinic_id

    def book_slot(self, booking_t, clinic_id):
        '''
        Book a slot on day t for clinic c

        A slot is removed from args.carve_out_slots or
        args.available_slots if required.

        A appointment is recorded in args.bookings.iat

        Params:
        ------
        booking_t: int
            Day of booking

        clinic_id: int
            the clinic identifier

        '''
        #take carve out slot first
        if self.args.carve_out_slots.iat[booking_t, clinic_id] > 0:
            self.args.carve_out_slots.iat[booking_t, clinic_id] -= 1
        else:
            #one less public available slot
            self.args.available_slots.iat[booking_t, clinic_id] -= 1

        #one more booking...
        self.args.bookings.iat[booking_t, clinic_id] += 1

class LowPriorityBooker():
    '''
    Low prioity booking process

    Low priority patients only have access to public slots and have a minimum
    waiting time (e.g. 3 days before a slot can be used.)
    '''
    def __init__(self, args):
        self.args = args
        self.min_wait = LOW_PRIORITY_MIN_WAIT
        self.priority = 1

    def find_slot(self, t, clinic_id):
        '''
        Finds a slot in a diary of available slot

        Params:
        ------
        t: int,
            time t in days

        clinic_id: int
            clinic id is the index  of the clinic column in diary

        Returns:
        -------
        (int, int)
        (best_t, best_clinic_id)
        '''
        #to reduce runtime drop from pandas to numpy
        available_slots_np = self.args.available_slots.to_numpy()

        #get the clinic slots t+min_wait forward for the pooled clinics
        clinic_slots = available_slots_np[t+self.min_wait:, clinic_id]

        # return (best_t, best_clinic_id)
        return np.argmax(clinic_slots > 0) + self.min_wait + t, clinic_id


    def book_slot(self, booking_t, clinic_id):
        '''
        Book a slot on day t for clinic c

        A slot is removed from args.available_slots
        A appointment is recorded in args.bookings.iat

        Params:
        ------
        booking_t: int
            Day of booking

        clinic_id: int
            the clinic identifier
        '''
        #one less public available slot
        self.args.available_slots.iat[booking_t, clinic_id] -= 1

        #one more patient waiting
        self.args.bookings.iat[booking_t, clinic_id] += 1

class HighPriorityPooledBooker():
    '''
    High prioity booking process for POOLED clinics.

    High priority patients have access to public and reserved
    slots and have a minimum waiting time (e.g. 1 days before a
    slot can be used.)
    '''
    def __init__(self, args):
        self.args = args
        self.min_wait = 1
        self.priority = 2


    def find_slot(self, t, clinic_id):
        '''
        Finds a slot in a diary of available slot

        NUMPY IMPLEMENTATION.

        Params:
        ------
        t: int,
            time t in days

        clinic_id: int
            home clinic id is the index  of the clinic column in diary

        Returns:
        -------
        (int, int)
        (best_t, best_clinic_id)

        '''
        #to reduce runtime - drop down to numpy...
        available_slots_np = self.args.available_slots.to_numpy()
        carve_out_slots_np = self.args.carve_out_slots.to_numpy()

        #get the clinics that are pooled with this one.
        clinic_options = np.where(self.args.pooling_np[clinic_id] == 1)[0]

        #get the clinic slots t+min_wait forward for the pooled clinics
        public_slots = available_slots_np[t+self.min_wait:, clinic_options]
        priority_slots = carve_out_slots_np[t+self.min_wait:, clinic_options]

        #total slots
        clinic_slots = priority_slots + public_slots

        #get the earliest day number (its the name of the series)
        best_t = np.where((clinic_slots.sum(axis=1) > 0))[0][0]

        #get the index of the best clinic option.
        best_clinic_idx = clinic_options[clinic_slots[best_t, :] > 0][0]

        #return (best_t, best_clinic_id)
        return best_t + self.min_wait + t, best_clinic_idx


    def book_slot(self, booking_t, clinic_id):
        '''
        Book a slot on day t for clinic c

        A slot is removed from args.available_slots
        A appointment is recorded in args.bookings.iat

        Params:
        ------
        booking_t: int
            Day of booking

        clinic_id: int
            the clinic identifier
        '''
        #take carve out slot first
        if self.args.carve_out_slots.iat[booking_t, clinic_id] > 0:
            self.args.carve_out_slots.iat[booking_t, clinic_id] -= 1
        else:
            #one less public available slot
            self.args.available_slots.iat[booking_t, clinic_id] -= 1

        #one more booking...
        self.args.bookings.iat[booking_t, clinic_id] += 1

class PatientReferral(object):
    '''
    Patient referral process

    Find an appropraite asessment slot for the patient.
    Schedule an assessment for that day.

    '''
    def __init__(self, env, args, referral_t, home_clinic, booker, event_log, identifier):
        self.env = env
        self.args = args
        self.referral_t = referral_t
        self.home_clinic = home_clinic
        self.booked_clinic = home_clinic
        self.booker = booker
        self.event_log = event_log
        self.identifier = identifier


        #performance metrics
        self.waiting_time = None

    @property
    def priority(self):
        '''
        Return the priority of the patient booking
        '''
        return self.booker.priority

    def execute(self):
        '''
        Patient is referred to clinic

        1. find earliest slot within rules
        2. book slot at clinic
        3. schedule process to complete at that time
        '''
        self.event_log.append(
            {'patient': self.identifier,
             'pathway': self.priority,
             'event_type': 'arrival_departure',
             'event': 'arrival',
             'home_clinic': int(self.home_clinic),
             'time': self.env.now}
        )


        #get slot for clinic
        best_t, self.booked_clinic = \
            self.booker.find_slot(self.referral_t, self.home_clinic)

        #book slot at clinic = time of referral + waiting_time
        self.booker.book_slot(best_t, self.booked_clinic)

        self.event_log.append(
            {'patient': self.identifier,
             'pathway': self.priority,
             'event_type': 'queue',
             'event': 'appointment_booked_waiting',
             'booked_clinic': int(self.booked_clinic),
             'home_clinic': int(self.home_clinic),
             'time': self.env.now
             }
        )

        #wait for appointment
        yield self.env.timeout(best_t - self.referral_t)

        # measure waiting time on day of appointment
        #(could also record this before appointment, but leaving until
        #afterwards allows modifications where patients can be moved)
        self.waiting_time = best_t - self.referral_t

        # Use appointment
        self.event_log.append(
            {'patient': self.identifier,
             'pathway': self.priority,
             'event_type': 'queue',
             'event': 'have_appointment',
             'booked_clinic': int(self.booked_clinic),
             'home_clinic': int(self.home_clinic),
             'time': self.env.now,
             'wait': self.waiting_time
             }
        )

        self.event_log.append(
            {'patient': self.identifier,
             'pathway': self.priority,
             'event_type': 'arrival_departure',
             'event': 'depart',
             'home_clinic': int(self.home_clinic),
             'time': self.env.now+1}
        )



class AssessmentReferralModel(object):
    '''
    Implements the Mental Wellbeing and Access 'Assessment Referral'
    model in Pitt, Monks and Allen (2015). https://bit.ly/3j8OH6y

    Patients arrive at random and in proportion to the regional team.

    Patients may be seen by any team identified by a pooling matrix.
    This includes limiting a patient to only be seen by their local team.

    The model reports average waiting time and can be used to compare
    full, partial and no pooling of appointments.

    '''
    def __init__(self, args):
        '''
        Constructor

        Params:
        ------

        args: Scenario
            Arguments for the simulation model

        '''
        self.env = simpy.Environment()
        self.args = args

        #list of patients referral processes
        self.referrals = []

        self.event_log = []

        #simpy processes
        self.env.process(self.generate_arrivals())

    def run(self):
        '''
        Conduct a single run of the simulation model.
        '''
        self.env.run(self.args.run_length)
        self.process_run_results()

    def generate_arrivals(self):
        '''
        Time slicing simulation.  The model steps forward by a single
        day and simulates the number of arrivals from a Poisson
        distribution.  The following process is then applied.

        1. Sample the region of the referral from a Poisson distribution
        2. Triage - is an appointment made for the patient or are they referred
        to another service?
        3. A referral process is initiated for the patient.

        '''
        #loop a day at a time.
        for t in itertools.count():

            #total number of referrals today
            n_referrals = self.args.arrival_dist.sample()

            #loop through all referrals recieved that day
            for i in range(n_referrals):
                #sample clinic based on empirical proportions
                clinic_id = self.args.clinic_dist.sample()
                clinic = self.args.clinics[clinic_id]

                #triage patient and refer out of system if appropraite
                referred_out = clinic.ref_out_dist.sample()

                #if patient is accepted to clinic
                if referred_out == 0:

                    #is patient high priority?
                    high_priority = self.args.priority_dist.sample()

                    if high_priority == 1:
                        #different policy if pooling or not
                        if self.args.pooling:
                            booker = HighPriorityPooledBooker(self.args)
                        else:
                            booker = HighPriorityBooker(self.args)
                    else:
                        #different policy if pooling or not
                        if self.args.pooling:
                            booker = LowPriorityPooledBooker(self.args)
                        else:
                            booker = LowPriorityBooker(self.args)

                    #create instance of PatientReferral
                    patient = PatientReferral(self.env, self.args, t,
                                              clinic_id, booker, self.event_log, f"{t}_{i}")

                    #start a referral assessment process for patient.
                    self.env.process(patient.execute())

                    #only collect results after warm-up complete
                    if self.env.now > self.args.warm_up_period:
                        #store patient for calculating waiting time stats at end
                        self.referrals.append(patient)

                # Add event logging for patients triaged and referred out
                if referred_out == 1:
                    self.event_log.append(
                        {'patient': f"{t}_{i}",
                        'pathway': "Unsuitable for service",
                        'event_type': 'arrival_departure',
                        'event': 'arrival',
                        'home_clinic': int(clinic_id),
                        'time': self.env.now
                        }
                    )

                    self.event_log.append(
                        {'patient': f"{t}_{i}",
                        'pathway': "Unsuitable for service",
                        'event_type': 'queue',
                        'event': f'referred_out_{clinic_id}',
                        'home_clinic': int(clinic_id),
                        'time': self.env.now
                        }
                    )

                    self.event_log.append(
                        {'patient': f"{t}_{i}",
                        'pathway': "Unsuitable for service",
                        'event_type': 'arrival_departure',
                        'event': 'depart',
                        'home_clinic': int(clinic_id),
                        'time': self.env.now + 1
                        }
                    )

            #timestep by one day
            yield self.env.timeout(1)

    def process_run_results(self):
        '''
        Produce summary results split by priority...
        '''

        results_all = [p.waiting_time for p in self.referrals
               if not p.waiting_time is None]

        results_low = [p.waiting_time for p in self.referrals
                       if not (p.waiting_time is None) and p.priority == 1]

        results_high = [p.waiting_time for p in self.referrals
                       if (not p.waiting_time is None) and p.priority == 2]

        self.results_all = results_all
        self.results_low = results_low
        self.results_high = results_high
