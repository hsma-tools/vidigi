"""A two-stage clinic model, used only by the `resource_icon` /
`resource_icon_font` section of `feat_custom_icons.ipynb`.

Patients arrive, are seen by a nurse, then rest in a recovery bed, then leave -
so the animation has two independent resource stages to give different icons.
Deliberately minimal: no trial wrapper, no results dataframe, just an event log.
"""

import pandas as pd
import simpy
from sim_tools.distributions import Exponential, Lognormal

from vidigi.resources import populate_store


class g:
    """Parameters for the two-stage clinic."""

    n_nurses = 3
    n_beds = 4

    arrival_rate = 6
    nurse_time_mean = 20
    nurse_time_var = 4
    bed_time_mean = 45
    bed_time_var = 10

    sim_duration = 300
    random_number_set = 42


class Model:
    """Simulates a patient being seen by a nurse and then resting in a bed."""

    def __init__(self, run_number):
        self.env = simpy.Environment()
        self.event_log = []
        self.patient_counter = 0
        self.run_number = run_number

        self.nurses = simpy.Store(self.env)
        populate_store(
            num_resources=g.n_nurses,
            simpy_store=self.nurses,
            sim_env=self.env,
            label="nurse",
        )

        self.beds = simpy.Store(self.env)
        populate_store(
            num_resources=g.n_beds,
            simpy_store=self.beds,
            sim_env=self.env,
            label="bed",
        )

        seed = run_number * g.random_number_set
        self.arrival_dist = Exponential(mean=g.arrival_rate, random_seed=seed)
        self.nurse_dist = Lognormal(
            mean=g.nurse_time_mean, stdev=g.nurse_time_var, random_seed=seed + 1
        )
        self.bed_dist = Lognormal(
            mean=g.bed_time_mean, stdev=g.bed_time_var, random_seed=seed + 2
        )

    def _log(self, patient, event, event_type, **extra):
        self.event_log.append(
            {
                "patient": patient,
                "pathway": "Clinic",
                "event": event,
                "event_type": event_type,
                "time": self.env.now,
                **extra,
            }
        )

    def generator_patient_arrivals(self):
        while True:
            self.patient_counter += 1
            self.env.process(self.attend_clinic(self.patient_counter))
            yield self.env.timeout(self.arrival_dist.sample())

    def attend_clinic(self, patient):
        self._log(patient, "arrival", "arrival_departure")

        self._log(patient, "nurse_wait_begins", "queue")
        nurse = yield self.nurses.get()
        self._log(
            patient, "nurse_begins", "resource_use", resource_id=nurse.id_attribute
        )
        yield self.env.timeout(self.nurse_dist.sample())
        self._log(
            patient,
            "nurse_complete",
            "resource_use_end",
            resource_id=nurse.id_attribute,
        )
        self.nurses.put(nurse)

        self._log(patient, "bed_wait_begins", "queue")
        bed = yield self.beds.get()
        self._log(
            patient, "bed_begins", "resource_use", resource_id=bed.id_attribute
        )
        yield self.env.timeout(self.bed_dist.sample())
        self._log(
            patient, "bed_complete", "resource_use_end", resource_id=bed.id_attribute
        )
        self.beds.put(bed)

        self._log(patient, "depart", "arrival_departure")

    def run(self):
        self.env.process(self.generator_patient_arrivals())
        self.env.run(until=g.sim_duration)

        self.event_log = pd.DataFrame(self.event_log)
        self.event_log["run"] = self.run_number
        return {"event_log": self.event_log}
