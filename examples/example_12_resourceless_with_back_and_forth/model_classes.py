'''

Classes and functions for the scheduling example lab.
This is used to build a model of the queuing and scheduling
at a mental health assessment network across in Devon

'''
import pandas as pd
import numpy as np
import itertools
import simpy
import random
import queue
from dataclasses import dataclass, field
from typing import Any
import math

from sim_tools.distributions import Bernoulli, Poisson, Lognormal

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


@dataclass(order=True)
class PrioritizedItem:
    priority: int
    item: Any=field(compare=False)

def trace(msg):
    '''
    Utility function for traceing a trace as the
    simulation model executes.
    Set the TRACE constant to False, to turn tracing off.

    Params:
    -------
    msg: str
        string to trace to screen.
    '''
    if TRACE:
        trace(msg)

TRACE = False


def generate_seed_vector(one_seed_to_rule_them_all=42, size=30):
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

ANNUAL_DEMAND = 1500
LOW_PRIORITY_MIN_WAIT = 7
HIGH_PRIORITY_MIN_WAIT = 2

PROP_HIGH_PRIORITY= 0.15
PROP_CARVE_OUT = 0.15

# What proportion of people initially graded as *high* priority
# go on to have ongoing appointments?
PROP_HIGH_PRIORITY_ONGOING_APPOINTMENTS = 0.95

# What proportion of people initially graded as *low* priority
# go on to have ongoing appointments?
PROP_LOW_PRIORITY_ONGOING_APPOINTMENTS = 0.8

# What proportion of people initially graded as *high*
# priority go on to have high intensity therapy?
PROP_HIGH_PRIORITY_HIGH_INTENSITY = 0.7
# What proportion of people initially graded as *low*
# priority go on to have high intensity therapy?
PROP_LOW_PRIORITY_HIGH_INTENSITY = 0.2

MEAN_FOLLOW_UPS_HIGH_INTENSITY = 10
SD_FOLLOW_UPS_HIGH_INTENSITY = 6
MEAN_FOLLOW_UPS_LOW_INTENSITY = 6
SD_FOLLOW_UPS_LOW_INTENSITY = 3

LOW_INTENSITY_FOLLOW_UP_TARGET_INTERVAL = 14
HIGH_INTENSITY_FOLLOW_UP_TARGET_INTERVAL = 7

#targets in working days
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
    def __init__(self,
                 run_length,
                 warm_up=0.0,
                 prop_carve_out=0.0,
                 demand_file=None,
                 slots_file=None,
                 pooling_file=None,
                 existing_caseload_file=None,
                 annual_demand=ANNUAL_DEMAND,
                 prop_high_priority=PROP_HIGH_PRIORITY,
                 prop_high_priority_ongoing_appointments=PROP_HIGH_PRIORITY_ONGOING_APPOINTMENTS,
                 prop_low_priority_ongoing_appointments=PROP_LOW_PRIORITY_ONGOING_APPOINTMENTS,
                 prop_high_priority_assessed_high_intensity=PROP_HIGH_PRIORITY_HIGH_INTENSITY,
                 prop_low_priority_assessed_high_intensity=PROP_LOW_PRIORITY_HIGH_INTENSITY,
                 mean_follow_ups_high_intensity=MEAN_FOLLOW_UPS_HIGH_INTENSITY,
                 sd_follow_ups_high_intensity=SD_FOLLOW_UPS_HIGH_INTENSITY,
                 mean_follow_ups_low_intensity=MEAN_FOLLOW_UPS_LOW_INTENSITY,
                 sd_follow_ups_low_intensity=SD_FOLLOW_UPS_LOW_INTENSITY,
                 caseload_multiplier=1,
                 prop_referred_out=0.12,
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

        if existing_caseload_file is None:
            existing_caseload_file = pd.read_csv('data/caseload.csv')

        #useful if you want to record anything during a model run.
        self.debug = []

        #run length and warm up period
        self.run_length = run_length
        self.warm_up_period = warm_up

        #should we pool clinics?
        self.pooling = True

        # What multiplier should we apply to caseload?
        # Increasing this may mean more effective utilisation of slots
        # because it prompt bookings to be made before clients are removed
        # from caseload so caseload numbers don't drop too far below the
        # optimum
        self.caseload_multiplier = caseload_multiplier

        #proportion of carve out used
        self.prop_carve_out = prop_carve_out

        self.prop_referred_out = prop_referred_out

        #input data from files
        self.clinic_demand = demand_file
        self.weekly_slots = slots_file
        self.pooling_np = pooling_file.to_numpy().T[1:].T
        self.existing_caseload = existing_caseload_file.iloc[0,]

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
        # Arrival rate of patients to the service
        self.arrival_dist = Poisson(annual_demand / 52 / 5,
                                    random_seed=self.seeds[0])
        # Initial priority setting for assessment
        self.priority_dist = Bernoulli(prop_high_priority,
                                       random_seed=self.seeds[1])

        # Determining whether people will have follow-up appointments
        self.follow_up_dist_high_priority = Bernoulli(
            prop_high_priority_ongoing_appointments,
            random_seed=self.seeds[2]
            )
        self.follow_up_dist_low_priority = Bernoulli(
            prop_low_priority_ongoing_appointments,
            random_seed=self.seeds[3]
            )

        # Setting intensity (frequency) of follow-up appointments
        self.intensity_dist_high_priority = Bernoulli(
            prop_high_priority_assessed_high_intensity,
            random_seed=self.seeds[4]
            )
        self.intensity_dist_low_priority = Bernoulli(
            prop_low_priority_assessed_high_intensity,
            random_seed=self.seeds[5]
            )

        # Setting number of follow up appointments - high intensity
        self.num_follow_up_dist_high_intensity = Lognormal(
            mean=mean_follow_ups_high_intensity,
            stdev=sd_follow_ups_high_intensity,
            random_seed=self.seeds[6]
            )

        self.num_follow_up_dist_low_intensity = Lognormal(
            mean=mean_follow_ups_low_intensity,
            stdev=sd_follow_ups_low_intensity,
            random_seed=self.seeds[7]
            )


        #create a distribution for sampling a patients local clinic.
        elements = [i for i in range(len(self.clinic_demand))]
        probs = self.clinic_demand['prop'].to_numpy()
        self.clinic_dist = Discrete(elements, probs, random_seed=self.seeds[8])

        #create a list of clinic objects
        self.clinics = []
        for i in range(len(self.clinic_demand)):
            clinic = Clinic(self.prop_referred_out,
                            random_seed=self.seeds[i+9])
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


    def find_slot(self, t, clinic_id,
                  limit_clinic_choice = None):
        '''
        Finds a slot in a diary of available slots

        NUMPY IMPLEMENTATION.

        Params:
        ------
        t: int,
            time t in days

        clinic_id: int
            home clinic id is the index  of the clinic column in diary

        limit_clinic_choice: list
            mask (list of True/False per clinic index) for clinics to allow
            additional filtering at time of booking over and above standard pooling

        Returns:
        -------
        (int, int)
        (best_t, best_clinic_id)

        '''
        #to reduce runtime - drop down from pandas df to numpy...
        available_slots_np = self.args.available_slots.to_numpy()

        #get the clinics that are pooled with this one.

        # Note that this is a leftover from when this model was clinic-level instead of
        # clinician level - however, it was much quicker to just set it up so that
        # for the initial appointment, everyone was pooled with everyone else using
        # the pooling file, rather than rewriting the model to change the logic of
        # patient arrivals. This is why this code and reference to pooling in places
        # might feel a bit strange - looking at ex_4_community will help you understand
        # why it's like this and why that option is very useful in other contexts.
        # In short - this works fine and it's not worth rewriting in this instance!

        if (limit_clinic_choice is not None) and (not any(limit_clinic_choice)):
            raise AssertionError("Booking code triggered when no clinics have slots available - check prior logic")

        # trace(self.args.pooling_np)
        # trace(clinic_id)
        # TODO: CONFIRM WHETHER ADDING IN -1 TO CLINIC ID HERE IS APPROPRIATE
        clinic_options = np.where(self.args.pooling_np[clinic_id] == 1)[0]
        trace(f"Clinic options: {clinic_options}")

        # Then mask further by those with availability
        # The booking code should never be triggered if the total available
        # clinicians/clinics after limiting choice with this mask is an empty
        # array
        if limit_clinic_choice is not None:
            clinic_options = clinic_options[limit_clinic_choice]
            trace(f"Clinic options after additional filtering: {clinic_options}")

        #get the clinic slots t+min_wait forward for the pooled clinics
        clinic_slots = available_slots_np[t+self.min_wait:, clinic_options]

        #get the earliest day number (its the name of the series)
        best_t = np.where((clinic_slots.sum(axis=1) > 0))[0][0]

        #get the index of the best clinic option.
        # To ensure it's not always the first available clinician with availability
        # (as this can lead to odd behaviour with e.g. clinicians earlier in the list
        # getting all of the emergency patients when multiple clinicians have availability
        # on the same day)
        clinic_sample = random.randint(0, len(clinic_options[clinic_slots[best_t, :] > 0])-1)

        best_clinic_idx = clinic_options[clinic_slots[best_t, :] > 0][clinic_sample]

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


    def find_slot(self, t,
                  clinic_id,
                  limit_clinic_choice = None):
        '''
        Finds a slot in a diary of available slot

        NUMPY IMPLEMENTATION.

        Params:
        ------
        t: int,
            time t in days

        clinic_id: int
            home clinic id is the index  of the clinic column in diary

        limit_clinic_choice: list
            mask (list of true false per clinic index) for clinics to allow
            additional filtering at time of booking over and above standard pooling

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
        # Then mask further by those with availability
        clinic_options = clinic_options[limit_clinic_choice]

        #get the clinic slots t+min_wait forward for the pooled clinics
        public_slots = available_slots_np[t+self.min_wait:, clinic_options]
        priority_slots = carve_out_slots_np[t+self.min_wait:, clinic_options]

        #total slots
        clinic_slots = priority_slots + public_slots

        #get the earliest day number (its the name of the series)
        best_t = np.where((clinic_slots.sum(axis=1) > 0))[0][0]

        #get the index of the best clinic option.
        # To ensure it's not always the first available clinician with availability
        # (as this can lead to odd behaviour with e.g. clinicians earlier in the list
        # getting all of the emergency patients when multiple clinicians have availability
        # on the same day)
        clinic_sample = random.randint(0, len(clinic_options[clinic_slots[best_t, :] > 0])-1)

        best_clinic_idx = clinic_options[clinic_slots[best_t, :] > 0][clinic_sample]

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

class RepeatBooker():
    '''
    Repeat Booking for clients who need to be seen at a high frequency
    (weekly)

    Set the minimum wait to be one day fewer

    clinic_id: int
        the clinic identifier
    '''
    def __init__(self, args, ideal_frequency, clinic_id):
        self.args = args
        self.ideal_frequency = ideal_frequency
        self.clinic_id = clinic_id
        # Set minimum wait to 1 day fewer than stated ideal frequency
        self.min_wait = ideal_frequency - 1
        self.priority = 1

    def find_slot(self, t):
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
        clinic_slots = available_slots_np[t+self.min_wait:, self.clinic_id]

        # return (best_t, best_clinic_id)
        return np.argmax(clinic_slots > 0) + self.min_wait + t, self.clinic_id


    def book_slot(self, booking_t):
        '''
        Book a slot on day t for clinic c

        A slot is removed from args.available_slots
        A appointment is recorded in args.bookings.iat

        Params:
        ------
        booking_t: int
            Day of booking
        '''
        #one less public available slot
        self.args.available_slots.iat[booking_t, self.clinic_id] -= 1

        #one more patient waiting
        self.args.bookings.iat[booking_t, self.clinic_id] += 1




class PatientReferral(object):
    '''
    Patient referral process

    Find an appropraite asessment slot for the patient.
    Schedule an assessment for that day.

    '''
    def __init__(self, env, args, referral_t, home_clinic,
                 booker, arrival_number,
                 event_log, identifier, wait_store):
        self.env = env
        self.args = args
        self.referral_t = referral_t
        self.assessment_t = None
        self.home_clinic = home_clinic
        self.booked_clinic = home_clinic
        self.wait_store = wait_store

        self.booker = booker

        self.event_log = event_log
        self.identifier = identifier

        self.arrival_day = identifier.split('_')[0]
        self.arrival_order_within_day = identifier.split('_')[1]
        self.arrival_number = arrival_number

        #performance metrics
        self.waiting_time = None
        self.num_appts = None

        self.follow_up_intensity = None

    @property
    def priority(self):
        '''
        Return the priority of the patient booking
        '''
        return self.booker.priority

    def execute_referral(self):
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

        # self.event_log.append(
        #         {'patient': self.identifier,
        #         'pathway': self.priority,
        #         'event_type': 'queue',
        #         'event': 'waiting_appointment_to_be_scheduled',
        #         'home_clinic': int(self.home_clinic),
        #         'time': self.env.now
        #         }
        #     )

        #########################
        # Low Priority Patients
        #########################

        # if priority is low, put into a store so they can wait to be dealt with by
        # a process that will check whether the clinician has availability to take
        # an additional client onto their caseload (using the caseload tracking csv,
        # which is updated as patients join/leave caseload)
        # if all clinicians caseloads are full, the process wait one day, and then check again
        # This is to try and prevent the books becoming overfull, leading to gaps that are too long
        # between regular appointments
        if self.priority == 1:
            # PUT THEM IN THE STORE AND GO TO THE NEXT PROCESS
            trace(f"Standard Referral {self.identifier} - Putting into referral queue")

            # Priority queue doesn't have order stability within priorities, so important to set priority
            # in such a way that everyone has their own distinct priority that will put them in the correct point
            # in the queue
            self.wait_store.put(PrioritizedItem(self.arrival_number+1000000, self), block=False)
            # Once they are in the store, the simulation will check once every day how many people can be taken
            # out of the store and booked in for their assessment and ongoing regular appointments

        #########################
        # High Priority Patients
        #########################

        # If priority is high, put to front of referral queue
        if self.priority == 2:
            # PUT THEM IN THE STORE AND GO TO THE NEXT PROCESS
            trace(f"Urgent Referral {self.identifier} - Putting to front of referral queue")
            # Lower numbers go to the front of the queue
            self.wait_store.put(PrioritizedItem(self.arrival_number, self), block=False)

        self.event_log.append(
                {'patient': self.identifier,
                'pathway': self.priority,
                'event_type': 'queue',
                'event': 'waiting_appointment_to_be_scheduled',
                'booked_clinic': int(self.booked_clinic),
                'home_clinic': int(self.home_clinic),
                'time': self.env.now
                }
            )

    def execute_assessment_booking(self):

        def get_available_clinicians():
            # First calculate each clinician's theoretical maximum from the slots file
            # TODO: Consdier whether to floor
            caseload_slots_per_clinician = np.floor((self.args.weekly_slots).sum().to_numpy().T * self.args.caseload_multiplier)
            trace(f"Adjusted slots: {caseload_slots_per_clinician}")
            # caseload_slots_per_clinician = (self.args.weekly_slots).sum().to_numpy().T
            # Then we subtract one from the other to get the available slots
            # Then subtract one from the theoretical maximum because we want to leave headroom
            # for emergency clients
            # available_caseload = (
            #     caseload_slots_per_clinician - self.args.existing_caseload.tolist()[1:]
            #     )- 1
            available_caseload = (
                caseload_slots_per_clinician - self.args.existing_caseload.tolist()[1:]
                )
            #print(f"Checking available clinicians when booking assessment appointment. " \
            #      f"Caseload slots available: {sum([c if c>0 else 0 for c in available_caseload])} ({available_caseload})")
            # trace(f"Total theoretical caseload: {caseload_slots_per_clinician}")
            # #print(f"Total current caseload per clinician: {self.args.existing_caseload.tolist()[1:]}")
            clinicians_with_slots = [True if c >= 0.5 else False for c in available_caseload]
            return clinicians_with_slots

        #get slot for clinic
        if self.priority == 2:
            self.assessment_t, self.booked_clinic = self.booker.find_slot(
                self.env.now, self.home_clinic,
                )

        # if non-urgent, we will have previously checked that there is some availability
        else:
            got_slots = get_available_clinicians()
            trace(f"Clinicians with slots for patient {self.identifier}: {got_slots}")
            self.assessment_t, self.booked_clinic = self.booker.find_slot(
                self.env.now, self.home_clinic,
                # Limit clinic choice here to clinicians with capacity
                limit_clinic_choice = got_slots
                )
            # self.booker.find_slot(self.referral_t, self.home_clinic)


        #book slot at clinic = time of referral + waiting_time
        self.booker.book_slot(self.assessment_t, self.booked_clinic)

        trace(f"client {self.identifier} (priority: {self.priority}): referred on" \
              f" {self.referral_t}, seized booking with clinician {self.booked_clinic}" \
              f" on day {self.assessment_t} at day {self.env.now}" \
              f" (Assessment wait: {self.assessment_t - self.env.now} days," \
              f" booking wait {(self.env.now - self.referral_t)} days)")

        self.event_log.append(
            {'patient': self.identifier,
            'pathway': self.priority,
            'event_type': 'queue',
            'event': 'appointment_booked_waiting',
            'booked_clinic': int(self.booked_clinic),
            'home_clinic': int(self.home_clinic),
            'time': self.env.now,
            'assessment_booking_wait': (self.env.now - self.referral_t)
            }
        )

        # Update the caseload file for the clinician they've been booked in with
        # At this point we don't know whether they'll be high or low intensity going forwards
        # but most high priority patients go on to be high intensity, so adjust the
        # caseload accordingly - we can always adjust that if they are deemed to be low
        # frequency after their assessment appointment
        if self.priority == 2:
            self.args.existing_caseload[1:].iloc[int(self.booked_clinic)] += 1
         # If they are low priority chances are they'll be low intensity, so adjust
        # the booked clinician's available caseload figures accordingly
        elif self.priority == 1:
            self.args.existing_caseload[1:].iloc[int(self.booked_clinic)] += 0.5
        else:
            trace(f"Error - unknown priority value passed for patient {self.identifier}" \
                  f" ({self.priority})")

        # Pass client to process where they will wait for the assessment appointment
        # to take place
        yield self.env.process(self.execute_assessment_appointment())


    def execute_assessment_appointment(self):
        # Wait for this appointment to take place
        yield self.env.timeout(self.assessment_t - self.referral_t)

        # measure waiting time on day of appointment
        #(could also record this before appointment, but leaving until
        #afterwards allows modifications where patients can be moved)
        self.waiting_time = self.assessment_t - self.referral_t

        # Use appointment
        self.event_log.append(
            {'patient': self.identifier,
            'pathway': self.priority,
            'event_type': 'queue',
            'event': 'have_appointment',
            'booked_clinic': int(self.booked_clinic),
            'home_clinic': int(self.home_clinic),
            'type': "assessment",
            'time': self.env.now,
            'wait': self.waiting_time
            }
        )

        # Now pass them to the process for booking ongoing regular appointments
        yield self.env.process(self.ongoing_regular_appointments())
        # self.ongoing_regular_appointments()


    def ongoing_regular_appointments(self):
        # First sample whether they will have any follow-up appointments
        # Low priority likely to be low intensity
        # High priority likely to be high intensity
        if int(self.priority) == 1: # low priority
            follow_up_y = self.args.follow_up_dist_low_priority.sample()
        elif int(self.priority) == 2: # high priority
            follow_up_y = self.args.follow_up_dist_high_priority.sample()
        else:
            trace(f"Error - Unknown priority value received ({self.priority})")

        # If they don't have follow-up appointments we can remove them
        # from the caseload and they'll exit the system
        # At this stage the amount of caseload they take up will
        # have been assumed from their initial priority
        # (high priority = probably high intensity = 1 caseload slot)
        # (low priority = probably low intensity = 0.5 caseload slots)
        if not follow_up_y:
            trace(f"Client {self.identifier} (priority: {self.priority})" \
                  f" assessed as not needing ongoing service")
            self.event_log.append(
                {'patient': self.identifier,
                'pathway': self.priority,
                'event_type': 'arrival_departure',
                'event': 'depart',
                'home_clinic': int(self.home_clinic),
                'time': self.env.now+1}
            )
            #print(f"Patient {self.identifier} (priority: {self.priority}) departs after assessments without follow-ups")
            # If assessed as not needing ongoing service, we can reduce the clinician's caseload
            # which will have at this point been set based on their most likely follow-up intensity
            # (weekly for high intensity so 1 slot, fortnightly for low intensity so 0.5 slots)
            if self.priority == 2: # high
                self.args.existing_caseload[1:].iloc[int(self.booked_clinic)] -= 1
            else: # low
                self.args.existing_caseload[1:].iloc[int(self.booked_clinic)] -= 0.5

        # If they do have follow-up appointments
        # Sample whether they will need high-intensity follow-up
        # (every 7 days) or low-intensity follow-up (every 21 days)
        else:
            if int(self.priority) == 1: # low
                self.follow_up_intensity = self.args.intensity_dist_low_priority.sample()
            elif int(self.priority) == 2: # high
                self.follow_up_intensity = self.args.intensity_dist_high_priority.sample()
            else:
                trace(f"Error - Unknown priority value received ({self.priority})")
            # Output of this:
            # we count 0 as a low intensity follow-up
            # we count 1 as a high intensity follow-up

            # Adjust caseload values if expected pathway not followed
            # if high priority has low intensity follow up then we need to reduce the
            # number of caseload slots they are using from 1 to 0.5:
            if self.follow_up_intensity == 0 and int(self.priority) == 2:
                self.args.existing_caseload[1:].iloc[int(self.booked_clinic)] -= 0.5
            # if low priority has high intensity follow up then we need to up
            # the number of caseload slots they are using from 0.5 to 1:
            elif self.follow_up_intensity == 1 and int(self.priority) == 1:
                self.args.existing_caseload[1:].iloc[int(self.booked_clinic)] += 0.5
            # Otherwise caseload remains as it was set initially when they were booked in
            # for assessment
            else:
                pass

            # Now sample how many follow-up appointments they need
            if self.follow_up_intensity == 1: # high-intensity follow-up
                num_appts = int(self.args.num_follow_up_dist_high_intensity.sample())
                repeat_booker = RepeatBooker(
                    ideal_frequency=HIGH_INTENSITY_FOLLOW_UP_TARGET_INTERVAL,
                    args = self.args,
                    clinic_id=self.booked_clinic)
            else: # low-intensity follow-up
                num_appts = int(self.args.num_follow_up_dist_low_intensity.sample())
                repeat_booker = RepeatBooker(
                    args = self.args,
                    ideal_frequency=LOW_INTENSITY_FOLLOW_UP_TARGET_INTERVAL,
                    clinic_id=self.booked_clinic)

            self.num_appts = num_appts

            trace(f"Client {self.identifier} (priority: {self.priority}) assessed as needing" \
                  f" {num_appts} appointments at intensity {self.follow_up_intensity}")

            # Now we know how many appointments they will have over the total duration
            # of their interaction with the service, we can enter a loop of booking in
            # their appointment (waiting a minimum of the preferred interval - 1),
            # waiting (time elapses) until that appointment takes place, then when they
            # attend their appointment, we check the calendar and book in their next
            # appointment
            # This then just repeats as many times are required to meet the number of
            # appointments we've sampled they need
            # The alternative would have been to sample each time whether we think a
            # client is going to need an additional appointment but while this perhaps
            # more realistically reflects what's happening in practice, it is much harder
            # to then reflect the historical (or desired) spread of the number of follow-up
            # appointments people in our system have

            for i in range(num_appts):
                best_t, clinic = \
                    repeat_booker.find_slot(self.env.now)

                #book slot at clinic = time of referral + waiting_time
                repeat_booker.book_slot(best_t)

                self.event_log.append(
                    {'patient': self.identifier,
                    'pathway': self.priority,
                    'event_type': 'queue',
                    'event': 'follow_up_appointment_booked_waiting',
                    'booked_clinic': int(self.booked_clinic),
                    'home_clinic': int(self.home_clinic),
                    'follow_up': i,
                    'follow_up_intensity': 'high' if self.follow_up_intensity == 1 else 'low',
                    'follow_ups_intended': num_appts,
                    # plus one to ensure this doesn't end up preventing them from actually being
                    # at the appointment at some point
                    'time': self.env.now + 1,
                    'true_time': self.env.now
                    }
                )

                interval = best_t - self.env.now

                #wait for appointment
                yield self.env.timeout(best_t - self.env.now)

                # Use appointment
                self.event_log.append(
                    {'patient': self.identifier,
                    'pathway': self.priority,
                    'event_type': 'queue',
                    'event': 'have_appointment',
                    'booked_clinic': int(self.booked_clinic),
                    'home_clinic': int(self.home_clinic),
                    'time': self.env.now,
                    'type': "follow-up",
                    'follow_up': i,
                    'follow_up_intensity': 'high' if self.follow_up_intensity == 1 else 'low',
                    'follow_ups_intended': num_appts,
                    'interval': interval
                    }
                )

                i += 1

                # Repeat this loop until all predefined appointments have taken place

            # Once they reach this part of the code, they are leaving the system, so can
            # be removed from the caseload file
            if self.follow_up_intensity == 1: # high intensity
                self.args.existing_caseload[1:].iloc[int(self.booked_clinic)] -= 1
            elif self.follow_up_intensity == 0: # low intensity
                self.args.existing_caseload[1:].iloc[int(self.booked_clinic)] -= 0.5

            self.event_log.append(
                {'patient': self.identifier,
                'pathway': self.priority,
                'event_type': 'arrival_departure',
                'event': 'depart',
                'home_clinic': int(self.home_clinic),
                # Add 1 so that when displaying we don't prioritise departure above
                # displaying as being at an appointment (else they happen effectively
                # at the same time and this may be selected as most recent activity
                # for display)
                'time': self.env.now + 1,
                'true_time': self.env.now
                }
            )
            #print(f"Patient {self.identifier} (intensity: {self.follow_up_intensity}) departs after {num_appts} follow-ups complete")

class AssessmentReferralModel(object):
    '''
    Adapted from a model that implements the Mental Wellbeing and Access 'Assessment Referral'
    model in Pitt, Monks and Allen (2015). https://bit.ly/3j8OH6y

    In original model, patients arrive at random and in proportion to the regional team.
    Patients may be seen by any team identified by a pooling matrix.
    This includes limiting a patient to only be seen by their local team.

    In this version of the model, patients arrive roughly in line with a desired
    annual number of arrivals distribution.
    Patients may be discharged before assessment if deemed inappropriate for the service.
    While patients initially have a different 'home clinic' (due to modifying the existing model),
    this is effectively ignored and, if deemed appropriate, they are booked in with any clinician
    to begin with based on available capacity.

    Patients are classified as high or low priority on referral.
    High priority patients go to the front of a queue of patients who have not yet been booked in
    for their assessment appointment.

    When booking patient in, the total caseload of the clinicians is taken into account. The aim of this
    check is to avoid taking on too many clients relative to the number of clinical slots they have
    available per week. The max caseload defaults to the number of clinical slots (though bear in mind
    that a patient being seen every other week will take up 0.5 slots, not 1).
    1 weekly appointment = 1 caseload slot
    2 weekly appointments = 2 caseload slots (not implemented here)
    1 appointment every other week = 0.5 caseload slots
    and so on.
    The caseload can be multiplied by a factor to allow more clients to exist on caseload at any one time.

    After referral, a sampling distribution is consulted to determine whether the client is discharged at this point
    or continues on to have some number of regular repeat appointments.

    If they are going to continue, it will also be determined whether they are having high- or low-intensity therapy.
    High-priority patients are most likely to go on to high-intensity therapy (every week - 1 caseload slot) but have
    a chance of requiring low intensity.
    Low-priority patients are most likely to go on to low-intensity therapy (every other week - 0.5 caseload slots) but have
    a chance of requiring high intensity.

    A sampling distribution is then used to determine the number of follow-up appointments each patient will have, with
    different distributions used for the different intensities (and lower-intensity patients requiring fewer
    sessions on average).

    Patients will then exit the simulation after this number of appointments has elapsed.

    Various metrics are available as outputs, along with full event logs that can support animations.

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

        self.daily_caseload_snapshots = []
        self.daily_waiting_for_booking_snapshots = []

        self.init_resources()

        # simpy processes
        self.env.process(self.generate_arrivals())
        # self.env.process(self.book_new_clients_if_capacity())

    def init_resources(self):
        """
        Create a store we can keep patients in while we wait for there
        to be capacity on a clinician's caseload
        """
        # self.args.waiting_for_clinician_store = simpy.Store(self.env)
        self.args.waiting_for_clinician_store = queue.PriorityQueue()

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
        total_arrivals = 0

        for t in itertools.count():
            #print("##################")
            #print(f"# Day {t}")
            #print("##################")
            #total number of referrals today
            n_referrals = self.args.arrival_dist.sample()
            #print(f"{n_referrals} patients arrive in system")

            #loop through all referrals recieved that day
            for i in range(n_referrals):

                total_arrivals += (i+1) # plus one as will start at 0

                #sample clinic based on empirical proportions
                # hangover from model this was based on - this effectively doesn't matter here
                # as the pooling is set for clients to then be able to book in with *any* clinician
                # for their initial appointment
                # however, as doesn't have a negative impact, not worth removing!
                clinic_id = self.args.clinic_dist.sample()
                clinic = self.args.clinics[clinic_id]

                #triage patient and refer out of system if appropraite
                referred_out = clinic.ref_out_dist.sample()

                #if patient is accepted to clinic
                if referred_out == 0:

                    #is patient high priority?
                    high_priority = self.args.priority_dist.sample()

                    if high_priority == 1:
                        assessment_booker = HighPriorityPooledBooker(self.args)
                    else:
                        assessment_booker = LowPriorityPooledBooker(self.args)

                    #create instance of PatientReferral
                    patient = PatientReferral(self.env,
                                              self.args,
                                              referral_t=t,
                                              home_clinic=clinic_id,
                                              booker=assessment_booker,
                                              event_log=self.event_log,
                                              identifier=f"{t}_{i}",
                                              arrival_number=total_arrivals,
                                              wait_store=self.args.waiting_for_clinician_store)

                    #start a referral assessment process for patient.
                    # self.env.process(patient.execute_referral())
                    patient.execute_referral()

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
                    trace(f"Client {t}_{i} categorised as inappropriate referral - rejected")

                    self.event_log.append(
                        {'patient': f"{t}_{i}",
                        'pathway': "Unsuitable for service",
                        'event_type': 'queue',
                        'event': 'referred_out',
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
                    #print(f"Patient {t}_{i} discharged before assessment as unsuitable for service")

            # Finish iterating per patient

            # Move onto processes that will be triggered once per day
            trace(f"Triggering assessment booking process on day {self.env.now}")
            self.env.process(self.book_new_clients_if_capacity())

            # Record the daily caseload after all patients booked in
            # caseload_slots_per_clinician = (self.args.weekly_slots).sum().to_numpy().T
            self.daily_caseload_snapshots.append(
                {'day': t, 'caseload_day_end': self.args.existing_caseload.tolist()[1:]}
                )

            self.daily_waiting_for_booking_snapshots.append(
                {'day': t, 'booking_queue_size_day_end': self.args.waiting_for_clinician_store.qsize()}
                )
            #timestep by one day
            yield self.env.timeout(1)

    def book_new_clients_if_capacity(self):
        trace(f"Initial check of clinician caseload on day {self.env.now}")
        # Check whether there is any capacity for new patients to be added to the
        # caseload of the clinicians
        # (i.e. have any of their existing clients had their final appointment since yesterday,
        # making space on their books?)

        # There may be more than 1 clinician who has capacity now (or a clinician may have capacity to take on multiple new clients),
        # so get the total number of available slots we can work with

        # Get this many patients out of the store
        # (skimming from the top/front of the queue - store is FIFO)
        # Remember that different patients will have different priorities/frequencies,
        # which affects how much of a caseload slot they take up (e.g. being seen
        # every 2 weeks means 0.5 slots used, being seen every week means 1 slot used)
        # Note - in this model we have made it so that high priority patients
        # get booked in regardless of capacity,
        # and low priority patients get booked in when there is availability by
        # being sent to this process
        #  If you wanted a different behaviour for the high priority patients
        # (or to add in additional ranking of multiple priorities of patient)
        # you could put all patients into the store and reorder them in the store by some priority variable

        # First calculate the caseload of each clinician
        # Caseload calculation is based on the number of slots they have available
        # each week, the number of high intensity patients they have (take up 1 slot per week,
        # so 1 caseload slot), and the number of low intensity caseload patients they have
        # (take up 1 slot every other week, so 0.5 caseload slots).
        # Want to leave a buffer of 1 caseload slot per clinician
        # (i.e. if they have 15 theoretical slots per week but 14 are already taken,
        # we will count this as full for these purposes - as this leaves some flexibility for
        # high priority/urgent patients, who will bypass the check
        # and be admitted to caseload anyway)

        # What we need to check is the number of people currently booked for assessment
        # or on the books with each clinician

        # this is stored in self.args.existing_caseload

        def check_for_availability():
            # Then we calculate their theoretical maximum from the slots file
             # TODO: Consdier whether to floor
            caseload_slots_per_clinician = np.floor((self.args.weekly_slots).sum().to_numpy().T * self.args.caseload_multiplier)
            trace(f"Adjusted slots: {caseload_slots_per_clinician}")
            # caseload_slots_per_clinician = (self.args.weekly_slots).sum().to_numpy().T
            # Then we subtract one from the other to get the available slots
            # Then subtract one from the theoretical maximum because we want to leave headroom
            # for emergency clients
            # available_caseload = (caseload_slots_per_clinician - self.args.existing_caseload.tolist()[1:]) -1
            available_caseload = (caseload_slots_per_clinician - self.args.existing_caseload.tolist()[1:])
            clinicians_with_slots = len([c for c in available_caseload if c >= 0.5])
            return clinicians_with_slots, available_caseload

        # Do an initial check for if anyone has capacity
        # and if they do, check who has the soonest appointment
        # If no-one has capacity, time out and wait until tomorrow instead
        # when a fresh check will be done.
        # clinicians_with_slots, available_caseload = check_for_availability()
        # trace(f"Current caseload distribution: {self.args.existing_caseload.tolist()[1:]}")
        # trace(f"Initial availability on day {self.env.now}: {clinicians_with_slots} " \
        #       f"clinicians with {available_caseload.sum()} total caseload slots ({available_caseload})")

        # We have to make some assumptions here that may later prove to be incorrect -
        # we assume a low priority patient will go on to be low intensity,
        # but this may change after their assessment - but for now we basically assume
        # that each client that's in our store is going to take up 0.5 slots
        # (so e.g. if a high intensity patient has just left the system, then you
        # can book 2 likely-to-be-low intensity patients in their place)

        # Continue looping while there are people waiting to be booked
        while self.args.waiting_for_clinician_store.qsize() > 0:
            clinicians_with_slots, available_caseload = check_for_availability()
            # if there are any available slots, proceed, else break loop entirely
            # as if this is the case, we can't make any more bookings today
            cl_count = sum([c if c>0 else 0 for c in available_caseload])
            trace(f"Available caseload is {cl_count}")
            if cl_count < 0.5:
                trace("Exiting loop position 1")
                break

            #print(f"{self.args.waiting_for_clinician_store.qsize()} patients still waiting to be booked in")

            # Get someone out of the store of patients waiting for bookings
            patient_front_of_wl = self.args.waiting_for_clinician_store.get().item
            # Check whether they
            # You could do this differently here if you had multiple priority
            # levels within the store
            # For example, if there isn't space for a high priority person on someone's
            # caseload, maybe a low priority person could jump the queue
            # (as they wouldn't overload that clinician)
            # But here we just have low priority patients in our store because any
            # high priority patients have gone straight to being booked in
            #print(f"Patient {patient_front_of_wl.identifier} (priority: {patient_front_of_wl.priority}) removed from store")
            yield self.env.process(patient_front_of_wl.execute_assessment_booking())
            trace(f"Assessment booking process complete for patient {patient_front_of_wl.identifier}")

            # Recheck the availability after this booking
            # clinicians_with_slots, available_caseload = check_for_availability()
            # trace(f"Updated availability on day {self.env.now} after booking {patient_front_of_wl.identifier}: {clinicians_with_slots} clinicians with {sum([c if c>0 else 0 for c in available_caseload])} total slots")
            # trace(f"Available caseload per clinician: {available_caseload}")
            # # If after updating availability there is no longer anyone with a caseload slot, break
            # # out of the while loop
            # if sum([c if c>0 else 0 for c in available_caseload]) < 0.5:
            #     trace (f"Available caseload is {sum([c if c>0 else 0 for c in available_caseload])} - exiting loop position 2")
            #     break


            # # If no availability at initial check point, exit
            # else:
            #     trace ("Exiting loop position 1")
            #     break

                # # Now that patient has been booked in, recheck the number of available slots
                # # If there are still clinicians with slots, the next patient in the store
                # # will be brought out and be booked in
                # clinicians_with_slots, available_caseload = check_for_availability()
        else:
            trace(f"No further slots available for booking on day {self.env.now}")



    def process_run_results(self):
        '''
        Produce summary results split by priority...
        '''

        trace(f"{len(self.referrals)} patients in total")
        trace(f"{[p.priority for p in self.referrals]}")

        results_all = [p.waiting_time for p in self.referrals
               if not p.waiting_time is None]
        trace(f"Results all - len {len(results_all)}")

        results_low = [p.waiting_time for p in self.referrals
                       if not (p.waiting_time is None) and p.priority == 1]
        trace(f"Results low - len {len(results_low)}")

        results_high = [p.waiting_time for p in self.referrals
                       if (not p.waiting_time is None) and p.priority == 2]

        trace(f"Results high - len {len(results_high)}")

        results_arrivals = [p.arrival_day for p in self.referrals]

        self.results_all = results_all
        self.results_low = results_low
        self.results_high = results_high

        self.bookings = self.args.bookings
        self.available_slots = self.args.available_slots
        self.daily_caseload_snapshots = pd.DataFrame(self.daily_caseload_snapshots)
        self.daily_waiting_for_booking_snapshots = pd.DataFrame(self.daily_waiting_for_booking_snapshots)
        self.results_daily_arrivals = results_arrivals
