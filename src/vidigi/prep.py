import gc
import time
import pandas as pd
import numpy as np
import hashlib
import warnings
from typing import Literal, Optional, TypeAlias, Union
from vidigi.utils import (
    _check_one_arrival_per_entity,
    _check_single_run,
    _enforce_int_params,
)
from packaging import version


# Sentinel so a deprecated parameter can tell "caller passed a value" apart from
# "caller left it alone", without warning everyone who simply uses the default.
_UNSET = object()

# Where the snapshot grid counts from when a warm-up period is set. Shared with
# animation.py so the two signatures cannot drift apart. Editors offer these as
# completions; the value is still validated at runtime, since annotations are not
# enforced.
SnapshotAlignment: TypeAlias = Literal["warm_up", "run_start"]


def _warn_on_entities_without_an_arrival(
    event_log: pd.DataFrame,
    pivoted_log: pd.DataFrame,
    entity_col_name: str,
    event_col_name: str,
) -> None:
    """Warn about entities that have events but no 'arrival', so are never drawn.

    Whether an entity is present at a snapshot is decided by comparing its arrival and
    departure times, so an entity with no arrival row is absent from every frame no
    matter how many other events it has. Nothing else in the pipeline notices.

    Almost always this means the log has been truncated by time to discard a warm-up
    period, which strips the arrival rows of everyone who was already in the system.
    Those are precisely the entities a steady-state animation is meant to show, so the
    queue is drawn far shorter than the model actually had it.

    A warning rather than an error: a model that legitimately never logs an arrival for
    some entities is unusual but not impossible, and this does not corrupt anything for
    the entities that *are* drawn.
    """
    entities_with_an_arrival = set(
        pivoted_log.loc[pivoted_log["arrival"].notna(), entity_col_name]
    )
    seen_entities = event_log[entity_col_name].dropna().drop_duplicates()

    # Kept in log order rather than sorted, so mixed id types cannot raise on comparison.
    missing = [
        entity for entity in seen_entities if entity not in entities_with_an_arrival
    ]
    if not missing:
        return

    examples = ", ".join(repr(entity) for entity in missing[:5])
    if len(missing) > 5:
        examples += ", ..."

    warnings.warn(
        f"{len(missing)} entities ({examples}) have events in the event log but no "
        f"'arrival' event, so they will be missing from every frame of the animation.\n"
        "\n"
        f"vidigi works out who is present at each snapshot from the arrival and "
        f"departure rows, so an entity without an arrival is never drawn.\n"
        "\n"
        f"The usual cause is discarding a warm-up period by filtering the log, e.g. "
        f"`event_log[event_log['time'] >= warm_up]`, which removes the arrival rows of "
        f"everyone already in the system - including entities that are still queuing.\n"
        "\n"
        f"To skip a warm-up period, pass the whole event log and set `warm_up` to "
        f"the end of the warm-up instead. That trims the animation window without "
        f"discarding the history it needs.",
        UserWarning,
        stacklevel=4,
    )


@_enforce_int_params(
    ["every_x_time_units", "limit_duration", "step_snapshot_max", "warm_up"],
    allow_none=["limit_duration"],
)
def reshape_for_animations(
    event_log: pd.DataFrame,
    every_x_time_units: int = 10,
    limit_duration: Optional[int] = 10 * 60 * 24,
    step_snapshot_max: int = 60,
    time_col_name: str = "time",
    entity_col_name: str = "entity_id",
    event_type_col_name: str = "event_type",
    event_col_name: str = "event",
    pathway_col_name: Optional[str] = None,
    debug_mode: bool = False,
    save_intermediate_outputs: Optional[Union[bool, str]] = False,
    run_col_name: Optional[str] = "auto",
    warm_up: int = 0,
    snapshot_alignment: SnapshotAlignment = "warm_up",
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
        The time at which the animation stops, in preferred time units (default is 10
        days). Together with `warm_up` this defines the animation window, which runs
        from `warm_up` to `limit_duration`.
    step_snapshot_max : int, optional
        The maximum number of entities to include in each snapshot for each event (default is 60).
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
    run_col_name : str or None, optional
        Name of the column identifying which simulation run (replication) each row
        belongs to, used to reject event logs containing more than one replication.
        Default is "auto", which looks for a column named (case-insensitively) one of
        'run', 'run_number', 'replication', 'rep' or 'run_id'. Pass an explicit column
        name to override the search, or `None` to disable the check.
    warm_up : int, optional
        The time at which the animation starts, in preferred time units (default is 0,
        the beginning of the run). Snapshots then run up to `limit_duration`, spaced
        `every_x_time_units` apart; `snapshot_alignment` controls exactly where that
        grid falls.

        This is how to discard a warm-up period. Pass the **whole** event log and set
        `warm_up` to the end of your warm-up; do not filter the log by time first.
        Filtering removes the 'arrival' rows of every entity that arrived during the
        warm-up, and since this function works out who is present from arrival and
        departure rows, those entities then vanish from every frame - including ones
        still queuing. `warm_up` trims the window while leaving that history intact.
    snapshot_alignment : {"warm_up", "run_start"}, optional
        Which point the snapshot grid counts from when `warm_up` is non-zero. Ignored
        when `warm_up` is 0, as the two are then identical.

        - "warm_up" (default): snapshots are taken at `warm_up`,
          `warm_up + every_x_time_units`, and so on, so the first frame lands exactly
          on the boundary and shows the state of the system as the warm-up ends.
        - "run_start": snapshots stay on the grid that runs from time 0, and those
          before `warm_up` are simply dropped. Frame times are then the same ones you
          would get with no warm-up at all, which keeps them round numbers when
          `warm_up` is not a multiple of `every_x_time_units`. This matches the
          longstanding workaround of filtering the reshaped frame by `snapshot_time`,
          except that a snapshot falling exactly on `warm_up` is kept rather than
          dropped.

        The two produce identical grids whenever `warm_up` is a multiple of
        `every_x_time_units`.

    Returns
    -------
    DataFrame
        A reshaped DataFrame containing snapshots of entity positions at regular time intervals,
        sorted by minute and event.

    Notes
    -----
    - **This function animates a single replication only.** An event log containing more
      than one run is rejected with a `ValueError`, because the runs would otherwise be
      blended together into an animation representing no run of your model. Filter your
      log first, e.g. `event_log[event_log["run"] == 1]`.
    - The function creates snapshots of entity positions at specified time intervals.
    - It handles entities who are present in the system at each snapshot time.
    - Entities are ranked within each event based on their arrival order.
    - A maximum number of patients per event can be set to limit the number of entities who will be
      displayed on screen within any one event type at a time.
    - This function assumes entities only exist in one place/queue at a time. Simulations where this
      assumption does not hold may display unexpected behaviour.
    - An 'exit' event is added for each entity at the end of their journey.
    - The function uses memory management techniques (del and gc.collect()) to handle large datasets.
    - **To skip a warm-up period, use `warm_up` rather than filtering the event log.**
      Presence at each snapshot is derived from arrival and departure rows, so a log
      truncated with something like `event_log[event_log["time"] >= warm_up]` has lost
      the arrival row of everyone who was already in the system, and those entities are
      then absent from every frame. A warning is raised if the log looks truncated this
      way, but `warm_up` avoids the problem entirely.

    TODO
    ----
    - Add behavior for when limit_duration is None.
    - Implement pathway order and precedence columns.
    - Fix the automatic exit at the end of the simulation run for all entities.
    """
    # Reject multi-replication logs before doing any work. Both checks run: the run
    # column catches a log whose entity IDs happen to be unique across runs, and the
    # duplicate-arrival check catches a log whose run column is named something we do
    # not recognise, or absent entirely.
    _check_single_run(event_log, run_col_name=run_col_name, frame_arg="event_log")
    _check_one_arrival_per_entity(
        event_log,
        entity_col_name=entity_col_name,
        event_type_col_name=event_type_col_name,
        event_col_name=event_col_name,
        pathway_col_name=pathway_col_name,
        frame_arg="event_log",
    )

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

    # The pivot above turns the 'arrival' and 'depart' event names into columns. If the
    # log contains no arrival_departure rows at all we cannot work out who is present at
    # any given moment, so say so rather than silently animating nothing.
    if "arrival" not in pivoted_log.columns:
        raise ValueError(
            f"No 'arrival' events were found in the event log. `reshape_for_animations` "
            f"identifies who is present at each snapshot using rows where "
            f"`{event_type_col_name}` is 'arrival_departure' and `{event_col_name}` is "
            f"'arrival' or 'depart'. Check that your event log contains these, and that "
            f"the `event_type_col_name` and `event_col_name` arguments match your columns."
        )

    # If nobody has departed - a truncated run, or a model whose entities never leave -
    # there is no 'depart' column to compare against. Treat every entity as still in the
    # system, which is what an absent departure means.
    if "depart" not in pivoted_log.columns:
        pivoted_log["depart"] = np.nan

    # Presence is decided further down by `pivoted_log["arrival"] <= time_unit`, and
    # `NaN <= t` is False, so an entity with no arrival row is silently absent from
    # every frame however many other events it has. The usual cause is a log truncated
    # by time to discard a warm-up period, which strips the arrival rows of everyone
    # already in the system - exactly the entities the modeller is trying to look at.
    _warn_on_entities_without_an_arrival(
        event_log,
        pivoted_log,
        entity_col_name=entity_col_name,
        event_col_name=event_col_name,
    )

    # Add in behaviour for if limit_duration is None (which strictly speaking it shouldn't be,
    # but should improve behaviour if users try to do this)
    if limit_duration is None:
        limit_duration = int(round(event_log[time_col_name].max(), 0))
        warnings.warn(
            f"`None` was provided for the limit_duration argument."
            f"This is not an officially supported input, so has been set to {limit_duration}.",
            UserWarning,
            stacklevel=3,
        )

    if warm_up < 0:
        raise ValueError(
            f"`warm_up` must not be negative, but {warm_up} was passed. It is the "
            f"time at which the animation begins, measured from the start of the run."
        )

    if warm_up > limit_duration:
        raise ValueError(
            f"`warm_up` ({warm_up}) is after `limit_duration` ({limit_duration}), "
            f"so the animation window is empty and no frames can be produced. These "
            f"bound the window between them: the animation runs from `warm_up` to "
            f"`limit_duration`."
        )

    # Which point the snapshot grid counts from. Anchoring on `warm_up` puts the first
    # frame exactly on the boundary; anchoring on the start of the run keeps the frame
    # times a caller would have got without a warm-up, and simply drops the early ones.
    # The two coincide whenever `warm_up` is a multiple of `every_x_time_units`.
    if snapshot_alignment == "warm_up":
        grid_origin = warm_up
    elif snapshot_alignment == "run_start":
        grid_origin = 0
    else:
        raise ValueError(
            f"Invalid snapshot_alignment option provided: '{snapshot_alignment}'. "
            f"Valid options are: 'warm_up' (snapshots start exactly at `warm_up`) and "
            f"'run_start' (snapshots stay on the grid running from time 0, and those "
            f"before `warm_up` are dropped)."
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
    # By default the snapshot grid is anchored on `warm_up` rather than on zero, so the
    # first frame lands exactly on the requested start instead of at whichever interval
    # boundary happens to follow it. At the default `warm_up=0` both alignments give
    # the same grid as before.
    for time_unit in range(warm_up, limit_duration + every_x_time_units):
        # Get entities who
        # - arrived before the current minute
        # - and who left the system after the current minute
        # (or arrived but didn't reach the point of being seen before the model run ended)
        if (time_unit - grid_origin) % every_x_time_units == 0:
            # Work out which entities - if any - were present in the simulation at the current time
            # They will have arrived at or before the minute in question, and they will depart at
            # or after the minute in question, or never depart during our model run
            # (which can happen if they arrive towards the end, or there is a bottleneck)
            # Both 'arrival' and 'depart' are guaranteed to exist as columns by this point.
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

            # If we do have any entities, they will have been passed as a list
            # so now just filter our event log down to the events these entities have been
            # involved in
            if len(current_entities_in_moment) > 0:
                # Grab just those entities from the filtered log (the unpivoted version)

                # Filter out any events that have taken place after the minute we are interested in

                entity_minute_df = event_log[
                    (event_log[entity_col_name].isin(current_entities_in_moment))
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
                    most_recent_events_time_unit_ungrouped.groupby([event_col_name])[
                        "index"
                    ].rank(method="first")
                )

                # Calculate the total number of entities observed in this step
                most_recent_events_time_unit_ungrouped["max"] = (
                    most_recent_events_time_unit_ungrouped.groupby(event_col_name)[
                        "rank"
                    ].transform("max")
                )

                # ----------------------------------------------------------------------------- #

                # Now limit the rows to anything below or equal to the step_snapshot_max
                # (so we shed excessive rows here to help manage the size of the resulting
                # output and, eventually, the animation)

                # First we exclude event types that should not be part of snapshot logic
                excluded_types = ["resource_use", "resource_use_end"]

                # ----------------------------------------------------------------------------- #
                # Vectorized Cap Logic (Replaces process_event_group and groupby.apply)
                # ----------------------------------------------------------------------------- #
                excluded_types = ["resource_use", "resource_use_end"]

                # 1. Separate data into what needs capping and what doesn't
                to_process_mask = ~most_recent_events_time_unit_ungrouped[event_type_col_name].isin(excluded_types)

                # 2. Filter out rows where rank exceeds step_snapshot_max + 1 (only for non-excluded types)
                keep_mask = (~to_process_mask) | (most_recent_events_time_unit_ungrouped["rank"] <= (step_snapshot_max + 1))
                most_recent_events_time_unit_ungrouped = most_recent_events_time_unit_ungrouped[keep_mask].copy()

                # 3. Calculate the 'additional' column value only for the boundary rows
                # (Re-evaluate masks on the trimmed dataframe)
                still_processing_mask = ~most_recent_events_time_unit_ungrouped[event_type_col_name].isin(excluded_types)
                boundary_row_mask = still_processing_mask & (most_recent_events_time_unit_ungrouped["rank"] == float(step_snapshot_max + 1))

                most_recent_events_time_unit_ungrouped.loc[boundary_row_mask, "additional"] = (
                    most_recent_events_time_unit_ungrouped.loc[boundary_row_mask, "max"] - most_recent_events_time_unit_ungrouped.loc[boundary_row_mask, "rank"]
                )

                most_recent_events_time_unit_ungrouped = most_recent_events_time_unit_ungrouped.reset_index(drop=True)

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
    full_entity_df = (pd.concat(entity_dfs, ignore_index=True)).reset_index(drop=True)

    if debug_mode:
        print(
            f"Snapshot df concatenation complete at {time.strftime('%H:%M:%S', time.localtime())}"
        )

    if save_intermediate_outputs is not False:
        event_log.to_csv(path_or_buf=f"{extra_path}_0_event_log.csv", index=True)
        pivoted_log.to_csv(path_or_buf=f"{extra_path}_1_pivoted_log.csv", index=True)
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
        full_entity_df.sort_values([entity_col_name, "snapshot_time"], ascending=True)
        .groupby(entity_col_name)
        .tail(1)
        .copy()
    )

    # Propose their 'exit' time
    final_step["snapshot_time"] = final_step["snapshot_time"] + every_x_time_units
    final_step[event_col_name] = "depart"

    # Only keep rows for people whose exit step will happen *before* the simulation end
    final_step = final_step[final_step["snapshot_time"] <= (limit_duration)]

    # Change the event_type of the final step to more accurately reflect what it is.
    # This must use the caller's event type column - writing to a literal "event_type"
    # creates a second, mostly-empty type column when a custom name is in use.
    final_step[event_type_col_name] = "exit"

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
    step_snapshot_max: int = 60,
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
    minimize_output_df=_UNSET,
    run_col_name: Optional[str] = "auto",
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
        Maximum number of patients to show in each snapshot (default is 60).
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
    minimize_output_df: bool, optional
        .. deprecated::
            This parameter has never had any effect and is ignored. All columns are
            retained regardless of the value passed. Passing it emits a
            DeprecationWarning. Column dropping is planned for vidigi 2.0.
    run_col_name : str or None, optional
        Name of the column identifying which simulation run (replication) each row
        belongs to, used to reject data containing more than one replication.
        Default is "auto", which looks for a column named (case-insensitively) one of
        'run', 'run_number', 'replication', 'rep' or 'run_id'. Pass an explicit column
        name to override the search, or `None` to disable the check.
    step_snapshot_limit_gauges: bool, optional
        If True, replaces the text '+ x more' with a gauge. The upper limit of the gauge is set
        by the maximum queue length observed across the simulation.

    Returns
    -------
    pd.DataFrame
        A DataFrame with added columns for x and y positions, and icons for each entity.

    Notes
    -----
    - **This function positions a single replication only.** Data containing more than
      one run is rejected with a `ValueError`. The run column survives
      `reshape_for_animations`, so a multi-replication log is caught here as well as
      there.
    - The function handles both queuing and resource use events differently.
    - It assigns unique icons to entities for visualization.
    - Queues can be wrapped to multiple rows if they exceed a specified length.
    - The function adds a visual indicator for additional entities when exceeding the snapshot limit.

    TODO
    ----
    - Write a test to ensure that no entity ID appears in multiple places at a single time unit.
    """

    # The run column survives reshape_for_animations, so a multi-replication log that
    # reached this far - for instance by calling the three pipeline steps by hand - is
    # still caught here rather than being positioned into a blended animation.
    _check_single_run(
        full_entity_df, run_col_name=run_col_name, frame_arg="full_entity_df"
    )

    if save_intermediate_outputs is not False:
        if isinstance(save_intermediate_outputs, str):
            extra_path = save_intermediate_outputs
        else:
            extra_path = ""

    # `wrap_queues_at=None` means "do not wrap", which is handled further down. Only
    # check the multiple when wrapping is actually in use.
    if wrap_queues_at is not None and step_snapshot_max % wrap_queues_at != 0:
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

    # Note: this function does NOT filter to a single replication - it cannot, as the
    # snapshotting has already happened by this point. A multi-replication log is
    # rejected up front by the `_check_single_run` call above and in
    # `reshape_for_animations`.

    # 29/09/2025 - consider removing as this is already done in reshape_for_animation function
    # (though method is very slightly different, but should achieve the same output)
    # Order entities within event/time unit to determine their eventual position in the line
    full_entity_df["rank"] = full_entity_df.groupby([event_col_name, "snapshot_time"])[
        "snapshot_time"
    ].rank(method="first")

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
        entity_data.to_csv(path_or_buf=f"{extra_path}_4_entity_data.csv", index=True)

    # Determine the position for any resource use steps
    resource_use = entity_data[
        entity_data[event_type_col_name] == "resource_use"
    ].copy()
    # resource_use['y_final'] =  resource_use['y']

    if len(resource_use) > 0:
        resource_use = resource_use.rename(columns={"y": "y_final"})
        resource_use["x_final"] = (
            resource_use["x"] - resource_use[resource_col_name] * gap_between_resources
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
                + (wrap_resources_at * resource_use["row"] * gap_between_resources)
                + gap_between_resources
            )

            resource_use["y_final"] = resource_use["y_final"] + (
                resource_use["row"] * gap_between_resource_rows
            )

    # Determine the position for any queuing steps
    queues = entity_data[entity_data[event_type_col_name] == "queue"].copy()

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

        queues["y_final"] = queues["y_final"] + (queues["row"] * gap_between_queue_rows)

    # Nudge the overflow row's "+ x more" label towards the middle of the queue row so it
    # does not sit flush against the front of the queue. With no wrapping there is no row
    # to centre it within, so it stays where its rank puts it.
    # np.where evaluates both branches, so the division must be guarded rather than
    # relying on the condition to short-circuit it.
    if wrap_queues_at is not None:
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
        exit_steps.to_csv(path_or_buf=f"{extra_path}_7_exit_steps.csv", index=True)

    # Handle any additional steps
    other = entity_data[
        ~(entity_data[event_type_col_name].isin(["queue", "resource_use", "exit"]))
    ].copy()
    other["x_final"] = other["x"]
    other["y_final"] = other["y"]

    if len(resource_use) > 0:
        processed_entities_df = pd.concat(
            [queues, resource_use, exit_steps, other], ignore_index=True
        )
        del resource_use, queues, exit_steps
    else:
        processed_entities_df = pd.concat(
            [queues, exit_steps, other], ignore_index=True
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

    full_icon_list = icon_list * int(np.ceil(len(individual_entities) / len(icon_list)))

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
                        max_count if gauge_max_override is None else gauge_max_override
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
                full_entity_df_plus_pos[full_entity_df_plus_pos["additional"].isna()],
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

    # `minimize_output_df` has never had any effect: the loop that was meant to implement
    # it called .drop() without assigning the result, so every column was retained
    # regardless. Rather than start dropping columns now - which would change the output
    # of every existing caller, including removing `run` - the parameter is deprecated and
    # left inert. Columns will be dropped in 2.0.
    if minimize_output_df is not _UNSET:
        warnings.warn(
            "`minimize_output_df` has never had any effect and is deprecated. It is "
            "currently ignored, and all columns are retained. Column dropping will be "
            "introduced in vidigi 2.0; pass no value to keep the current behaviour.",
            DeprecationWarning,
            stacklevel=3,
        )

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
            bar = filled_char * filled_len + empty_char * (bar_length - filled_len)
            if display_count_as_fig:
                if count_string_format == "more":
                    return f"[{bar}] + {count:.0f} more"
                else:
                    return f"[{bar}] {count:.0f}"
    else:
        return ""


def _event_to_icon_id(event_name):
    safe_name = str(event_name)
    # Hash event name, take first 6 digits, and offset to keep it large
    h = int(hashlib.md5(safe_name.encode()).hexdigest(), 16)
    return 9_000_000 + (h % 1_000_000)
