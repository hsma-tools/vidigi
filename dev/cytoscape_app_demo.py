import streamlit as st
import pandas as pd
from vidigi.process_mapping import (
    dfg_to_cytoscape_streamlit,
    add_sim_timestamp,
    discover_dfg,
)

st.set_page_config(layout="wide")

stroke_df = pd.read_csv("dev/event_log_stroke.csv")
stroke_df.head()

stroke_df["event"] = stroke_df["event"].apply(
    lambda x: x.replace("_time", "").replace("_", " ")
)

stroke_df_timestamp = add_sim_timestamp(stroke_df)

nodes, edges = discover_dfg(stroke_df_timestamp, case_col="id")

st.write(nodes)

st.write(edges)


@st.fragment
def make_dfg():
    layout = st.selectbox(
        "Select a layout",
        ["breadthfirst", "grid", "circle", "concentric", "cose", "fcose", "klay"],
    )
    orientation = st.selectbox(
        "Select an orientation", ["downward", "upward", "rightward", "leftward"]
    )
    selected = dfg_to_cytoscape_streamlit(
        nodes, edges, layout_name=layout, layout_orientation=orientation
    )

    st.markdown("**Selected nodes**: %s" % (", ".join(selected["nodes"])))
    st.markdown("**Selected edges**: %s" % (", ".join(selected["edges"])))


make_dfg()
