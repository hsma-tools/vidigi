# Utility functions
import simpy

TRACE = False

def trace(msg, show=TRACE):
    '''
    Utility function for printing a trace as the
    simulation model executes.
    Set the TRACE constant to False, to turn tracing off.

    Params:
    -------
    msg: str
        string to print to screen.
    '''
    if show:
        print(msg)
