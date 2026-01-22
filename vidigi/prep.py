import gc
import time
import pandas as pd
import numpy as np
import hashlib
import warnings
from typing import Optional, Union
from vidigi.utils import _enforce_int_params


@_enforce_int_params(
    ["every_x_time_units", "limit_duration", "step_snapshot_max"]
)
def reshape_for_animations(
    event_log: pd.DataFrame,
    every_x_time_units: int = 10,
    limit_duration: int = 10 * 60 * 24,
    step_snapshot_max: int = 50,
    time_col_name: str = "time",
    entity_col_name: str = "entity_id",
    event_type_col_name: str = "event_type",
    event_col_name: str = "event",
    pathway_col_name: Optional[str] = None,
    debug_mode: bool = False,
    save_intermediate_outputs: Optional[Union[bool, str]] = False,
) -> pd.DataFrame:
    """
    Reshape event log data for animation purposes.

    This function processes an event log to create a series of snapshots at regular time intervals,
    suitable for creating animations of patient flow through a system.

    Parameters
    ----------
    event_log : pd.DataFrame
        The input event log containing entity events and timestamps in the form of a number of time
        units since the simulation began.
    every_x_time_units : int, optional
        The time interval between snapshots in preferred time units (default is 10).
    limit_duration : int, optional
        The maximum duration to consider in preferred time units (default is 10 days).
    step_snapshot_max : int, optional
        The maximum number of entities to include in each snapshot for each event (default is 50).
    time_col_name : str, default="time"
        Name of the column in `event_log` that contains the timestamp of each event.
        Timestamps should represent the number of time units since the simulation began.
    entity_col_name : str, default="entity_id"
        Name of the column in `event_log` that contains the unique identifier for each entity
        (e.g., "entity_id", "entity", "patient", "patient_id", "customer", "ID").
    event_type_col_name : str, default="event_type"
        Name of the column in `event_log` that specifies the category of the event.
        Supported event types include 'arrival_departure', 'resource_use',
        'resource_use_end', and 'queue'.
    event_col_name : str, default="event"
        Name of the column in `event_log` that specifies the actual event that occurred.
    pathway_col_name : str, optional, default=None
        Name of the column in `event_log` that identifies the specific pathway or
        process flow the entity is following. If `None`, it is assumed that pathway
        information is not present.
    debug_mode : bool, optional
        If True, print debug information during processing (default is False).
    save_intermediate_outputs: bool or str, optional
        For debugging purposes.
        If True or a string, output a series of csvs with intermediate transformed dataframes.
        If a string is passed, this will be interpreted as the path to prefix the dataframes with.
        Default is False.

    Returns
    -------
    DataFrame
        A reshaped DataFrame containing snapshots of entity positions at regular time intervals,
        sorted by minute and event.

    Notes
    -----
    - The function creates snapshots of entity positions at specified time intervals.
    - It handles entities who are present in the system at each snapshot time.
    - Entities are ranked within each event based on their arrival order.
    - A maximum number of patients per event can be set to limit the number of entities who will be
      displayed on screen within any one event type at a time.
    - This function assumes entities only exist in one place/queue at a time. Simulations where this
      assumption does not hold may display unexpected behaviour.
    - An 'exit' event is added for each entity at the end of their journey.
    - The function uses memory management techniques (del and gc.collect()) to handle large datasets.

    TODO
    ----
    - Add behavior for when limit_duration is None.
    - Consider adding 'first step' and 'last step' parameters.
    - Implement pathway order and precedence columns.
    - Fix the automatic exit at the end of the simulation run for all entities.
    """
    # Begin logic
    entity_dfs = []

    if save_intermediate_outputs is not False:
        if isinstance(save_intermediate_outputs, str):
            extra_path = save_intermediate_outputs
        else:
            extra_path = ""

    # First, we convert our event log from a long format (one row per event) to a wide format
    # By using the entity ID and the event type as the index, we will obtain a dataframe where
    # the arrival time and departure time for an individual are side-by-side, allowing us to more
    # easily filter for entities that meet arrival/departure time criteria and get their IDs, which
    # we can then use for later filtering

    # If a pathway column is provided, make this part of the index
    # (note - this is a hang over from the early development of the package, and it is likely
    # to be removed as a behaviour at a later date as the concept of 'pathways' was tied up in
    # some specific use cases and isn't really necessary for things to function)
    if pathway_col_name is not None:
        pivoted_log = (
            event_log[event_log[event_type_col_name] == "arrival_departure"]
            .pivot_table(
                values=time_col_name,
                index=[entity_col_name, event_type_col_name, pathway_col_name],
                columns=event_col_name,
            )
            .reset_index()
            .copy()
        )

    # If no pathway column is provided, index is just the entity ID and the event type
    # This is expected to be the code actually used in most cases
    else:
        pivoted_log = (
            event_log[event_log[event_type_col_name] == "arrival_departure"]
            .pivot_table(
                values=time_col_name,
                index=[entity_col_name, event_type_col_name],
                columns=event_col_name,
            )
            .reset_index()
            .copy()
        )

    # Add in behaviour for if limit_duration is None (which strictly speaking it shouldn't be,
    # but should improve behaviour if users try to do this)
    if limit_duration is None:
        limit_duration = int(round(max(pivoted_log[time_col_name]), 0))
        warnings.warn(
            f"`None` was provided for the limit_duration argument."
            f"This is not an officially supported input, so has been set to {limit_duration}.",
            UserWarning,
            stacklevel=3,
        )

    ################################################################################
    # Iterate through every matching minute
    # and generate snapshot df of position of any entities present at that moment
    # (i.e. dataframe per 'snapshot time' of the most recent position of every
    # entity present in the model at that time)
    # e.g. if they joined the treatment queue at time 72, and started treatment at
    # time 85, then departed at time 93
    # - at snapshot_time 80, they would have a last event of joined_treatment_queue
    # - at snapshot_time 90, they would have a last event of started_treatment
    # - at snapshot_time 100, they would not appear (as they have departed)
    ################################################################################
    # Note that we want to do this for everything up to AND INCLUDING the full duration we've passed
    # as the limit
    for time_unit in range(limit_duration + every_x_time_units):
        # Get entities who
        # - arrived before the current minute
        # - and who left the system after the current minute
        # (or arrived but didn't reach the point of being seen before the model run ended)
        if time_unit % every_x_time_units == 0:
            try:
                # Work out which entities - if any - were present in the simulation at the current time
                # They will have arrived at or before the minute in question, and they will depart at
                # or after the minute in question, or never depart during our model run
                # (which can happen if they arrive towards the end, or there is a bottleneck)
                current_entities_in_moment = pivoted_log[
                    (
                        pivoted_log["arrival"] <= time_unit
                    )  # Arrived before or at the current time
                    & (
                        (
                            pivoted_log["depart"] >= time_unit
                        )  # Left after or at the current time
                        | (
                            pivoted_log["depart"].isnull()
                        )  # Or never left (due to model ending first)
                    )
                ][entity_col_name].values
            except KeyError:
                current_entities_in_moment = (
                    []
                )  # Use an empty list for consistency

            # If we do have any entities, they will have been passed as a list
            # so now just filter our event log down to the events these entities have been
            # involved in
            if len(current_entities_in_moment) > 0:
                # Grab just those entities from the filtered log (the unpivoted version)

                # Filter out any events that have taken place after the minute we are interested in

                entity_minute_df = event_log[
                    (
                        event_log[entity_col_name].isin(
                            current_entities_in_moment
                        )
                    )
                    & (event_log[time_col_name] <= time_unit)
                ]

                # Each entity can only be in a single place at once

                # TODO: Are there instances where this assumption may be broken, and how would we
                # handle them? e.g. someone who is in a ward but waiting for an x-ray to be read
                # could need to be represented in both queues simultaneously

                # We have filtered out events that occurred *later* than the current minute,
                # so now take the latest/most recent event that has taken place for each entity
                most_recent_events_time_unit_ungrouped = (
                    entity_minute_df.reset_index(drop=False)
                    .sort_values([time_col_name, "index"], ascending=True)
                    .groupby([entity_col_name])
                    .tail(1)
                )

                # Now rank entities within a given event by the order
                # in which they turned up to that event (so we are effectively calculating their
                # visual queue position, which ensures consistent positioning and a 'queue-like'
                # progression through the animation)
                most_recent_events_time_unit_ungrouped["rank"] = (
                    most_recent_events_time_unit_ungrouped.groupby(
                        [event_col_name]
                    )["index"].rank(method="first")
                )

                # Calculate the total number of entities observed in this step
                most_recent_events_time_unit_ungrouped["max"] = (
                    most_recent_events_time_unit_ungrouped.groupby(
                        event_col_name
                    )["rank"].transform("max")
                )

                # ----------------------------------------------------------------------------- #

                # Now limit the rows to anything below or equal to the step_snapshot_max
                # (so we shed excessive rows here to help manage the size of the resulting
                # output and, eventually, the animation)

                # First we exclude event types that should not be part of snapshot logic
                excluded_types = ["resource_use", "resource_use_end"]

                # Apply snapshot logic per event
                def process_event_group(df):
                    if df[event_type_col_name].iloc[0] in excluded_types:
                        return df  # Return unchanged
                    else:
                        # Keep only top (step_snapshot_max + 1) ranks
                        df = df[df["rank"] <= (step_snapshot_max + 1)].copy()

                        # Identify max rank row (to possibly add 'additional' column)
                        max_row = df[
                            df["rank"] == float(step_snapshot_max + 1)
                        ].copy()
                        if len(max_row) > 0:
                            max_row["additional"] = (
                                max_row["max"] - max_row["rank"]
                            )
                            df = pd.concat(
                                [
                                    df[
                                        df["rank"]
                                        != float(step_snapshot_max + 1)
                                    ],
                                    max_row,
                                ],
                                ignore_index=True,
                            )
                        return df

                # Apply the per-event logic to each row
                most_recent_events_time_unit_ungrouped = (
                    most_recent_events_time_unit_ungrouped.groupby(
                        event_col_name, group_keys=False
                    ).apply(process_event_group)
                )

                # Clean up and store snapshot in our list of snapshots, which will all be
                # concatenated into one large dataframe at the end
                entity_dfs.append(
                    most_recent_events_time_unit_ungrouped.drop(
                        columns="max", errors="ignore"
                    ).assign(snapshot_time=time_unit)
                )

            else:
                # If no entities, append a DataFrame with just the snapshot_time
                # This creates a row with NaN for all other columns, preserving the time step so we
                # don't get odd time skips in the final animation.
                empty_df = pd.DataFrame([{"snapshot_time": time_unit}])
                entity_dfs.append(empty_df)

    if debug_mode:
        print(
            f"Iteration through time-unit-by-time-unit logs complete {time.strftime('%H:%M:%S', time.localtime())}"
        )

    # Join together all entity dfs - so the dataframe created per time snapshot - are put into
    # one large dataframe
    full_entity_df = (pd.concat(entity_dfs, ignore_index=True)).reset_index(
        drop=True
    )

    if debug_mode:
        print(
            f"Snapshot df concatenation complete at {time.strftime('%H:%M:%S', time.localtime())}"
        )

    if save_intermediate_outputs is not False:
        event_log.to_csv(
            path_or_buf=f"{extra_path}_0_event_log.csv", index=True
        )
        pivoted_log.to_csv(
            path_or_buf=f"{extra_path}_1_pivoted_log.csv", index=True
        )
        full_entity_df.to_csv(
            path_or_buf=f"{extra_path}_2_full_entity_df.csv", index=True
        )

    # We no longer need to keep the individual dataframes in that list, so get rid of them
    # to free up memory asap
    del entity_dfs
    gc.collect()

    # Add a final exit step for each entity

    # This is helpful as it ensures all entities are visually seen to exit rather than
    # just disappearing after their final step

    # It makes it easier to track the split of people going on to an optional step when
    # this step is at the end of the pathway

    # First, get the last step for every single entity
    final_step = (
        full_entity_df.sort_values(
            [entity_col_name, "snapshot_time"], ascending=True
        )
        .groupby(entity_col_name)
        .tail(1)
        .copy()
    )

    # Propose their 'exit' time
    final_step["snapshot_time"] = (
        final_step["snapshot_time"] + every_x_time_units
    )
    final_step[event_col_name] = "depart"

    # Only keep rows for people whose exit step will happen *before* the simulation end
    final_step = final_step[final_step["snapshot_time"] <= (limit_duration)]

    # Change the event_type of the final step to more accurately reflect what it is
    final_step["event_type"] = "exit"

    full_entity_df = pd.concat([full_entity_df, final_step], ignore_index=True)

    # We no longer need this dataframe as we have concatenated it to our main dataframe, so
    # delete it and clear up the memory it was using asap
    del final_step
    gc.collect()

    return (
        full_entity_df.sort_values(["snapshot_time", event_col_name])
        .reset_index(drop=True)
        .dropna(axis=1, how="all")
    )


@_enforce_int_params(
    [
        "step_snapshot_max",
        "gap_between_entities",
        "gap_between_resources",
        "gap_between_resource_rows",
        "gap_between_queue_rows",
    ]
)
def generate_animation_df(
    full_entity_df: pd.DataFrame,
    event_position_df: pd.DataFrame,
    wrap_queues_at: Optional[int] = 20,
    wrap_resources_at: Optional[int] = 20,
    step_snapshot_max: int = 50,
    gap_between_entities: int = 10,
    gap_between_resources: int = 10,
    gap_between_resource_rows: int = 30,
    gap_between_queue_rows: int = 30,
    time_col_name: str = "time",
    entity_col_name: str = "entity_id",
    event_type_col_name: str = "event_type",
    event_col_name: str = "event",
    resource_col_name: str = "resource_id",
    debug_mode: bool = False,
    custom_entity_icon_list: Optional[list[str]] = None,
    include_fun_emojis: bool = False,
    save_intermediate_outputs: Optional[Union[bool, str]] = False,
    minimize_output_df: bool = True,
    step_snapshot_limit_gauges=False,
    gauge_segments: int = 10,
    gauge_max_override: Optional[Union[int, float]] = None,
):
    """
    Generate a DataFrame for animation purposes by adding position information to entity data.

    This function takes entity event data and adds positional information for visualization,
    handling both queuing and resource use events.

    Parameters
    ----------
    full_entity_df : pd.DataFrame
        Output of reshape_for_animation(), containing entity event data.
    event_position_df : pd.DataFrame
        DataFrame with columns 'event', 'x', and 'y', specifying initial positions for each event type.
    wrap_queues_at : int, optional
        Number of entities in a queue before wrapping to a new row (default is 20).
    wrap_resources_at : int, optional
        Number of resources to show before wrapping to a new row (default is 20).
    step_snapshot_max : int, optional
        Maximum number of patients to show in each snapshot (default is 50).
    gap_between_entities : int, optional
        Horizontal spacing between entities in pixels (default is 10).
    gap_between_resources : int, optional
        Horizontal spacing between resources in pixels (default is 10).
    gap_between_queue_rows : int, optional
        Vertical spacing between rows in pixels (default is 30).
    gap_between_resource_rows : int, optional
        Vertical spacing between rows in pixels (default is 30).
    time_col_name : str, default="time"
        Name of the column in `event_log` that contains the timestamp of each event.
        Timestamps should represent the number of time units since the simulation began.
    entity_col_name : str, default="entity_id"
        Name of the column in `event_log` that contains the unique identifier for each entity
        (e.g., "entity_id", "entity", "patient", "patient_id", "customer", "ID").
    event_type_col_name : str, default="event_type"
        Name of the column in `event_log` that specifies the category of the event.
        Supported event types include 'arrival_departure', 'resource_use',
        'resource_use_end', and 'queue'.
    resource_col_name : str, default="resource_id"
        Name of the column for the resource identifier. Used for 'resource_use' events.
    event_col_name : str, default="event"
        Name of the column in `event_log` that specifies the actual event that occurred.
    debug_mode : bool, optional
        If True, print debug information during processing (default is False).
    custom_entity_icon_list : list, optional
        If provided, will be used as the list for entity icons. Once the end of the list is reached,
        it will loop back around to the beginning (so e.g. if a list of 8 icons is provided, entities
        1 to 8 will use the provided emoji list, and then entity 9 will use the same icon as entity 1,
        and so on.)
    include_fun_emojis : bool, default=False
        If True, include the more 'fun' emojis, such as Santa Claus. Ignored if a custom entity icon list
        is passed.
    save_intermediate_outputs: bool or str, optional
        For debugging purposes.
        If True or a string, output a series of csvs with intermediate transformed dataframes.
        If a string is passed, this will be interpreted as the path to prefix the dataframes with.
        Default is False.
    step_snapshot_limit_gauges: bool, optional
        If True, replaces the text '+ x more' with a gauge. The upper limit of the gauge is set
        by the maximum queue length observed across the simulation.

    Returns
    -------
    pd.DataFrame
        A DataFrame with added columns for x and y positions, and icons for each entity.

    Notes
    -----
    - The function handles both queuing and resource use events differently.
    - It assigns unique icons to entities for visualization.
    - Queues can be wrapped to multiple rows if they exceed a specified length.
    - The function adds a visual indicator for additional entities when exceeding the snapshot limit.

    TODO
    ----
    - Write a test to ensure that no entity ID appears in multiple places at a single time unit.
    """

    if save_intermediate_outputs is not False:
        if isinstance(save_intermediate_outputs, str):
            extra_path = save_intermediate_outputs
        else:
            extra_path = ""

    if step_snapshot_max % wrap_queues_at != 0:
        warnings.warn(
            f"`step_snapshot_max` is not a multiple of `wrap_queues_at`."
            f"The animation will display better if this is resolved.",
            UserWarning,
            stacklevel=3,
        )

    if debug_mode:
        print(
            f"Placement dataframe started construction at {time.strftime('%H:%M:%S', time.localtime())}"
        )

    # Filter to only a single replication

    # TODO: Write a test  to ensure that no patient ID appears in multiple places at a single time unit
    # and return an error if it does so

    # 29/09/2025 - consider removing as this is already done in reshape_for_animation function
    # (though method is very slightly different, but should achieve the same output)
    # Order entities within event/time unit to determine their eventual position in the line
    full_entity_df["rank"] = full_entity_df.groupby(
        [event_col_name, "snapshot_time"]
    )["snapshot_time"].rank(method="first")

    full_entity_df_plus_pos = full_entity_df.merge(
        event_position_df, on=event_col_name, how="left"
    ).sort_values([event_col_name, "snapshot_time", time_col_name])

    # Separate the empty snapshots from the entity data
    # We can identify them as rows where the entity ID is null.
    empty_snapshots = full_entity_df_plus_pos[
        full_entity_df_plus_pos[entity_col_name].isnull()
    ].copy()

    # Then a non-null entity name will be a row where an entity is tracked
    entity_data = full_entity_df_plus_pos[
        full_entity_df_plus_pos[entity_col_name].notnull()
    ].copy()

    if save_intermediate_outputs is not False:
        empty_snapshots.to_csv(
            path_or_buf=f"{extra_path}_3_empty_snapshots.csv", index=True
        )
        entity_data.to_csv(
            path_or_buf=f"{extra_path}_4_entity_data.csv", index=True
        )

    # Determine the position for any resource use steps
    resource_use = entity_data[
        entity_data[event_type_col_name] == "resource_use"
    ].copy()
    # resource_use['y_final'] =  resource_use['y']

    if len(resource_use) > 0:
        resource_use = resource_use.rename(columns={"y": "y_final"})
        resource_use["x_final"] = (
            resource_use["x"]
            - resource_use[resource_col_name] * gap_between_resources
        )

        # If we want resources to wrap at a certain queue length, do this here
        # They'll wrap at the defined point and then the queue will start expanding upwards
        # from the starting row
        if wrap_resources_at is not None:
            resource_use["row"] = np.floor(
                (resource_use[resource_col_name] - 1) / (wrap_resources_at)
            )

            resource_use["x_final"] = (
                resource_use["x_final"]
                + (
                    wrap_resources_at
                    * resource_use["row"]
                    * gap_between_resources
                )
                + gap_between_resources
            )

            resource_use["y_final"] = resource_use["y_final"] + (
                resource_use["row"] * gap_between_resource_rows
            )

    # Determine the position for any queuing steps
    queues = entity_data[entity_data["event_type"] == "queue"].copy()

    # queues['y_final'] =  queues['y']
    queues = queues.rename(columns={"y": "y_final"})
    queues["x_final"] = queues["x"] - queues["rank"] * gap_between_entities

    # If we want people to wrap at a certain queue length, do this here
    # They'll wrap at the defined point and then the queue will start expanding upwards
    # from the starting row
    if wrap_queues_at is not None:
        queues["row"] = np.floor((queues["rank"] - 1) / (wrap_queues_at))

        queues["x_final"] = (
            queues["x_final"]
            + (wrap_queues_at * queues["row"] * gap_between_entities)
            + gap_between_entities
        )

        queues["y_final"] = queues["y_final"] + (
            queues["row"] * gap_between_queue_rows
        )

    queues["x_final"] = np.where(
        queues["rank"] != step_snapshot_max + 1,
        queues["x_final"],
        queues["x_final"] - (gap_between_entities * (wrap_queues_at / 2)),
    )

    # Deal with the exit steps
    exit_steps = entity_data[entity_data[event_type_col_name] == "exit"].copy()
    exit_steps["x_final"] = exit_steps["x"]
    exit_steps["y_final"] = exit_steps["y"]

    if save_intermediate_outputs is not False:
        resource_use.to_csv(
            path_or_buf=f"{extra_path}_5_resource_use_steps.csv", index=True
        )
        queues.to_csv(path_or_buf=f"{extra_path}_6_queues.csv", index=True)
        exit_steps.to_csv(
            path_or_buf=f"{extra_path}_7_exit_steps.csv", index=True
        )

    if len(resource_use) > 0:
        processed_entities_df = pd.concat(
            [queues, resource_use, exit_steps], ignore_index=True
        )
        del resource_use, queues, exit_steps
    else:
        processed_entities_df = pd.concat(
            [queues, exit_steps], ignore_index=True
        )
        del queues, exit_steps

    # Add the empty snapshots back into the main dataframe
    full_entity_df_plus_pos = pd.concat(
        [processed_entities_df, empty_snapshots], ignore_index=True
    )

    if debug_mode:
        print(
            f"Placement dataframe finished construction at {time.strftime('%H:%M:%S', time.localtime())}"
        )

    # full_patient_df_plus_pos['icon'] = '🙍'

    # TODO: Add warnings if duplicates are found (because in theory they shouldn't be)
    individual_entities = (
        full_entity_df[entity_col_name].drop_duplicates().sort_values()
    )

    # Recommend https://emojipedia.org/ for finding emojis to add to list
    # note that best compatibility across systems can be achieved by using
    # emojis from v12.0 and below - Windows 10 got no more updates after that point

    if custom_entity_icon_list is None:
        icon_list = [
            "🧔🏼",
            "👨🏿‍🦯",
            "👨🏻‍🦰",
            "🧑🏻",
            "👩🏿‍🦱",
            "🤰",
            "👳🏽",
            "👩🏼‍🦳",
            "👨🏿‍🦳",
            "👩🏼‍🦱",
            "🧍🏽‍♀️",
            "👨🏼‍🔬",
            "👩🏻‍🦰",
            "🧕🏿",
            "👨🏼‍🦽",
            "👴🏾",
            "👨🏼‍🦱",
            "👷🏾",
            "👧🏿",
            "🙎🏼‍♂️",
            "👩🏻‍🦲",
            "🧔🏾",
            "🧕🏻",
            "👨🏾‍🎓",
            "👨🏾‍🦲",
            "👨🏿‍🦰",
            "🙍🏼‍♂️",
            "🙋🏾‍♀️",
            "👩🏻‍🔧",
            "👨🏿‍🦽",
            "👩🏼‍🦳",
            "👩🏼‍🦼",
            "🙋🏽‍♂️",
            "👩🏿‍🎓",
            "👴🏻",
            "🤷🏻‍♀️",
            "👶🏾",
            "👨🏻‍✈️",
            "🙎🏿‍♀️",
            "👶🏻",
            "👴🏿",
            "👨🏻‍🦳",
            "👩🏽",
            "👩🏽‍🦳",
            "🧍🏼‍♂️",
            "👩🏽‍🎓",
            "👱🏻‍♀️",
            "👲🏼",
            "🧕🏾",
            "👨🏻‍🦯",
            "🧔🏿",
            "👳🏿",
            "🤦🏻‍♂️",
            "👩🏽‍🦰",
            "👨🏼‍✈️",
            "👨🏾‍🦲",
            "🧍🏾‍♂️",
            "👧🏼",
            "🤷🏿‍♂️",
            "👨🏿‍🔧",
            "👱🏾‍♂️",
            "👨🏼‍🎓",
            "👵🏼",
            "🤵🏿",
            "🤦🏾‍♀️",
            "👳🏻",
            "🙋🏼‍♂️",
            "👩🏻‍🎓",
            "👩🏼‍🌾",
            "👩🏾‍🔬",
            "👩🏿‍✈️",
            "👵🏿",
            "🤵🏻",
            "🤰",
        ]

        if include_fun_emojis:
            additional_fun_icon_list = [
                "🎅🏼",
                "👽",
                "🤸",
                "🧜",
                "🏇",
                "🧟",
                "🧞",
                "🧚",
                "🧙",
                "🦹",
                "🦸",
            ]

            icon_list.extend(additional_fun_icon_list)
    else:
        icon_list = custom_entity_icon_list.copy()

    full_icon_list = icon_list * int(
        np.ceil(len(individual_entities) / len(icon_list))
    )

    full_icon_list = full_icon_list[0 : len(individual_entities)]

    full_entity_df_plus_pos = full_entity_df_plus_pos.merge(
        pd.DataFrame(
            {
                entity_col_name: list(individual_entities),
                "icon": full_icon_list,
            }
        ),
        on=entity_col_name,
    )

    if "additional" in full_entity_df_plus_pos.columns:
        exceeded_snapshot_limit = full_entity_df_plus_pos[
            full_entity_df_plus_pos["additional"].notna()
        ].copy()

        if step_snapshot_limit_gauges:
            # Calculate the maximum queue length seen at any step across the whole animation
            # This will be used to calculate the upper limit of the gauges across all steps
            # so there is a consistent length that they can be used to compare across
            max_count = max(exceeded_snapshot_limit["additional"])

            # If step snapshot max is very low, we don't want to display the icon as '+ x more' -
            # we simply want to display it as 'x'
            if step_snapshot_max <= 1:
                display_fig_string = "raw"
            else:
                display_fig_string = "more"

            # Update the icon column conditionally
            exceeded_snapshot_limit["icon"] = exceeded_snapshot_limit.apply(
                lambda row: ascii_queue_icon(
                    icon=row["icon"],
                    count=row["additional"],
                    max_count=(
                        max_count
                        if gauge_max_override is None
                        else gauge_max_override
                    ),
                    bar_length=gauge_segments,
                    display_count_as_fig=True,
                    count_string_format=display_fig_string,
                ),
                axis=1,
            )

        else:
            exceeded_snapshot_limit["icon"] = exceeded_snapshot_limit[
                "additional"
            ].apply(lambda x: f"+ {int(x):5d} more")

        # 29/09/25 We will replace the entity_id of any instance where we have a bar or
        # text string indicating excess queues with a consistent ID for that particular event.
        # This prevents these icons from 'flying in' each time a new individual enters the
        # animation, making the animation more stable-looking and visually pleasing.
        exceeded_snapshot_limit[entity_col_name] = exceeded_snapshot_limit[
            event_col_name
        ].apply(_event_to_icon_id)

        full_entity_df_plus_pos = pd.concat(
            [
                full_entity_df_plus_pos[
                    full_entity_df_plus_pos["additional"].isna()
                ],
                exceeded_snapshot_limit,
            ],
            ignore_index=True,
        )

    full_entity_df_plus_pos["opacity"] = 1.0

    full_entity_df_plus_pos = full_entity_df_plus_pos.sort_values(
        [entity_col_name, "snapshot_time"]
    )

    if save_intermediate_outputs is not False:
        individual_entities.to_csv(
            path_or_buf=f"{extra_path}_8_individual_entities.csv", index=True
        )
        full_entity_df_plus_pos.to_csv(
            path_or_buf=f"{extra_path}_9_full_entity_df_plus_pos_all_cols.csv",
            index=True,
        )

    # Drop any columns that are no longer strictly necessary (but may be useful to retain for debugging)
    if minimize_output_df:
        for col in ["opacity", "x", "y", "index", "run"]:
            if col in full_entity_df_plus_pos.columns:
                full_entity_df_plus_pos.drop(columns=col)

    return full_entity_df_plus_pos.dropna(axis=1, how="all")


def ascii_queue_icon(
    icon,
    count,
    max_count,
    filled_char="█",
    empty_char="░",
    bar_length=10,
    count_only=False,
    display_count_as_fig=True,
    count_string_format="more",
):
    """
    Generate an ASCII progress bar string representing the queue length.

    This can optionally be called as part of the generate_animation_df function.

    Alternatively, use that function with step_snapshot_limit_gauges set to False, and then
    call this function on the output of generate_animation_df to allow for finer-grained control
    over the output.

    Parameters
    ----------
    icon: str
        The current icon
    count : int or str
        The current entity count. If `count_only=True` and `count` is a string,
        the string will be returned directly.
    max_count : int
        The maximum entity count in the data.
    bar_length : int, optional
        Total length of the bar in characters (default is 10).
    filled_char : str, optional
        Character used for filled segments.
    empty_char : str, optional
        Character used for empty segments.
    count_only : bool, optional
        If True, only return the total entities in the step rather than a bar
        gauge (default is False).
    display_count_as_fig: bool, optional
        If True, displays the step count as a number after the bar gauge
        Ignored if count_only = True
    count_string_format: str, optional
        If "more", displays the count string after the bar as "[bar] + x more"
        Otherwise, displays it as "[bar] x"


    Returns
    -------
    str
        ASCII progress bar string representing the current queue, or the
        count value if `count_only=True`.

    Notes
    -----
    - If `max_count` is zero, a bar of only `empty_char` is returned to avoid
      division by zero.
    - If `count` is NaN, no bar is drawn.
    - An example of applying this to the output of generate_animation_df to create bars only for
    some steps can be found in
    https://hsma-tools.github.io/vidigi/examples/example_17_resourceless_larger_queues/resourceless_longer_queues.html
    """
    if max_count == 0:
        return empty_char * bar_length  # avoid division by zero

    if not np.isnan(count):
        if count_only:
            return f"{count:.0f}"
        else:
            filled_len = int(round(bar_length * count / max_count))
            bar = filled_char * filled_len + empty_char * (
                bar_length - filled_len
            )
            if display_count_as_fig:
                if count_string_format == "more":
                    return f"[{bar}] + {count:.0f} more"
                else:
                    return f"[{bar}] {count:.0f}"
    else:
        return ""


def _event_to_icon_id(event_name):
    # Hash event name, take first 6 digits, and offset to keep it large
    h = int(hashlib.md5(event_name.encode()).hexdigest(), 16)
    return 9_000_000 + (h % 1_000_000)
