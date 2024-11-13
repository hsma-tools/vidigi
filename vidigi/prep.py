import gc
import time
import pandas as pd
import numpy as np

def reshape_for_animations(event_log,
                           every_x_time_units=10,
                           limit_duration=10*60*24,
                           step_snapshot_max=50,
                           debug_mode=False):
    patient_dfs = []

    pivoted_log = event_log.pivot_table(values="time",
                                        index=["patient","event_type","pathway"],
                                        columns="event").reset_index()

    #TODO: Add in behaviour for if limit_duration is None

    ################################################################################
    # Iterate through every matching minute
    # and generate snapshot df of position of any patients present at that moment
    ################################################################################
    for minute in range(limit_duration):
        # print(minute)
        # Get patients who arrived before the current minute and who left the system after the current minute
        # (or arrived but didn't reach the point of being seen before the model run ended)
        # When turning this into a function, think we will want user to pass
        # 'first step' and 'last step' or something similar
        # and will want to reshape the event log for this so that it has a clear start/end regardless
        # of pathway (move all the pathway stuff into a separate column?)

        # Think we maybe need a pathway order and pathway precedence column
        # But what about shared elements of each pathway?
        if minute % every_x_time_units == 0:
            try:
                # Work out which patients - if any - were present in the simulation at the current time
                # They will have arrived at or before the minute in question, and they will depart at
                # or after the minute in question, or never depart during our model run
                # (which can happen if they arrive towards the end, or there is a bottleneck)
                current_patients_in_moment = pivoted_log[(pivoted_log['arrival'] <= minute) &
                            (
                                (pivoted_log['depart'] >= minute) |
                                (pivoted_log['depart'].isnull() )
                            )]['patient'].values
            except KeyError:
                current_patients_in_moment = None

            # If we do have any patients, they will have been passed as a list
            # so now just filter our event log down to the events these patients have been
            # involved in
            if current_patients_in_moment is not None:
                # Grab just those clients from the filtered log (the unpivoted version)
                # Filter out any events that have taken place after the minute we are interested in

                patient_minute_df = event_log[
                    (event_log['patient'].isin(current_patients_in_moment)) &
                    (event_log['time'] <= minute)
                    ]
                # Each person can only be in a single place at once, and we have filtered out
                # events that occurred later than the current minute, so filter out any events
                # then just take the latest event that has taken place for each client
                most_recent_events_minute_ungrouped = patient_minute_df \
                    .reset_index(drop=False) \
                    .sort_values(['time', 'index'], ascending=True) \
                    .groupby(['patient']) \
                    .tail(1)

                # Now rank patients within a given event by the order in which they turned up to that event
                most_recent_events_minute_ungrouped['rank'] = most_recent_events_minute_ungrouped \
                              .groupby(['event'])['index'] \
                              .rank(method='first')


                most_recent_events_minute_ungrouped['max'] = most_recent_events_minute_ungrouped.groupby('event')['rank'] \
                                                             .transform('max')

                most_recent_events_minute_ungrouped = most_recent_events_minute_ungrouped[
                    most_recent_events_minute_ungrouped['rank'] <= (step_snapshot_max + 1)
                    ].copy()

                maximum_row_per_event_df = most_recent_events_minute_ungrouped[
                    most_recent_events_minute_ungrouped['rank'] == float(step_snapshot_max + 1)
                    ].copy()

                maximum_row_per_event_df['additional'] = ''

                if len(maximum_row_per_event_df) > 0:
                    maximum_row_per_event_df['additional'] = maximum_row_per_event_df['max'] - maximum_row_per_event_df['rank']
                    most_recent_events_minute_ungrouped = pd.concat(
                        [most_recent_events_minute_ungrouped[most_recent_events_minute_ungrouped['rank'] != float(step_snapshot_max + 1)],
                        maximum_row_per_event_df],
                        ignore_index=True
                    )

                # Add this dataframe to our list of dataframes, and then return to the beginning
                # of the loop and do this for the next minute of interest until we reach the end
                # of the period of interest
                patient_dfs.append(most_recent_events_minute_ungrouped
                                   .drop(columns='max')
                                   .assign(minute=minute))
    if debug_mode:
        print(f'Iteration through minute-by-minute logs complete {time.strftime("%H:%M:%S", time.localtime())}')

    full_patient_df = (pd.concat(patient_dfs, ignore_index=True)).reset_index(drop=True)

    if debug_mode:
        print(f'Snapshot df concatenation complete at {time.strftime("%H:%M:%S", time.localtime())}')

    del patient_dfs
    gc.collect()

    # Add a final exit step for each client
    # This is helpful as it ensures all patients are visually seen to exit rather than
    # just disappearing after their final step
    # It makes it easier to track the split of people going on to an optional step when
    # this step is at the end of the pathway
    # TODO: Fix so that everyone doesn't automatically exit at the end of the simulation run
    final_step = full_patient_df.sort_values(["patient", "minute"], ascending=True) \
                 .groupby(["patient"]) \
                 .tail(1)

    final_step['minute'] = final_step['minute'] + every_x_time_units
    final_step['event'] = "exit"

    full_patient_df = pd.concat([full_patient_df, final_step], ignore_index=True)

    del final_step
    gc.collect()

    return full_patient_df.sort_values(["minute", "event"]).reset_index(drop=True)

def generate_animation_df(
        full_patient_df,
        event_position_df,
        wrap_queues_at=20,
        step_snapshot_max=50,
        gap_between_entities=10,
        gap_between_resources=10,
        gap_between_rows=30,
        debug_mode=False
):
    """_summary_

    Args:
        full_patient_df (pd.Dataframe):
            output of reshape_for_animation()

        event_position_dicts (pd.Dataframe):
            dataframe with three cols - event, x and y
            Can be more easily created by passing a list of dicts to pd.DataFrame
            list of dictionaries with one dicitionary per event type
            containing keys 'event', 'x' and 'y'
            This will determine the intial position of any entries in the animated log
            (think of it as the bottom right hand corner of any group of entities at each stage)

        scenario:
            Pass in an object that specifies the number of resources at different steps

        rep (int, optional): Defaults to 1.
            The replication of any model to include. Can only display one rep at a time, so will take
            the first rep if not otherwise specified.

        plotly_height (int, optional): Defaults to 900.

    Returns:
       Plotly fig object
    """

    # Filter to only a single replication

    # TODO: Write a test  to ensure that no patient ID appears in multiple places at a single minute
    # and return an error if it does so

    # Order patients within event/minute/rep to determine their eventual position in the line
    full_patient_df['rank'] = full_patient_df.groupby(['event','minute'])['minute'] \
                              .rank(method='first')

    full_patient_df_plus_pos = full_patient_df.merge(event_position_df, on="event", how='left') \
                             .sort_values(["event", "minute", "time"])

    # Determine the position for any resource use steps
    resource_use = full_patient_df_plus_pos[full_patient_df_plus_pos['event_type'] == "resource_use"].copy()
    # resource_use['y_final'] =  resource_use['y']

    if len(resource_use) > 0:
        resource_use = resource_use.rename(columns={"y": "y_final"})
        resource_use['x_final'] = resource_use['x'] - resource_use['resource_id'] * gap_between_resources

    # Determine the position for any queuing steps
    queues = full_patient_df_plus_pos[full_patient_df_plus_pos['event_type']=='queue'].copy()
    # queues['y_final'] =  queues['y']
    queues = queues.rename(columns={"y": "y_final"})
    queues['x_final'] = queues['x'] - queues['rank'] * gap_between_entities

    # If we want people to wrap at a certain queue length, do this here
    # They'll wrap at the defined point and then the queue will start expanding upwards
    # from the starting row
    if wrap_queues_at is not None:
        queues['row'] = np.floor((queues['rank'] - 1) / (wrap_queues_at))
        queues['x_final'] = queues['x_final'] + (wrap_queues_at * queues['row'] * gap_between_entities) + gap_between_entities
        queues['y_final'] = queues['y_final'] + (queues['row'] * gap_between_rows)

    queues['x_final'] = np.where(queues['rank'] != step_snapshot_max + 1,
                                 queues['x_final'],
                                queues['x_final'] - (gap_between_entities * (wrap_queues_at/2)))


    if len(resource_use) > 0:
        full_patient_df_plus_pos = pd.concat([queues, resource_use], ignore_index=True)
        del resource_use, queues
    else:
        full_patient_df_plus_pos = queues.copy()
        del queues


    if debug_mode:
        print(f'Placement dataframe finished construction at {time.strftime("%H:%M:%S", time.localtime())}')

    # full_patient_df_plus_pos['icon'] = '🙍'

    individual_patients = full_patient_df['patient'].drop_duplicates().sort_values()

    # Recommend https://emojipedia.org/ for finding emojis to add to list
    # note that best compatibility across systems can be achieved by using
    # emojis from v12.0 and below - Windows 10 got no more updates after that point
    icon_list = [
        '🧔🏼', '👨🏿‍🦯', '👨🏻‍🦰', '🧑🏻', '👩🏿‍🦱',
        '🤰', '👳🏽', '👩🏼‍🦳', '👨🏿‍🦳', '👩🏼‍🦱',
        '🧍🏽‍♀️', '👨🏼‍🔬', '👩🏻‍🦰', '🧕🏿', '👨🏼‍🦽',
        '👴🏾', '👨🏼‍🦱', '👷🏾', '👧🏿', '🙎🏼‍♂️',
        '👩🏻‍🦲', '🧔🏾', '🧕🏻', '👨🏾‍🎓', '👨🏾‍🦲',
        '👨🏿‍🦰', '🙍🏼‍♂️', '🙋🏾‍♀️', '👩🏻‍🔧', '👨🏿‍🦽',
        '👩🏼‍🦳', '👩🏼‍🦼', '🙋🏽‍♂️', '👩🏿‍🎓', '👴🏻',
        '🤷🏻‍♀️', '👶🏾', '👨🏻‍✈️', '🙎🏿‍♀️', '👶🏻',
        '👴🏿', '👨🏻‍🦳', '👩🏽', '👩🏽‍🦳', '🧍🏼‍♂️',
        '👩🏽‍🎓', '👱🏻‍♀️', '👲🏼', '🧕🏾', '👨🏻‍🦯',
        '🧔🏿', '👳🏿', '🤦🏻‍♂️', '👩🏽‍🦰', '👨🏼‍✈️',
        '👨🏾‍🦲', '🧍🏾‍♂️', '👧🏼', '🤷🏿‍♂️', '👨🏿‍🔧',
        '👱🏾‍♂️', '👨🏼‍🎓', '👵🏼', '🤵🏿', '🤦🏾‍♀️',
        '👳🏻', '🙋🏼‍♂️', '👩🏻‍🎓', '👩🏼‍🌾', '👩🏾‍🔬',
        '👩🏿‍✈️', '🎅🏼', '👵🏿', '🤵🏻', '🤰'
    ]

    full_icon_list = icon_list * int(np.ceil(len(individual_patients)/len(icon_list)))

    full_icon_list = full_icon_list[0:len(individual_patients)]

    full_patient_df_plus_pos = full_patient_df_plus_pos.merge(
        pd.DataFrame({'patient':list(individual_patients),
                      'icon':full_icon_list}),
        on="patient")

    if 'additional' in full_patient_df_plus_pos.columns:
        exceeded_snapshot_limit = full_patient_df_plus_pos[full_patient_df_plus_pos['additional'].notna()].copy()
        exceeded_snapshot_limit['icon'] = exceeded_snapshot_limit['additional'].apply(lambda x: f"+ {int(x):5d} more")
        full_patient_df_plus_pos = pd.concat(
            [
                full_patient_df_plus_pos[full_patient_df_plus_pos['additional'].isna()], exceeded_snapshot_limit
            ],
            ignore_index=True
        )

    return full_patient_df_plus_pos
