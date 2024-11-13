import datetime as dt
import time
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from vidigi.prep import reshape_for_animations, generate_animation_df

def generate_animation(
        full_patient_df_plus_pos,
        event_position_df,
        scenario=None,
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
        resource_opacity=0.8,
        custom_resource_icon=None,
        gap_between_resources=10,
        setup_mode=False,
        frame_duration=400, #milliseconds
        frame_transition_duration=600, #milliseconds
        debug_mode=False
):
    if override_x_max is not None:
        x_max = override_x_max
    else:
        x_max = event_position_df['x'].max()*1.25

    if override_y_max is not None:
        y_max = override_x_max
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
        full_patient_df_plus_pos['minute'] = dt.date.today() + pd.DateOffset(days=165) +  pd.TimedeltaIndex(full_patient_df_plus_pos['minute'], unit='m')
        # https://strftime.org/
        full_patient_df_plus_pos['minute_display'] = full_patient_df_plus_pos['minute'].apply(
            lambda x: dt.datetime.strftime(x, '%d %B %Y\n%H:%M')
            )
        full_patient_df_plus_pos['minute'] = full_patient_df_plus_pos['minute'].apply(
            lambda x: dt.datetime.strftime(x, '%Y-%m-%d %H:%M')
            )
    if time_display_units == "d":
        if start_date is None:
            full_patient_df_plus_pos['minute'] = dt.date.today() + pd.DateOffset(days=165) +  pd.TimedeltaIndex(full_patient_df_plus_pos['minute'], unit='d')
        else:
            full_patient_df_plus_pos['minute'] = dt.datetime.strptime(start_date, "%Y-%m-%d") +  pd.TimedeltaIndex(full_patient_df_plus_pos['minute'], unit='d')

        full_patient_df_plus_pos['minute_display'] = full_patient_df_plus_pos['minute'].apply(
            lambda x: dt.datetime.strftime(x, '%A %d %B %Y')
            )
        full_patient_df_plus_pos['minute'] = full_patient_df_plus_pos['minute'].apply(
            lambda x: dt.datetime.strftime(x, '%Y-%m-%d')
            )
    else:
        full_patient_df_plus_pos['minute_display'] = full_patient_df_plus_pos['minute']

    # We are effectively making use of an animated plotly express scatterploy
    # to do all of the heavy lifting
    # Because of the way plots animate in this, it deals with all of the difficulty
    # of paths between individual positions - so we just have to tell it where to put
    # people at each defined step of the process, and the scattergraph will move them
    if scenario is not None:
        hovers = ["patient", "pathway", "time", "minute", "resource_id"]
    else:
        hovers = ["patient", "pathway", "time", "minute"]

    fig = px.scatter(
            full_patient_df_plus_pos.sort_values('minute'),
            x="x_final",
            y="y_final",
            # Each frame is one step of time, with the gap being determined
            # in the reshape_for_animation function
            animation_frame="minute_display",
            # Important to group by patient here
            animation_group="patient",
            text="icon",
            hover_name="event",
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
            lambda r: pd.Series({'x_final': [r['x']-(gap_between_resources*(i+1)) for i in range(r['resource_count'])]}), axis=1).explode('x_final'),
            how='right')

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
                y=[i-10 for i in events_with_resources['y'].to_list()],
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
                y=[i-10 for i in events_with_resources['y'].to_list()],
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
        scenario,
        every_x_time_units=10,
        wrap_queues_at=20,
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
        time_display_units=None,
        setup_mode=False,
        frame_duration=400, #milliseconds
        frame_transition_duration=600, #milliseconds
        debug_mode=False
        ):

    if debug_mode:
        start_time_function = time.perf_counter()
        print(f'Animation function called at {time.strftime("%H:%M:%S", time.localtime())}')

    full_patient_df = reshape_for_animations(event_log,
                                             every_x_time_units=every_x_time_units,
                                             limit_duration=limit_duration,
                                             step_snapshot_max=step_snapshot_max,
                                             debug_mode=debug_mode)

    if debug_mode:
        print(f'Reshaped animation dataframe finished construction at {time.strftime("%H:%M:%S", time.localtime())}')



    full_patient_df_plus_pos = generate_animation_df(
                                full_patient_df=full_patient_df,
                                event_position_df=event_position_df,
                                wrap_queues_at=wrap_queues_at,
                                step_snapshot_max=step_snapshot_max,
                                gap_between_entities=gap_between_entities,
                                gap_between_resources=gap_between_resources,
                                gap_between_rows=gap_between_rows,
                                debug_mode=debug_mode
                        )

    animation = generate_animation(
        full_patient_df_plus_pos=full_patient_df_plus_pos,
        event_position_df=event_position_df,
        scenario=scenario,
        plotly_height=plotly_height,
        plotly_width=plotly_width,
        include_play_button=include_play_button,
        add_background_image=add_background_image,
        display_stage_labels=display_stage_labels,
        icon_and_text_size=icon_and_text_size,
        override_x_max=override_x_max,
        override_y_max=override_y_max,
        time_display_units=time_display_units,
        setup_mode=setup_mode,
        resource_opacity=resource_opacity,
        custom_resource_icon=custom_resource_icon,
        frame_duration=frame_duration, #milliseconds
        frame_transition_duration=frame_transition_duration, #milliseconds
        debug_mode=debug_mode
    )

    if debug_mode:
        end_time_function = time.perf_counter()
        print(f'Total Time Elapsed: {(end_time_function - start_time_function):.2f} seconds')

    return animation
