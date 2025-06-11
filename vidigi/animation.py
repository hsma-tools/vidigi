import datetime as dt
import time
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from vidigi.prep import reshape_for_animations, generate_animation_df
import numpy as np
from copy import deepcopy


def generate_animation(
        full_entity_df_plus_pos,
        event_position_df,
        scenario=None,
        time_col_name="time",
        entity_col_name="entity_id",
        event_col_name="event",
        resource_col_name="resource_id",
        pathway_col_name=None,
        simulation_time_unit="minutes",
        plotly_height=900,
        plotly_width=None,
        include_play_button=True,
        add_background_image=None,
        display_stage_labels=True,
        entity_icon_size=24,
        text_size=24,
        resource_icon_size=24,
        override_x_max=None,
        override_y_max=None,
        time_display_units=None,
        start_date=None,
        start_time=None,
        resource_opacity=0.8,
        custom_resource_icon=None,
        wrap_resources_at=20,
        gap_between_resources=10,
        gap_between_resource_rows=30,
        setup_mode=False,
        frame_duration=400, #milliseconds
        frame_transition_duration=600, #milliseconds
        debug_mode=False
):
    """
    Generate an animated visualization of patient flow through a system.

    This function creates an interactive Plotly animation based on patient data and event positions.

    Parameters
    ----------
    full_entity_df_plus_pos : pd.DataFrame
        DataFrame containing entity data with position information.
        This will be the output of passing an event log through the reshape_for_animations()
        and generate_animation_df() functions
    event_position_df : pd.DataFrame
        DataFrame specifying the positions of different events.
    scenario : object, optional
        Object containing attributes for resource counts at different steps.
        time_col_name : str, default="time"
        Name of the column in `event_log` that contains the timestamp of each event.
        Timestamps should represent the number of time units since the simulation began.
    entity_col_name : str, default="entity_id"
        Name of the column in `event_log` that contains the unique identifier for each entity
        (e.g., "entity_id", "entity", "patient", "patient_id", "customer", "ID").
    event_col_name : str, default="event"
        Name of the column in `event_log` that specifies the actual event that occurred.
    pathway_col_name : str, optional, default=None
        Name of the column in `event_log` that identifies the specific pathway or
        process flow the entity is following. If `None`, it is assumed that pathway
        information is not present.
    resource_col_name : str, default="resource_id"
        Name of the column for the resource identifier. Used for 'resource_use' events.
    simulation_time_unit: string, optional
        Time unit used within the simulation (default is minutes).
        Possible values are 'seconds', 'minutes', 'hours', 'days', 'weeks', 'years'
    plotly_height : int, optional
        Height of the Plotly figure in pixels (default is 900).
    plotly_width : int, optional
        Width of the Plotly figure in pixels (default is None).
    include_play_button : bool, optional
        Whether to include a play button in the animation (default is True).
    add_background_image : str, optional
        Path to a background image file to add to the animation (default is None).
    display_stage_labels : bool, optional
        Whether to display labels for each stage (default is True).
    entity_icon_size : int, optional
        Size of entity icons in the animation (default is 24).
    text_size : int, optional
        Size of text labels in the animation (default is 24).
    resource_icon_size : int, optional
        Size of resource icons in the animation (default is 24).
    override_x_max : int, optional
        Override the maximum x-coordinate (default is None).
    override_y_max : int, optional
        Override the maximum y-coordinate (default is None).
        time_display_units : str, optional
        Format for displaying time on the animation timeline. This affects how simulation time is
        converted into human-readable dates or clock formats. If `None` (default), the raw simulation
        time is used.

        Predefined options:
        - 'dhms' : Day Month Year + HH:MM:SS (e.g., "06 June 2025\n14:23:45")
        - 'dhms_ampm' : Same as 'dhms', but in 12-hour format with AM/PM (e.g., "06 June 2025\n02:23:45 PM")
        - 'dhm'  : Day Month Year + HH:MM (e.g., "06 June 2025\n14:23")
        - 'dhm_ampm' : 12-hour format with AM/PM (e.g., "06 June 2025\n02:23 PM")
        - 'dh'   : Day Month Year + HH (e.g., "06 June 2025\n14")
        - 'dh_ampm' : 12-hour format with AM/PM (e.g., "06 June 2025\n02 PM")
        - 'd'    : Full weekday and date (e.g., "Friday 06 June 2025")
        - 'm'    : Month and year (e.g., "June 2025")
        - 'y'    : Year only (e.g., "2025")
        - 'day_clock' or 'simulation_day_clock':
            Show simulation-relative day and time (e.g., "Simulation Day 3\n14:15")
        - 'day_clock_ampm' or 'simulation_day_clock_ampm':
            Same as above, but time is shown in 12-hour clock with AM/PM (e.g., "Simulation Day 3\n02:15 PM")

        Alternatively, you can supply a custom [strftime](https://strftime.org/) format string
        (e.g., '%Y-%m-%d %H') to control the display manually.
    start_date : str, optional
        Start date for the animation in 'YYYY-MM-DD' format. Only used when time_display_units is 'd' or 'dhm' (default is None).
    start_time : str, optional
        Start date for the animation in 'HH:MM:SS' format. Only used when time_display_units is 'd' or 'dhm' (default is None).
    resource_opacity : float, optional
        Opacity of resource icons (default is 0.8).
    custom_resource_icon : str, optional
        Custom icon to use for resources (default is None).
    wrap_resources_at : int, optional
        Number of resources to show before wrapping to a new row (default is 20).
        If this has been set elsewhere, it is also important to set it in this function to ensure
        the visual indicators of the resources wrap in the same way the entities using those
        resources do.
    gap_between_resources : int, optional
        Spacing between resources in pixels (default is 10).
    gap_between_resource_rows : int, optional
        Vertical spacing between rows in pixels (default is 30).
    setup_mode : bool, optional
        Whether to run in setup mode, showing grid and tick marks (default is False).
    frame_duration : int, optional
        Duration of each frame in milliseconds (default is 400).
    frame_transition_duration : int, optional
        Duration of transition between frames in milliseconds (default is 600).
    debug_mode : bool, optional
        Whether to run in debug mode with additional output (default is False).

    Returns
    -------
    plotly.graph_objs._figure.Figure
        An animated Plotly figure object representing the patient flow.

    Notes
    -----
    - The function uses Plotly Express to create an animated scatter plot.
    - Time can be displayed as actual dates or as model time units.
    - The animation supports customization of icon sizes, resource representation, and animation speed.
    - A background image can be added to provide context for the patient flow.
    - If `time_display_units` is specified, the simulation time is converted into real-world
      datetimes using the `simulation_time_unit` and optionally `start_date` and `start_time`.
    - If `start_date` and/or `start_time` are not provided, a default offset from today's date
      is used.
    - The `snapshot_time` column is transformed to datetime strings, and a `snapshot_time_display`
      column is created for visual display.

    Examples
    --------
    >>> animation = generate_animation(patient_df, event_positions, scenario,
    ...                                time_display_units='dhm',
    ...                                add_background_image='path/to/image.png')
    >>> animation.show()
    """
    full_entity_df_plus_pos_copy = full_entity_df_plus_pos.copy()

    if override_x_max is not None:
        x_max = override_x_max
    else:
        x_max = event_position_df['x'].max()*1.25

    if override_y_max is not None:
        y_max = override_y_max
    else:
        y_max = event_position_df['y'].max()*1.1

    # If we're displaying time as a clock instead of as units of whatever time our model
    # is working in, create a snapshot_time_display column that will display as a psuedo datetime

    # We need to keep the original snapshot time and exact time columns in existance because they're
    # important for sorting
    full_entity_df_plus_pos_copy["snapshot_time_base"] = full_entity_df_plus_pos_copy["snapshot_time"]

    # Assuming time display units are set to something other

    if time_display_units is not None:

        if simulation_time_unit in ("second", "seconds"):
            unit = "s"
        elif simulation_time_unit in ("minute", "minutes"):
            unit = "m"
        elif simulation_time_unit in ("hour", "hours"):
            unit = "h"
        elif simulation_time_unit in ("day", "days"):
            unit = "d"
        elif simulation_time_unit in ("week", "weeks"):
            unit = "w"
        elif simulation_time_unit in ("month", "months"):
            # Approximate 1 month as 30 days
            full_entity_df_plus_pos_copy["snapshot_time"] *= 30
            unit = "d"
        elif simulation_time_unit in ("year", "years"):
            # Approximate 1 year as 365 days
            full_entity_df_plus_pos_copy["snapshot_time"] *= 365
            unit = "d"

        if start_date is None and start_time is None:
            full_entity_df_plus_pos_copy["snapshot_time"] = (
                dt.date.today() +
                pd.DateOffset(days=165) +
                pd.TimedeltaIndex(full_entity_df_plus_pos_copy["snapshot_time"], unit=unit)
                )

        elif start_date is not None and start_time is None:

            full_entity_df_plus_pos_copy["snapshot_time"] = (
                dt.datetime.strptime(start_date, "%Y-%m-%d") +
                pd.TimedeltaIndex(full_entity_df_plus_pos_copy["snapshot_time"], unit=unit)
                )

        else:
            start_time_dt = dt.datetime.strptime(start_time, "%H:%M:%S")

            start_time_time_delta = dt.timedelta(
                    hours=start_time_dt.hour,
                    minutes=start_time_dt.minute,
                    seconds=start_time_dt.second
                )

            if start_date is None:
                full_entity_df_plus_pos_copy["snapshot_time"] = (
                    dt.date.today() +
                    pd.DateOffset(days=165) +
                    start_time_time_delta +
                    pd.TimedeltaIndex(full_entity_df_plus_pos_copy["snapshot_time"], unit=unit)
                    )

            else:
                full_entity_df_plus_pos_copy["snapshot_time"] = (
                    dt.datetime.strptime(start_date, "%Y-%m-%d") +
                    start_time_time_delta +
                    pd.TimedeltaIndex(full_entity_df_plus_pos_copy["snapshot_time"], unit=unit)
                    )

        # https://strftime.org/
        if time_display_units in ("dhms", "dhms_ampm"):
            fmt = '%d %B %Y\n%I:%M:%S %p' if time_display_units.endswith("ampm") else '%d %B %Y\n%H:%M:%S'
            full_entity_df_plus_pos_copy["snapshot_time_display"] = full_entity_df_plus_pos_copy["snapshot_time"].apply(
                lambda x: dt.datetime.strftime(x, fmt)
            )
            full_entity_df_plus_pos_copy["snapshot_time"] = full_entity_df_plus_pos_copy["snapshot_time"].apply(
                lambda x: dt.datetime.strftime(x, fmt)
            )

        elif time_display_units in ("dhm", "dhm_ampm"):
            fmt = '%d %B %Y\n%I:%M %p' if time_display_units.endswith("ampm") else '%d %B %Y\n%H:%M'
            full_entity_df_plus_pos_copy["snapshot_time_display"] = full_entity_df_plus_pos_copy["snapshot_time"].apply(
                lambda x: dt.datetime.strftime(x, fmt)
            )
            full_entity_df_plus_pos_copy["snapshot_time"] = full_entity_df_plus_pos_copy["snapshot_time"].apply(
                lambda x: dt.datetime.strftime(x, fmt)
            )

        elif time_display_units in ("dh", "dh_ampm"):
            fmt = '%d %B %Y\n%I %p' if time_display_units.endswith("ampm") else '%d %B %Y\n%H'
            full_entity_df_plus_pos_copy["snapshot_time_display"] = full_entity_df_plus_pos_copy["snapshot_time"].apply(
                lambda x: dt.datetime.strftime(x, fmt)
            )
            full_entity_df_plus_pos_copy["snapshot_time"] = full_entity_df_plus_pos_copy["snapshot_time"].apply(
                lambda x: dt.datetime.strftime(x, fmt)
            )

        elif time_display_units in ("d"):
            full_entity_df_plus_pos_copy["snapshot_time_display"] = full_entity_df_plus_pos_copy["snapshot_time"].apply(
                lambda x: dt.datetime.strftime(x, '%A %d %B %Y')
                )
            full_entity_df_plus_pos_copy["snapshot_time"] = full_entity_df_plus_pos_copy["snapshot_time"].apply(
                lambda x: dt.datetime.strftime(x, '%Y-%m-%d')
                )

        elif time_display_units in ("m"):
            full_entity_df_plus_pos_copy["snapshot_time_display"] = full_entity_df_plus_pos_copy["snapshot_time"].apply(
                lambda x: dt.datetime.strftime(x, '%B %Y')
                )
            full_entity_df_plus_pos_copy["snapshot_time"] = full_entity_df_plus_pos_copy["snapshot_time"].apply(
                lambda x: dt.datetime.strftime(x, '%B %Y')
                )

        elif time_display_units in ("y"):
            full_entity_df_plus_pos_copy["snapshot_time_display"] = full_entity_df_plus_pos_copy["snapshot_time"].apply(
                lambda x: dt.datetime.strftime(x, '%Y')
                )
            full_entity_df_plus_pos_copy["snapshot_time"] = full_entity_df_plus_pos_copy["snapshot_time"].apply(
                lambda x: dt.datetime.strftime(x, '%Y')
                )
        elif time_display_units in ("day_clock", "simulation_day_clock", "day_clock_ampm", "simulation_day_clock_ampm"):
            use_ampm = time_display_units.endswith("_ampm")
            def format_day_clock(t):
                delta = t - pd.Timestamp(t.date())
                sim_day = (t.normalize() - full_entity_df_plus_pos_copy["snapshot_time"].min().normalize()).days + 1
                time_fmt = "%I:%M %p" if use_ampm else "%H:%M"
                return f"Simulation Day {sim_day}\n{t.strftime(time_fmt)}"

            full_entity_df_plus_pos_copy["snapshot_time_display"] = full_entity_df_plus_pos_copy["snapshot_time"].apply(
                lambda x: format_day_clock(pd.to_datetime(x))
            )
            full_entity_df_plus_pos_copy["snapshot_time"] = full_entity_df_plus_pos_copy["snapshot_time"].apply(
                lambda x: format_day_clock(pd.to_datetime(x))
            )
        else:
            try:
                full_entity_df_plus_pos_copy["snapshot_time_display"] = full_entity_df_plus_pos_copy["snapshot_time"].apply(
                    lambda x: dt.datetime.strftime(x, time_display_units)
                    )
                full_entity_df_plus_pos_copy["snapshot_time"] = full_entity_df_plus_pos_copy["snapshot_time"].apply(
                    lambda x: dt.datetime.strftime(x, time_display_units)
                    )
            except:
                raise "Invalid time_display_units option provided. Valid options are: dhms, dhm, dh, d, m, y. Alternatively, you can provide your own valid strftime format (e.g. '%Y-%m-%d %H'). See the strftime documentation for more details: https://strftime.org/"


    else:
        full_entity_df_plus_pos_copy["snapshot_time_display"] = full_entity_df_plus_pos_copy["snapshot_time"]

    # We are effectively making use of an animated plotly express scatterplot
    # to do all of the heavy lifting
    # Because of the way plots animate in this, it deals with all of the difficulty
    # of paths between individual positions - so we just have to tell it where to put
    # people at each defined step of the process, and the scattergraph will move them
    if scenario is not None:
        if pathway_col_name is not None:
            hovers = [entity_col_name, pathway_col_name, time_col_name, "snapshot_time", resource_col_name]
        else:
            hovers = [entity_col_name, time_col_name, "snapshot_time", resource_col_name]

    else:
        if pathway_col_name is not None:
            hovers = [entity_col_name, pathway_col_name, time_col_name, "snapshot_time"]
        else:
            hovers = [entity_col_name, time_col_name, "snapshot_time"]

    fig = px.scatter(
            full_entity_df_plus_pos_copy.sort_values("snapshot_time_base"),
            x="x_final",
            y="y_final",
            # Each frame is one step of time, with the gap being determined
            # in the reshape_for_animation function
            animation_frame="snapshot_time_display",
            # Important to group by patient here
            animation_group=entity_col_name,
            text="icon",
            hover_name=event_col_name,
            hover_data=hovers,
            range_x=[0, x_max],
            range_y=[0, y_max],
            height=plotly_height,
            width=plotly_width,
            # This sets the opacity of the points that sit behind
            opacity=0
            )


    # Update the size of the icons and labels
    # This is what determines the size of the individual emojis that
    # represent our people!
    # fig.data[0].textfont.size = entity_icon_size
    # Apply entity_icon_size to all traces that represent entities
    for trace in fig.data:
        if "marker" in trace:
            trace.textfont.size = entity_icon_size

    # Now add labels identifying each stage (optional - can either be used
    # in conjunction with a background image or as a way to see stage names
    # without the need to create a background image)
    if display_stage_labels:
        fig.add_trace(go.Scatter(
            x=[pos+10 for pos in event_position_df['x'].to_list()],
            y=event_position_df['y'].to_list(),
            mode="text",
            name="",
            text=event_position_df['label'].to_list(),
            textposition="middle right",
            hoverinfo='none'
        ))

        # Update the size of the icons and labels
        # This is what determines the size of the individual emojis that
        # represent our people!
        # Update the text size for the LAST ADDED trace (stage labels)
        fig.data[-1].textfont.size = text_size

    #############################################
    # Add in icons to indicate the available resources
    #############################################

    # Make an additional dataframe that has one row per resource type
    # Then, starting from the initial position, make that many large circles
    # make them semi-transparent or you won't see the people using them!
    if scenario is not None:
        events_with_resources = event_position_df[event_position_df['resource'].notnull()].copy()
        events_with_resources['resource_count'] = events_with_resources['resource'].apply(lambda x: getattr(scenario, x))

        events_with_resources = events_with_resources.join(events_with_resources.apply(
            lambda r: pd.Series({'x_final': [r['x']-(gap_between_resources*(i+1))
                                             for i in range(r['resource_count'])]}), axis=1).explode('x_final'),
            how='right')

        # events_with_resources = events_with_resources.assign(resource_id=range(len(events_with_resources)))
        # After exploding
        events_with_resources[resource_col_name] = events_with_resources.groupby([event_col_name]).cumcount()

        if wrap_resources_at is not None:
            events_with_resources['row'] = np.floor((events_with_resources[resource_col_name]) / (wrap_resources_at))

            events_with_resources['x_final'] = (
                events_with_resources['x_final']
                + (wrap_resources_at * events_with_resources['row'] * gap_between_resources)
                + gap_between_resources
                )

            events_with_resources['y_final'] = (
                events_with_resources['y']
                + (events_with_resources['row'] * gap_between_resource_rows)
                )
        else:
            events_with_resources['y_final'] = events_with_resources['y']

        # This just adds an additional scatter trace that creates large dots
        # that represent the individual resources
        #TODO: Add ability to pass in 'icon' column as part of the event_position_df that
        # can then be used to provide custom icons per resource instead of a single custom
        # icon for all resources
        if custom_resource_icon is not None:
            fig.add_trace(go.Scatter(
                x=events_with_resources['x_final'].to_list(),
                # Place these slightly below the y position for each entity
                # that will be using the resource
                y=[i-10 for i in events_with_resources['y_final'].to_list()],
                mode="markers+text",
                text=custom_resource_icon,
                # Make the actual marker invisible
                marker=dict(opacity=0),
                # Set opacity of the icon
                opacity=0.8,
                hoverinfo='none'
            ))
        else:
            fig.add_trace(go.Scatter(
                x=events_with_resources['x_final'].to_list(),
                # Place these slightly below the y position for each entity
                # that will be using the resource
                y=[i-10 for i in events_with_resources['y_final'].to_list()],
                mode="markers",
                # Define what the marker will look like
                marker=dict(
                    color='LightSkyBlue',
                    size=15),
                opacity=resource_opacity,
                hoverinfo='none'
            ))

        # Update the size of the icons and labels
        # This is what determines the size of the individual emojis that
        # represent our people!
        fig.data[-1].textfont.size = resource_icon_size
        # fig.data[-1].opacity = resource_opacity # Set opacity for the resource icon text


    #############################################
    # Optional step to add a background image
    #############################################

    # This can help to better visualise the layout/structure of a pathway
    # Simple FOSS tool for creating these background images is draw.io

    # Ideally your queueing steps should always be ABOVE your resource use steps
    # as this then results in people nicely flowing from the front of the queue
    # to the next stage

    if add_background_image is not None:
        fig.add_layout_image(
            dict(
                source=add_background_image,
                xref="x domain",
                yref="y domain",
                x=1,
                y=1,
                sizex=1,
                sizey=1,
                xanchor="right",
                yanchor="top",
                sizing="stretch",
                opacity=0.5,
                layer="below")
    )

    # We don't need any gridlines or tickmarks for the final output, so remove
    # However, can be useful for the initial setup phase of the outputs, so give
    # the option to inlcude
    if not setup_mode:
        fig.update_xaxes(showticklabels=False, showgrid=False, zeroline=False,
                         # Prevent zoom
                         fixedrange=True)
        fig.update_yaxes(showticklabels=False, showgrid=False, zeroline=False,
                         # Prevent zoom
                         fixedrange=True)

    fig.update_layout(yaxis_title=None, xaxis_title=None, showlegend=False,
                      # Increase the size of the play button and animation timeline
                      sliders=[dict(currentvalue=dict(font=dict(size=35) ,
                                    prefix=""))]
                                )

    # You can get rid of the play button if desired
    # Was more useful in older versions of the function
    if not include_play_button:
        fig["layout"].pop("updatemenus")

    # Adjust speed of animation
    try:
        fig.layout.updatemenus[0].buttons[0].args[1]['frame']['duration'] = frame_duration
    except IndexError:
        print("Error changing frame duration")

    try:
        fig.layout.updatemenus[0].buttons[0].args[1]['transition']['duration'] = frame_transition_duration
    except IndexError:
        print("Error changing frame transition duration")

    if debug_mode:
        print(f'Output animation generation complete at {time.strftime("%H:%M:%S", time.localtime())}')

    return fig

def animate_activity_log(
        event_log,
        event_position_df,
        scenario=None,
        time_col_name="time",
        entity_col_name="entity_id",
        event_type_col_name="event_type",
        event_col_name="event",
        pathway_col_name=None,
        resource_col_name="resource_id",
        simulation_time_unit="minutes",
        every_x_time_units=10,
        wrap_queues_at=20,
        wrap_resources_at=20,
        step_snapshot_max=50,
        limit_duration=10*60*24,
        plotly_height=900,
        plotly_width=None,
        include_play_button=True,
        add_background_image=None,
        display_stage_labels=True,
        entity_icon_size=24,
        text_size=24,
        resource_icon_size=24,
        gap_between_entities=10,
        gap_between_queue_rows=30,
        gap_between_resource_rows=30,
        gap_between_resources=10,
        resource_opacity=0.8,
        custom_resource_icon=None,
        override_x_max=None,
        override_y_max=None,
        start_date=None,
        start_time=None,
        time_display_units=None,
        setup_mode=False,
        frame_duration=400, #milliseconds
        frame_transition_duration=600, #milliseconds
        debug_mode=False,
        custom_entity_icon_list=None,
        debug_write_intermediate_objects=False
        ):
    """
    Generate an animated visualization of patient flow through a system.

    This function processes event log data, adds positional information, and creates
    an interactive Plotly animation representing patient movement through various stages.

    Parameters
    ----------
    event_log : pd.DataFrame
        The log of events to be animated, containing patient activities.
    event_position_df : pd.DataFrame
        DataFrame specifying the positions of different events, with columns 'event', 'x', and 'y'.
    scenario : object
        An object containing attributes for resource counts at different steps.
        time_col_name : str, default="time"
        Name of the column in `event_log` that contains the timestamp of each event.
        Timestamps should represent the number of time units since the simulation began.
    entity_col_name : str, default="entity_id"
        Name of the column in `event_log` that contains the unique identifier for each entity
        (e.g., "entity_id",  "entity", "patient", "patient_id", "customer", "ID").
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
    resource_col_name : str, default="resource_id"
        Name of the column for the resource identifier. Used for 'resource_use' events.
    simulation_time_unit: string, optional
        Time unit used within the simulation (default is minutes).
        Possible values are 'seconds', 'minutes', 'hours', 'days', 'weeks', 'years'
    every_x_time_units : int, optional
        Time interval between animation frames in minutes (default is 10).
    wrap_queues_at : int, optional
        Maximum number of entities to display in a queue before wrapping to a new row (default is 20).
    wrap_resources_at : int, optional
        Number of resources to show before wrapping to a new row (default is 20).
    step_snapshot_max : int, optional
        Maximum number of patients to show in each snapshot per event (default is 50).
    limit_duration : int, optional
        Maximum duration to animate in minutes (default is 10 days or 14400 minutes).
    plotly_height : int, optional
        Height of the Plotly figure in pixels (default is 900).
    plotly_width : int, optional
        Width of the Plotly figure in pixels (default is None, which auto-adjusts).
    include_play_button : bool, optional
        Whether to include a play button in the animation (default is True).
    add_background_image : str, optional
        Path to a background image file to add to the animation (default is None).
    display_stage_labels : bool, optional
        Whether to display labels for each stage (default is True).
    entity_icon_size : int, optional
        Size of entity icons in the animation (default is 24).
    text_size : int, optional
        Size of text labels in the animation (default is 24).
    resource_icon_size : int, optional
        Size of resource icons in the animation (default is 24).
    gap_between_entities : int, optional
        Horizontal spacing between entities in pixels (default is 10).
    gap_between_queue_rows : int, optional
        Vertical spacing between rows in pixels (default is 30).
    gap_between_resource_rows : int, optional
        Vertical spacing between rows in pixels (default is 30).
    gap_between_resources : int, optional
        Horizontal spacing between resources in pixels (default is 10).
    resource_opacity : float, optional
        Opacity of resource icons (default is 0.8).
    custom_resource_icon : str, optional
        Custom icon to use for resources (default is None).
    override_x_max : int, optional
        Override the maximum x-coordinate of the plot (default is None).
    override_y_max : int, optional
        Override the maximum y-coordinate of the plot (default is None).
    time_display_units : str, optional
        Format for displaying time on the animation timeline. This affects how simulation time is
        converted into human-readable dates or clock formats. If `None` (default), the raw simulation
        time is used.

        Predefined options:
        - 'dhms' : Day Month Year + HH:MM:SS (e.g., "06 June 2025\n14:23:45")
        - 'dhms_ampm' : Same as 'dhms', but in 12-hour format with AM/PM (e.g., "06 June 2025\n02:23:45 PM")
        - 'dhm'  : Day Month Year + HH:MM (e.g., "06 June 2025\n14:23")
        - 'dhm_ampm' : 12-hour format with AM/PM (e.g., "06 June 2025\n02:23 PM")
        - 'dh'   : Day Month Year + HH (e.g., "06 June 2025\n14")
        - 'dh_ampm' : 12-hour format with AM/PM (e.g., "06 June 2025\n02 PM")
        - 'd'    : Full weekday and date (e.g., "Friday 06 June 2025")
        - 'm'    : Month and year (e.g., "June 2025")
        - 'y'    : Year only (e.g., "2025")
        - 'day_clock' or 'simulation_day_clock':
            Show simulation-relative day and time (e.g., "Simulation Day 3\n14:15")
        - 'day_clock_ampm' or 'simulation_day_clock_ampm':
            Same as above, but time is shown in 12-hour clock with AM/PM (e.g., "Simulation Day 3\n02:15 PM")

        Alternatively, you can supply a custom [strftime](https://strftime.org/) format string
        (e.g., '%Y-%m-%d %H') to control the display manually.
    setup_mode : bool, optional
        If True, display grid and tick marks for initial setup (default is False).
    frame_duration : int, optional
        Duration of each frame in milliseconds (default is 400).
    frame_transition_duration : int, optional
        Duration of transition between frames in milliseconds (default is 600).
    debug_mode : bool, optional
        If True, print debug information during processing (default is False).
    custom_entity_icon_list: list, optional
        If given, overrides the default list of emojis used to represent entities

    Returns
    -------
    plotly.graph_objs._figure.Figure
        An animated Plotly figure object representing the patient flow.

    Notes
    -----
    - This function uses helper functions: reshape_for_animations, generate_animation_df, and generate_animation.
    - The animation supports customization of icon sizes, resource representation, and animation speed.
    - Time can be displayed as actual dates or as model time units.
    - A background image can be added to provide context for the patient flow.
    - The function handles both queuing and resource use events.

    Examples
    --------
    >>> animation = animate_activity_log(event_log, event_positions, scenario,
    ...                                  time_display_units='dhm',
    ...                                  add_background_image='path/to/image.png')
    >>> animation.show()
    """
    if debug_mode:
        start_time_function = time.perf_counter()
        print(f'Animation function called at {time.strftime("%H:%M:%S", time.localtime())}')

    full_entity_df = reshape_for_animations(
        event_log,
        every_x_time_units=every_x_time_units,
        limit_duration=limit_duration,
        step_snapshot_max=step_snapshot_max,
        debug_mode=debug_mode,
        time_col_name=time_col_name,
        entity_col_name=entity_col_name,
        event_type_col_name=event_type_col_name,
        event_col_name=event_col_name,
        pathway_col_name=pathway_col_name
        )

    if debug_write_intermediate_objects:
        full_entity_df.to_csv("output_reshape_for_animations.csv")

    if debug_mode:
        print(f'Reshaped animation dataframe finished construction at {time.strftime("%H:%M:%S", time.localtime())}')

    full_entity_df_plus_pos = generate_animation_df(
                                full_entity_df=full_entity_df,
                                event_position_df=event_position_df,
                                wrap_queues_at=wrap_queues_at,
                                wrap_resources_at=wrap_resources_at,
                                step_snapshot_max=step_snapshot_max,
                                gap_between_entities=gap_between_entities,
                                gap_between_resources=gap_between_resources,
                                gap_between_resource_rows=gap_between_resource_rows,
                                gap_between_queue_rows=gap_between_queue_rows,
                                debug_mode=debug_mode,
                                custom_entity_icon_list=custom_entity_icon_list,
                                time_col_name=time_col_name,
                                entity_col_name=entity_col_name,
                                event_type_col_name=event_type_col_name,
                                event_col_name=event_col_name,
                                resource_col_name=resource_col_name
                                )

    if debug_write_intermediate_objects:
        full_entity_df_plus_pos.to_csv("output_generate_animation_df.csv")

    animation = generate_animation(
        full_entity_df_plus_pos=full_entity_df_plus_pos,
        event_position_df=event_position_df,
        scenario=scenario,
        simulation_time_unit=simulation_time_unit,
        plotly_height=plotly_height,
        plotly_width=plotly_width,
        include_play_button=include_play_button,
        add_background_image=add_background_image,
        display_stage_labels=display_stage_labels,
        entity_icon_size=entity_icon_size,
        resource_icon_size=resource_icon_size,
        text_size=text_size,
        gap_between_resource_rows=gap_between_resource_rows,
        override_x_max=override_x_max,
        override_y_max=override_y_max,
        start_date=start_date,
        start_time=start_time,
        time_display_units=time_display_units,
        setup_mode=setup_mode,
        resource_opacity=resource_opacity,
        wrap_resources_at=wrap_resources_at,
        gap_between_resources=gap_between_resources,
        custom_resource_icon=custom_resource_icon,
        frame_duration=frame_duration, #milliseconds
        frame_transition_duration=frame_transition_duration, #milliseconds
        debug_mode=debug_mode,
        time_col_name=time_col_name,
        entity_col_name=entity_col_name,
        event_col_name=event_col_name,
        pathway_col_name=pathway_col_name,
        resource_col_name=resource_col_name
    )

    if debug_mode:
        end_time_function = time.perf_counter()
        print(f'Total Time Elapsed: {(end_time_function - start_time_function):.2f} seconds')

    return animation

def add_repeating_overlay(
    fig: go.Figure,
    overlay_text: str,
    first_start_frame: int,
    on_duration_frames: float,
    off_duration_frames: float,
    rect_color: str = 'grey',
    rect_opacity: float = 0.5,
    text_size: int = 40,
    text_font_color: str = 'white',
    relative_text_position_x: int = 0.5,
    relative_text_position_y: int = 0.5
) -> go.Figure:
    """
    Add a repeating overlay (rectangle and text) to an animated Plotly figure using traces.

    This function adds overlay elements as additional traces rather than layout shapes/annotations,
    which enables the overlay to work without requiring redraw=True during animation. The overlay
    follows a repeating on/off pattern starting from a specified frame.

    Parameters
    ----------
    fig : plotly.graph_objects.Figure
        The animated Plotly figure object to modify.
    overlay_text : str
        The text to display in the overlay.
    first_start_frame : int
        The frame index where the overlay first appears. Must be >= 0.
    on_duration_frames : float
        The number of frames the overlay remains visible. Will be converted to int.
    off_duration_frames : float
        The number of frames the overlay is hidden between appearances. Will be converted to int.
    rect_color : str, default 'grey'
        The background color of the overlay rectangle. Accepts any valid CSS color string
        (e.g., 'red', '#FF0000', 'rgba(255,0,0,0.5)').
    rect_opacity : float, default 0.5
        The opacity of the overlay rectangle. Must be between 0 (transparent) and 1 (opaque).
    text_size : int, default 40
        The font size of the overlay text in points.
    text_font_color : str, default 'white'
        The color of the overlay text. Accepts any valid CSS color string.
    relative_text_position_x : float, default 0.5
        The horizontal position of the text within the overlay rectangle.
        0.0 = left edge, 0.5 = center, 1.0 = right edge.
    relative_text_position_y : float, default 0.5
        The vertical position of the text within the overlay rectangle.
        0.0 = bottom edge, 0.5 = center, 1.0 = top edge.

    Returns
    -------
    plotly.graph_objects.Figure
        The modified Plotly figure object with the repeating overlay added as traces.
        The original figure is modified in-place and also returned.

    Notes
    -----
    - The overlay uses secondary axes (x2, y2) to position elements in paper coordinates
      (0 to 1 range) independent of the main plot's data coordinates.
    - The overlay pattern repeats with a cycle length of (on_duration_frames + off_duration_frames).
    - Frame indexing is 0-based, so first_start_frame=0 means the overlay starts from the first frame.
    - The condition `i > start_frame` ensures the overlay doesn't appear on the initial frame
      unless explicitly specified.
    - This implementation works without requiring redraw=True in animation configurations,
      making it more efficient for complex animated plots.
   - returns UserWarning
        If the figure has no frames, a warning is printed and the figure is returned unchanged.
    - returns UserWarning
        If the sum of on_duration_frames and off_duration_frames is not positive,
        a warning is printed and the figure is returned unchanged.

    Examples
    --------
    Add a warning overlay that appears every 10 frames for 3 frames duration:

    >>> fig = create_animated_figure()  # Your animated figure
    >>> fig = add_repeating_overlay_as_traces(
    ...     fig=fig,
    ...     overlay_text="WARNING",
    ...     first_start_frame=5,
    ...     on_duration_frames=3,
    ...     off_duration_frames=7,
    ...     rect_color='red',
    ...     rect_opacity=0.7,
    ...     text_size=50,
    ...     text_font_color='white'
    ... )

    Add a subtle notification with custom text positioning:

    >>> fig = add_repeating_overlay_as_traces(
    ...     fig=fig,
    ...     overlay_text="Processing...",
    ...     first_start_frame=10,
    ...     on_duration_frames=2.5,
    ...     off_duration_frames=5.0,
    ...     rect_color='rgba(0,0,0,0.3)',
    ...     relative_text_position_x=0.8,
    ...     relative_text_position_y=0.2
    ... )
    """
    on_frames = int(on_duration_frames)
    off_frames = int(off_duration_frames)
    start_frame = int(first_start_frame)

    num_frames = len(fig.frames)
    if num_frames == 0:
        print("⚠️ Warning: Figure has no frames. Overlay will not be animated.")
        return fig

    cycle_length = on_frames + off_frames
    if cycle_length <= 0:
        print("⚠️ Warning: Sum of on/off duration is not positive. Cannot create pattern.")
        return fig


    # Create visibility pattern for each frame
    overlay_visibility = []
    for i in range(num_frames):
        is_on = False
        if i > start_frame:
            cycle_pos = (i - start_frame) % cycle_length
            if cycle_pos < on_frames:
                is_on = True
        overlay_visibility.append(is_on)

    # Determine what frame 0 should show
    frame_0_visible = overlay_visibility[0] if overlay_visibility else False

    # Add rectangle trace - match frame 0 visibility
    if frame_0_visible:
        rect_x = [0, 1, 1, 0, 0]
        rect_y = [0, 0, 1, 1, 0]
    else:
        rect_x = []
        rect_y = []

    fig.add_trace(go.Scatter(
        x=rect_x,
        y=rect_y,
        mode='lines',
        fill='toself',
        fillcolor=rect_color,
        opacity=rect_opacity,
        line=dict(width=0),
        xaxis='x2',  # Use secondary axis for paper coordinates
        yaxis='y2',
        showlegend=False,
        hoverinfo='skip',
        name='overlay_rect'
    ))

    # Add text trace - match frame 0 visibility
    if frame_0_visible:
        text_x = [relative_text_position_x]
        text_y = [relative_text_position_y]
        text_content = [overlay_text]
    else:
        text_x = []
        text_y = []
        text_content = []

    fig.add_trace(go.Scatter(
        x=text_x,
        y=text_y,
        mode='text',
        text=text_content,
        textfont=dict(size=text_size, color=text_font_color),
        xaxis='x2',
        yaxis='y2',
        showlegend=False,
        hoverinfo='skip',
        name='overlay_text'
    ))

    # Configure secondary axes to match paper coordinates
    fig.update_layout(
        xaxis2=dict(
            overlaying='x',
            range=[0, 1],
            showgrid=False,
            showticklabels=False,
            zeroline=False
        ),
        yaxis2=dict(
            overlaying='y',
            range=[0, 1],
            showgrid=False,
            showticklabels=False,
            zeroline=False
        )
    )

    # Update frame data to include overlay traces
    rect_trace_idx = len(fig.data) - 2  # Rectangle trace index
    text_trace_idx = len(fig.data) - 1  # Text trace index

    for i, frame in enumerate(fig.frames):
        # Add overlay trace data to each frame
        if overlay_visibility[i]:
            # Overlay should be visible
            rect_data = go.Scatter(
                x=[0, 1, 1, 0, 0],
                y=[0, 0, 1, 1, 0],
                mode='lines',
                fill='toself',
                fillcolor=rect_color,
                opacity=rect_opacity,
                line=dict(width=0),
                xaxis='x2',
                yaxis='y2'
            )
            text_data = go.Scatter(
                x=[relative_text_position_x],
                y=[relative_text_position_y],
                mode='text',
                text=[overlay_text],
                textfont=dict(size=text_size, color=text_font_color),
                xaxis='x2',
                yaxis='y2'
            )
        else:
            # Overlay should be hidden (empty data)
            rect_data = go.Scatter(x=[], y=[], xaxis='x2', yaxis='y2')
            text_data = go.Scatter(x=[], y=[], mode='text', xaxis='x2', yaxis='y2')

        # Extend frame data to include overlay traces
        frame_data = list(frame.data) if frame.data else []

        # Ensure we have the right number of traces
        while len(frame_data) <= text_trace_idx:
            frame_data.append(go.Scatter(x=[], y=[]))

        # Update overlay traces
        frame_data[rect_trace_idx] = rect_data
        frame_data[text_trace_idx] = text_data

        # Update frame
        frame.data = frame_data

    if rect_opacity > 0:
        for updatemenu in fig.layout.updatemenus:
            if 'buttons' in updatemenu and updatemenu['type'] == 'buttons':
                for button in updatemenu['buttons']:
                    if 'args' in button and len(button['args']) > 1:
                        # args is [None, {frame: {...}, ...}]
                        # Set redraw=True in the frame dict
                        if 'frame' in button['args'][1]:
                            button['args'][1]['frame']['redraw'] = True

        for slider in fig.layout.sliders:
            for step in slider['steps']:
                if 'args' in step and len(step['args']) > 1:
                    # args is [ [frame_name], {frame: {...}, ...} ]
                    # Set redraw=True in the frame dict
                    if 'frame' in step['args'][1]:
                        step['args'][1]['frame']['redraw'] = True

    return fig
