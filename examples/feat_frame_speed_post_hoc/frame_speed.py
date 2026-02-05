import streamlit as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from examples.example_2_branching_multistep.ex_2_model_classes import g, Trial
from vidigi.utils import EventPosition, create_event_position_df
from vidigi.animation import animate_activity_log

st.set_page_config(layout="wide")

with st.sidebar:
    st.write("""
This app aims to demonstrate that you can change the frame duration and frame transition
duration in a vidigi app without having to rerun the whole animation.

This is achieved by creating the animation in the main flow of the streamlit app, then
setting up the sliders in a fragment. The values from the sliders are used to modify attributes
of the fig object directly. These chaanges are immediately reflected without the animation
function needing to be rerun, making this a quick post-hoc change that can improve the user experience.

One unfortunate limitation is that the playback position will always be reset after a change is made
to the animation speed; at the present time (Feb 2026), this does not appear to be something that can be
overcome.
""")

event_position_df = create_event_position_df(
    [
        EventPosition(event="arrival", x=10, y=250, label="Arrival"),
        # Triage - minor and trauma
        EventPosition(
            event="triage_wait_begins", x=160, y=375, label="Waiting for<br>Triage"
        ),
        EventPosition(
            event="triage_begins",
            x=160,
            y=315,
            resource="n_triage",
            label="Being Triaged",
        ),
        # Minors (non-trauma) pathway
        EventPosition(
            event="MINORS_registration_wait_begins",
            x=300,
            y=145,
            label="Waiting for<br>Registration",
        ),
        EventPosition(
            event="MINORS_registration_begins",
            x=300,
            y=85,
            resource="n_reg",
            label="Being<br>Registered",
        ),
        EventPosition(
            event="MINORS_examination_wait_begins",
            x=465,
            y=145,
            label="Waiting for<br>Examination",
        ),
        EventPosition(
            event="MINORS_examination_begins",
            x=465,
            y=85,
            resource="n_exam",
            label="Being<br>Examined",
        ),
        EventPosition(
            event="MINORS_treatment_wait_begins",
            x=630,
            y=145,
            label="Waiting for<br>Treatment",
        ),
        EventPosition(
            event="MINORS_treatment_begins",
            x=630,
            y=85,
            resource="n_cubicles_non_trauma_treat",
            label="Being<br>Treated",
        ),
        # Trauma pathway
        EventPosition(
            event="TRAUMA_stabilisation_wait_begins",
            x=300,
            y=560,
            label="Waiting for<br>Stabilisation",
        ),
        EventPosition(
            event="TRAUMA_stabilisation_begins",
            x=300,
            y=490,
            resource="n_trauma",
            label="Being<br>Stabilised",
        ),
        EventPosition(
            event="TRAUMA_treatment_wait_begins",
            x=630,
            y=560,
            label="Waiting for<br>Treatment",
        ),
        EventPosition(
            event="TRAUMA_treatment_begins",
            x=630,
            y=490,
            resource="n_cubicles_trauma_treat",
            label="Being<br>Treated",
        ),
        EventPosition(event="depart", x=670, y=330, label="Exit"),
    ]
)


run_button = st.button("Press to run simulation")

if run_button:
    g.arrival_df = "examples/feaat_frame_speed_post_hoc/ed_arrivals_more_frequent.csv"
    my_trial = Trial()

    my_trial.run_trial()

    fig = animate_activity_log(
        event_log=my_trial.all_event_logs[my_trial.all_event_logs["run"] == 1],
        event_position_df=event_position_df,
        scenario=g(),
        entity_col_name="patient",
        debug_mode=False,
        setup_mode=False,
        every_x_time_units=5,
        include_play_button=True,
        gap_between_entities=11,
        gap_between_resources=15,
        gap_between_resource_rows=30,
        gap_between_queue_rows=30,
        plotly_height=600,
        plotly_width=900,
        override_x_max=700,
        override_y_max=675,
        entity_icon_size=10,
        resource_icon_size=13,
        text_size=15,
        wrap_queues_at=10,
        step_snapshot_max=20,
        limit_duration=g.sim_duration,
        time_display_units="dhm",
        display_stage_labels=False,
        add_background_image="https://raw.githubusercontent.com/Bergam0t/vidigi/refs/heads/main/examples/example_2_branching_multistep/Full%20Model%20Background%20Image%20-%20Horizontal%20Layout.drawio.png",
    )

    @st.fragment
    def change_animation_speed_and_duration():
        col1, col2 = st.columns(2)
        frame_duration = col1.slider("Set frame duration (ms)", 100, 2000, 800)
        frame_transition_duration = col2.slider(
            "Set frame transition duration (ms)", 100, 2000, 800
        )

        try:
            fig.layout.updatemenus[0].buttons[0].args[1]["frame"]["duration"] = (
                frame_duration
            )
        except IndexError:
            print("Error changing frame duration")

        try:
            fig.layout.updatemenus[0].buttons[0].args[1]["transition"]["duration"] = (
                frame_transition_duration
            )
        except IndexError:
            print("Error changing frame transitionduration")

        return st.plotly_chart(fig, use_container_width=False)

    change_animation_speed_and_duration()

    with st.expander("View the vidigi code"):
        st.code("""
    fig = animate_activity_log(
        event_log=my_trial.all_event_logs[my_trial.all_event_logs["run"] == 1],
        event_position_df=event_position_df,
        scenario=g(),
        entity_col_name="patient",
        debug_mode=True,
        setup_mode=True,
        every_x_time_units=5,
        include_play_button=True,
        gap_between_entities=11,
        gap_between_resources=15,
        gap_between_resource_rows=30,
        gap_between_queue_rows=30,
        plotly_height=600,
        plotly_width=1000,
        override_x_max=700,
        override_y_max=675,
        entity_icon_size=10,
        resource_icon_size=13,
        text_size=15,
        wrap_queues_at=10,
        step_snapshot_max=20,
        limit_duration=g.sim_duration,
        time_display_units="dhm",
        display_stage_labels=False,
        add_background_image="https://raw.githubusercontent.com/Bergam0t/vidigi/refs/heads/main/examples/example_2_branching_multistep/Full%20Model%20Background%20Image%20-%20Horizontal%20Layout.drawio.png",
    )


    @st.fragment
    def change_animation_speed_and_duration():
        frame_duration = st.slider("Set frame duration (ms)", 100, 2000, 800)
        frame_transition_duration = st.slider(
            "Set frame transition duration (ms)", 100, 2000, 800
        )

        try:
            fig.layout.updatemenus[0].buttons[0].args[1]["frame"]["duration"] = (
                frame_duration
            )
        except IndexError:
            print("Error changing frame duration")

        try:
            fig.layout.updatemenus[0].buttons[0].args[1]["transition"]["duration"] = (
                frame_transition_duration
            )
        except IndexError:
            print("Error changing frame transitionduration")

        return st.plotly_chart(fig)

    change_animation_speed_and_duration()
    """)
