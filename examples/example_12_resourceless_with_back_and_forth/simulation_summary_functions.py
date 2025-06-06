import pandas as pd

def results_summary(results_all, results_low, results_high):
    '''
    Present model results as a summary data frame

    Params:
    ------
    results_all: list
        - all patient waiting times unfiltered by prirority

    results_low: list
        - low prioirty patient waiting times

    results_high: list
        - high priority patient waiting times

    Returns:
    -------
        pd.DataFrame
    '''
    dfs = []
    column_names = []

    if results_all:
        results_all_described = pd.DataFrame(results_all).describe()
        dfs.append(results_all_described)
        column_names.append("All")
    if results_low:
        results_low_described = pd.DataFrame(results_low).describe()
        dfs.append(results_low_described)
        column_names.append("Low Priority")
    if results_high:
        results_high_described = pd.DataFrame(results_high).describe()
        dfs.append(results_high_described)
        column_names.append("High Priority")

    summary_frame = pd.concat(dfs,
                               axis=1)

    summary_frame.columns = column_names

    return summary_frame
