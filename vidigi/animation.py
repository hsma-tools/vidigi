import datetime as dt
import time
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from vidigi.prep import reshape_for_animations, generate_animation_df
import numpy as np

def generate_animation(
        full_entity_df_plus_pos,
        event_position_df,
        scenario=None,
        time_col_name="time",
        entity_col_name="patient",
        event_col_name="event",
        pathway_col_name=None,
        simulation_time_unit="minutes",
        plotly_height=900,
        plotly_width=None,
        include_play_button=True,
        add_background_image=None,
        display_stage_labels=True,
        icon_and_text_size=24,
        override_x_max=None,
        override_y_max=None,
        time_display_units=None,
        start_date=None,
        start_time=None,
        resource_opacity=0.8,
        custom_resource_icon=None,
        wrap_resources_at=20,
        gap_between_resources=10,
        gap_between_rows=30,
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
    icon_and_text_size : int, optional
        Size of icons and text in the animation (default is 24).
    override_x_max : int, optional
        Override the maximum x-coordinate (default is None).
    override_y_max : int, optional
        Override the maximum y-coordinate (default is None).
    time_display_units : str, optional
        Units for displaying time. Options are 'dhm' (days, hours, minutes), 'd' (days), or None (default).
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
    gap_between_rows : int, optional
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

    Examples
    --------
    >>> animation = generate_animation(patient_df, event_positions, scenario,
    ...                                time_display_units='dhm',
    ...                                add_background_image='path/to/image.png')
    >>> animation.show()
    """
    if override_x_max is not None:
        x_max = override_x_max
    else:
        x_max = event_position_df['x'].max()*1.25

    if override_y_max is not None:
        y_max = override_y_max
    else:
        y_max = event_position_df['y'].max()*1.1

    # If we're displaying time as a clock instead of as units of whatever time our model
    # is working in, create a minute_display column that will display as a psuedo datetime

    # For now, it starts a few months after the current date, just to give the
    # idea of simulating some hypothetical future time. It might be nice to allow
    # the start point to be changed, particular if we're simulating something on
    # a larger timescale that includes a level of weekly or monthly seasonality.

    # We need to keep the original minute column in existance because it's important for sorting
    if time_display_units == "dhm":
        if start_date is None:
            full_entity_df_plus_pos["snapshot_time"] = (
                dt.date.today() +
                pd.DateOffset(days=165) +
                pd.TimedeltaIndex(full_entity_df_plus_pos["snapshot_time"], unit='m')
                )
        else:
            if start_time is None:
                full_entity_df_plus_pos["snapshot_time"] = (
                    dt.datetime.strptime(start_date, "%Y-%m-%d") +
                    pd.TimedeltaIndex(full_entity_df_plus_pos["snapshot_time"], unit='m')
                    )
            else:
                start_time_dt = dt.datetime.strptime(start_time, "%H:%M:%S")

                start_time_time_delta = dt.timedelta(
                        hours=start_time_dt.hour,
                        minutes=start_time_dt.minute,
                        seconds=start_time_dt.second
                    )

                full_entity_df_plus_pos["snapshot_time"] = (
                    dt.datetime.strptime(start_date, "%Y-%m-%d") +
                    start_time_time_delta +
                    pd.TimedeltaIndex(full_entity_df_plus_pos["snapshot_time"], unit='m')
                    )

        # https://strftime.org/
        full_entity_df_plus_pos["snapshot_time_display"] = full_entity_df_plus_pos["snapshot_time"].apply(
            lambda x: dt.datetime.strftime(x, '%d %B %Y\n%H:%M')
            )
        full_entity_df_plus_pos["snapshot_time"] = full_entity_df_plus_pos["snapshot_time"].apply(
            lambda x: dt.datetime.strftime(x, '%Y-%m-%d %H:%M')
            )
    if time_display_units == "d":
        if start_date is None:
            full_entity_df_plus_pos["snapshot_time"] = (
                dt.date.today() + pd.DateOffset(days=165) +
                pd.TimedeltaIndex(full_entity_df_plus_pos["snapshot_time"], unit='d')
                )
        else:
            full_entity_df_plus_pos["snapshot_time"] = (
                dt.datetime.strptime(start_date, "%Y-%m-%d") +
                pd.TimedeltaIndex(full_entity_df_plus_pos["snapshot_time"], unit='d')
                )

        full_entity_df_plus_pos["snapshot_time_display"] = full_entity_df_plus_pos["snapshot_time"].apply(
            lambda x: dt.datetime.strftime(x, '%A %d %B %Y')
            )
        full_entity_df_plus_pos["snapshot_time"] = full_entity_df_plus_pos["snapshot_time"].apply(
            lambda x: dt.datetime.strftime(x, '%Y-%m-%d')
            )
    else:
        full_entity_df_plus_pos["snapshot_time_display"] = full_entity_df_plus_pos["snapshot_time"]

    # We are effectively making use of an animated plotly express scatterploy
    # to do all of the heavy lifting
    # Because of the way plots animate in this, it deals with all of the difficulty
    # of paths between individual positions - so we just have to tell it where to put
    # people at each defined step of the process, and the scattergraph will move them
    if scenario is not None:
        if pathway_col_name is not None:
            hovers = [entity_col_name, pathway_col_name, time_col_name, "snapshot_time", "resource_id"]
        else:
            hovers = [entity_col_name, time_col_name, "snapshot_time", "resource_id"]

    else:
        if pathway_col_name is not None:
            hovers = [entity_col_name, pathway_col_name, time_col_name, "snapshot_time"]
        else:
            hovers = [entity_col_name, time_col_name, "snapshot_time"]

    fig = px.scatter(
            full_entity_df_plus_pos.sort_values("snapshot_time"),
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
    fig.update_traces(textfont_size=icon_and_text_size)

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

        events_with_resources = events_with_resources.assign(resource_id=range(len(events_with_resources)))

        if wrap_resources_at is not None:
            events_with_resources['row'] = np.floor((events_with_resources['resource_id']) / (wrap_resources_at))
            events_with_resources['x_final'] = (
                events_with_resources['x_final']
                + (wrap_resources_at * events_with_resources['row'] * gap_between_resources)
                + gap_between_resources
                )
            events_with_resources['y_final'] = (
                events_with_resources['y']
                + (events_with_resources['row'] * gap_between_rows)
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
    fig.layout.updatemenus[0].buttons[0].args[1]['frame']['duration'] = frame_duration
    fig.layout.updatemenus[0].buttons[0].args[1]['transition']['duration'] = frame_transition_duration
    if debug_mode:
        print(f'Output animation generation complete at {time.strftime("%H:%M:%S", time.localtime())}')

    return fig

def animate_activity_log(
        event_log,
        event_position_df,
        scenario=None,
        time_col_name="time",
        entity_col_name="patient",
        event_type_col_name="event_type",
        event_col_name="event",
        pathway_col_name=None,
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
        icon_and_text_size=24,
        gap_between_entities=10,
        gap_between_rows=30,
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
        custom_entity_icon_list=None
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
    icon_and_text_size : int, optional
        Size of icons and text in the animation (default is 24).
    gap_between_entities : int, optional
        Horizontal spacing between entities in pixels (default is 10).
    gap_between_rows : int, optional
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
        Units for displaying time. Options are 'dhm' (days, hours, minutes), 'd' (days), or None (default).
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
                                gap_between_rows=gap_between_rows,
                                debug_mode=debug_mode,
                                custom_entity_icon_list=custom_entity_icon_list,
                                time_col_name=time_col_name,
                                entity_col_name=entity_col_name,
                                event_type_col_name=event_type_col_name,
                                event_col_name=event_col_name                        )

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
        icon_and_text_size=icon_and_text_size,
        override_x_max=override_x_max,
        override_y_max=override_y_max,
        start_date=start_date,
        start_time=start_time,
        time_display_units=time_display_units,
        setup_mode=setup_mode,
        resource_opacity=resource_opacity,
        wrap_resources_at=wrap_resources_at,
        gap_between_resources=gap_between_resources,
        gap_between_rows=gap_between_rows,
        custom_resource_icon=custom_resource_icon,
        frame_duration=frame_duration, #milliseconds
        frame_transition_duration=frame_transition_duration, #milliseconds
        debug_mode=debug_mode,
        time_col_name=time_col_name,
        entity_col_name=entity_col_name,
        event_col_name=event_col_name,
        pathway_col_name=pathway_col_name
    )

    if debug_mode:
        end_time_function = time.perf_counter()
        print(f'Total Time Elapsed: {(end_time_function - start_time_function):.2f} seconds')

    return animation
