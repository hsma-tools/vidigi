# Summary results across days and runs

# Overall summary of results across all runs, and across model run time.

# Used for validation

import numpy as np
import pandas as pd

DEFAULT_WARM_UP_PERIOD = 7
DEFAULT_RESULTS_COLLECTION_PERIOD = 42

class Summary:
    """
    summary results across run
    """
    def __init__(self, model):
        """ model: Hospital """
        
        self.model = model
        self.args = model.args
        self.summary_results = None
        
    def process_run_results(self):
        self.summary_results = {}
        
        #all patients arrived during results collection period
        patients = len([p for p in self.model.cum_primary_patients if p.day > DEFAULT_WARM_UP_PERIOD])+\
            len([p for p in self.model.cum_revision_patients if p.day > DEFAULT_WARM_UP_PERIOD])
        
        primary_arrivals = len([p for p in self.model.cum_primary_patients if p.day > DEFAULT_WARM_UP_PERIOD])
        revision_arrivals = len([p for p in self.model.cum_revision_patients if p.day > DEFAULT_WARM_UP_PERIOD])

        #throughput during results collection period
        primary_throughput = len([p for p in self.model.cum_primary_patients if (p.total_time > -np.inf)
                                  & (p.day > DEFAULT_WARM_UP_PERIOD)])
        revision_throughput = len([p for p in self.model.cum_revision_patients if (p.total_time > -np.inf)
                                   & (p.day > DEFAULT_WARM_UP_PERIOD)])

        #mean queues - this also includes patients who renege and therefore have 0 queue
        mean_primary_queue_beds = np.array([getattr(p, 'queue_beds') for p in self.model.cum_primary_patients
                                            if getattr(p, 'queue_beds') > -np.inf]).mean()
        mean_revision_queue_beds = np.array([getattr(p, 'queue_beds') for p in self.model.cum_revision_patients
                                            if getattr(p, 'queue_beds') > -np.inf]).mean()

        #check mean los
        mean_primary_los = np.array([getattr(p, 'primary_los') for p in self.model.cum_primary_patients
                                               if getattr(p, 'primary_los') > 0]).mean()
        mean_revision_los = np.array([getattr(p, 'revision_los') for p in self.model.cum_revision_patients
                                               if getattr(p, 'revision_los') > 0]).mean()

        #bed utilisation primary and revision patients during results collection period
        los_primary = np.array([getattr(p,'primary_los') for p in self.model.cum_primary_patients
                                if (getattr(p, 'primary_los') > -np.inf) & (getattr(p, 'day') > DEFAULT_WARM_UP_PERIOD)]).sum()
        mean_primary_bed_utilisation = los_primary / (DEFAULT_RESULTS_COLLECTION_PERIOD * self.args.n_beds)
        los_revision = np.array([getattr(p,'revision_los') for p in self.model.cum_revision_patients
                                if (getattr(p, 'revision_los') > -np.inf) & (getattr(p, 'day') > DEFAULT_WARM_UP_PERIOD)]).sum()
        mean_revision_bed_utilisation = los_revision / (DEFAULT_RESULTS_COLLECTION_PERIOD * self.args.n_beds)

        self.summary_results = {'arrivals':patients,
                                'primary_arrivals':primary_arrivals,  
                                'revision_arrivals':revision_arrivals,                     
                                'primary_throughput':primary_throughput,
                                'revision_throughput':revision_throughput,
                                'primary_queue':mean_primary_queue_beds,
                                'revision_queue':mean_revision_queue_beds,
                                'mean_primary_los':mean_primary_los,
                                'mean_revision_los':mean_revision_los,
                                'primary_bed_utilisation':mean_primary_bed_utilisation,
                                'revision_bed_utilisation':mean_revision_bed_utilisation}
    
    def summary_frame(self):
        if self.summary_results is None:
            self.process_run_results()
        df = pd.DataFrame({'1':self.summary_results})
        df = df.T
        df.index.name = 'rep'
        return df
                                            