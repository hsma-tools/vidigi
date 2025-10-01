import simpy
import random
from vidigi.logging import EventLogger


# Model parameters
class g:
    # Arrival rates
    mean_interarrival_time = 1.0 / (70.0 / 7.0)  # ~70 patients per week

    # Resource capacities
    n_initial_reviewers = 2
    n_assessors = 1
    n_treatment_slots = 1

    # Activity durations (in days)
    mean_initial_review_time = 0.5
    mean_assessment_time = 2.0
    mean_treatment_time = 3.0

    # Simulation parameters
    sim_duration = 52 * 7  # 52 weeks in days
    warm_up_period = 4 * 7  # 4 weeks warm-up
    number_of_runs = 1


# Patient class
class Patient:
    def __init__(self, p_id):
        self.id = p_id


# Model class
class Model:
    def __init__(self, run_number):
        self.env = simpy.Environment()
        self.patient_counter = 0
        self.run_number = run_number

        # Resources
        self.initial_reviewers = simpy.Resource(
            self.env, capacity=g.n_initial_reviewers
        )
        self.assessors = simpy.Resource(self.env, capacity=g.n_assessors)
        self.treatment_slots = simpy.Resource(self.env, capacity=g.n_treatment_slots)

        # Event logger
        self.event_log = EventLogger(env=self.env, run_number=run_number)

    def generator_patient_arrivals(self):
        """Generate patient arrivals"""
        while True:
            self.patient_counter += 1
            p = Patient(self.patient_counter)

            # Log arrival
            self.event_log.log_arrival(entity_id=p.id)

            self.env.process(self.patient_pathway(p))

            sampled_interarrival = random.expovariate(1.0 / g.mean_interarrival_time)
            yield self.env.timeout(sampled_interarrival)

    def patient_pathway(self, patient):
        """Define the patient pathway through the three steps"""

        # Step 1: Initial Review
        # Log queue entry
        self.event_log.log_queue(event="queue_initial_review", entity_id=patient.id)

        with self.initial_reviewers.request() as req:
            yield req

            # Log start of initial review
            self.event_log.log_queue(
                event="start_initial_review",
                entity_id=patient.id,
            )

            sampled_review_duration = random.expovariate(
                1.0 / g.mean_initial_review_time
            )
            yield self.env.timeout(sampled_review_duration)

            # Log end of initial review
            self.event_log.log_queue(
                event="end_initial_review",
                entity_id=patient.id,
            )

        # Step 2: Assessment
        # Log queue entry
        self.event_log.log_queue(event="queue_assessment", entity_id=patient.id)

        with self.assessors.request() as req:
            yield req

            # Log start of assessment
            self.event_log.log_queue(event="start_assessment", entity_id=patient.id)

            sampled_assessment_duration = random.expovariate(
                1.0 / g.mean_assessment_time
            )
            yield self.env.timeout(sampled_assessment_duration)

            # Log end of assessment
            self.event_log.log_queue(event="end_assessment", entity_id=patient.id)

        # Step 3: Treatment
        # Log queue entry
        self.event_log.log_queue(event="queue_treatment", entity_id=patient.id)

        with self.treatment_slots.request() as req:
            yield req

            # Log start of treatment
            self.event_log.log_queue(event="start_treatment", entity_id=patient.id)

            sampled_treatment_duration = random.expovariate(1.0 / g.mean_treatment_time)
            yield self.env.timeout(sampled_treatment_duration)

            # Log end of treatment (departure from system)
            self.event_log.log_queue(event="end_treatment", entity_id=patient.id)

        self.event_log.log_departure(entity_id=patient.id)

    def run(self):
        """Run the simulation"""
        self.env.process(self.generator_patient_arrivals())
        self.env.run(until=g.sim_duration)

        return self.event_log
