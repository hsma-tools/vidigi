import pandas as pd
import numpy as np
from examples.example_13_additional_synchronised_traces_method_1.model_classes import Schedule, Hospital
from examples.example_13_additional_synchronised_traces_method_1.simulation_summary_functions import Summary

# Model execution

# A single_run returns three data sets: summary, daily, patient-level

# The function multiple_reps calls single_run for the number of replications.

def single_run(scenario,
               results_collection=42+7,
               random_no_set=None,
               return_detailed_logs=False):
    """
    summary results for a single run which can be called for multiple runs
    1. summary of single run
    2. daily audit of mean results per day
    3a. primary patient results for one run and all days
    3b. revision patient results for one run and all days
    """
    scenario.set_random_no_set(random_no_set)
    schedule = Schedule()
    model = Hospital(scenario)
    model.run(results_collection = results_collection)
    summary = Summary(model)

    #summary results for a single run
    #(warmup excluded apart from bed utilisation AND throughput)
    summary_df = summary.summary_frame()

    #summary per day results for a single run (warmup excluded)
    results_per_day = model.results

    #patient-level results (includes warmup results)
    patient_results = model.patient_results()

    if return_detailed_logs:
        event_log =  pd.DataFrame(model.event_log)

        return (summary_df, results_per_day, patient_results, event_log)

    return(summary_df, results_per_day, patient_results)

def multiple_replications(scenario,
                  results_collection=42,
                  warmup=7,
                  n_reps=30,
                  return_detailed_logs=False):
    """
    create dataframes of summary results across multiple runs:
    1. summary table per run
    2. summary table per run and per day
    3a. primary patient results for all days and all runs
    3b. revision patient results for all days and all runs
    """

    results_collection_plus_warmup = results_collection + warmup
    #summary per run for multiple reps
    #(warm-up excluded apart from bed utilisation AND throughput)

    # all_results =

    results = [single_run(scenario, results_collection_plus_warmup, random_no_set=rep)[0]
                         for rep in range(n_reps)]
    df_results = pd.concat(results)
    df_results.index = np.arange(1, len(df_results)+1)
    df_results.index.name = 'rep'

    #summary per day per run for multiple reps (warmup excluded)
    day_results = [single_run(scenario, results_collection_plus_warmup, random_no_set=rep)[1]
                         for rep in range(n_reps)]

    length_run = [*range(1, results_collection_plus_warmup-warmup+1)]
    length_reps = [*range(1, n_reps+1)]
    run = [rep for rep in length_reps for i in length_run]

    df_day_results = pd.concat(day_results)
    df_day_results['run'] = run

    #patient results for all days and all runs (warmup included)
    primary_pt_results = [single_run(scenario, results_collection_plus_warmup, random_no_set=rep)[2][0].assign(rep = rep+1)
                         for rep in range(n_reps)]
    primary_pt_results = pd.concat(primary_pt_results)

    revision_pt_results = [single_run(scenario, results_collection_plus_warmup, random_no_set=rep)[2][1].assign(rep = rep+1)
                         for rep in range(n_reps)]
    revision_pt_results = pd.concat(revision_pt_results)

    if return_detailed_logs:
        event_log = [single_run(scenario,
                                results_collection_plus_warmup,
                                random_no_set=rep,
                                return_detailed_logs=True)[3].assign(rep = rep+1)
                            for rep in range(n_reps)]
        event_log = pd.concat(event_log)


        return (df_results, df_day_results, primary_pt_results, revision_pt_results, event_log)

    return (df_results, df_day_results, primary_pt_results, revision_pt_results)
