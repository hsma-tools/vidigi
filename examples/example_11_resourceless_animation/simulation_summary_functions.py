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
    summary_frame = pd.concat([pd.DataFrame(results_all).describe(),
                               pd.DataFrame(results_low).describe(),
                               pd.DataFrame(results_high).describe()],
                               axis=1)
    summary_frame.columns = ['all', 'low_pri', 'high_pri']
    return summary_frame
