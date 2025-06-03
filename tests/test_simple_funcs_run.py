from sample_models._simple_fifo_with_logging_storewrapper import Trial, g
from vidigi.prep import reshape_for_animations, generate_animation_df
from vidigi.animation import generate_animation, animate_activity_log
import pandas as pd
import plotly.io as pio
pio.renderers.default = "notebook"
import os
import pytest

my_trial = Trial()
my_trial.run_trial()

event_position_df = pd.DataFrame([
                    {'event': 'arrival',
                     'x':  50, 'y': 300,
                     'label': "Arrival" },

                    # Triage - minor and trauma
                    {'event': 'treatment_wait_begins',
                     'x':  205, 'y': 275,
                     'label': "Waiting for Treatment"},

                    {'event': 'treatment_begins',
                     'x':  205, 'y': 175,
                     'resource':'n_cubicles',
                     'label': "Being Treated"},

                    {'event': 'exit',
                     'x':  270, 'y': 70,
                     'label': "Exit"}

                ])

LIMIT_DURATION = g.sim_duration

def test_prep_RESHAPE_FOR_ANIMATIONS():
    try:
        full_entity_df = reshape_for_animations(
            event_log=my_trial.all_event_logs[my_trial.all_event_logs['run']==1],
            limit_duration=LIMIT_DURATION,
            debug_mode=True
            )

        full_entity_df.to_csv("tests/outputs/simple_funcs_run/TEST_prep_RESHAPE_FOR_ANIMATIONS.csv",
                               index=False)
    except:
        pytest.fail("prep.reshape_for_animations() function failed to run with default params")

def test_prep_GENERATE_ANIMATION_DF():
    try:
        full_entity_df = reshape_for_animations(
            event_log=my_trial.all_event_logs[my_trial.all_event_logs['run']==1],
            limit_duration=LIMIT_DURATION,
            debug_mode=True
            )

        full_entity_df_plus_pos = generate_animation_df(
            full_entity_df=full_entity_df,
            event_position_df=event_position_df,
            debug_mode=True
            )

        full_entity_df_plus_pos.to_csv("tests/outputs/simple_funcs_run/TEST_prep_GENERATE_ANIMATION_DF.csv",
                               index=False)

    except:
        pytest.fail("prep.generate_animation_df() function failed to run with default params")


def test_prep_GENERATE_ANIMATION():
    try:
        full_entity_df = reshape_for_animations(
            event_log=my_trial.all_event_logs[my_trial.all_event_logs['run']==1],
            limit_duration=LIMIT_DURATION,
            debug_mode=True
            )

        full_entity_df_plus_pos = generate_animation_df(
            full_entity_df=full_entity_df,
            event_position_df=event_position_df,
            debug_mode=True
            )

        fig = generate_animation(
                full_entity_df_plus_pos=full_entity_df_plus_pos,
                event_position_df=event_position_df,
                scenario=g(),
                debug_mode=True,
            )

        fig.write_html("tests/outputs/simple_funcs_run/TEST_prep_GENERATE_ANIMATION.html")

    except:
        pytest.fail("animation.animate_activity_log() function failed to run with default params")


def test_all_in_one_ANIMATE_ACTIVITY_LOG():
    try:
        animate_activity_log(
            event_log=my_trial.all_event_logs[my_trial.all_event_logs['run']==1],
            event_position_df= event_position_df,
            scenario=g(),
            limit_duration=g.sim_duration
        )
    except:
        pytest.fail("animation.animate_activity_log() function failed to run with default params")
