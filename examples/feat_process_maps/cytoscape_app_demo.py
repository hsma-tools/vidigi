import streamlit as st
import pandas as pd
from vidigi.process_mapping import (
    dfg_to_cytoscape_streamlit,
    add_sim_timestamp,
    discover_dfg,
    dfg_to_graphviz,
)

st.set_page_config(layout="wide")

st.title("Vidigi Process Map Output Showcase")

stroke_df = pd.read_csv("dev/event_log_stroke.csv")

with st.expander("Click to view the original event log"):
    st.dataframe(stroke_df)

    st.write(
        "We then tidy up some of the event names, making them shorter and replacing underscores with spaces so that they will wrap over multiple lines in the diagram."
    )

    stroke_df["event"] = stroke_df["event"].apply(
        lambda x: x.replace("_time", "").replace("_", " ")
    )

    st.code("""
stroke_df["event"] = stroke_df["event"].apply(
    lambda x: x.replace("_time", "").replace("_", " ")
)
            """)

    st.write(
        "We also add a timestamp column. These diagrams need an actual datetime to work from - even if the date and time are not 'real', as such."
    )

    stroke_df_timestamp = add_sim_timestamp(stroke_df)

    st.code("""
stroke_df_timestamp = add_sim_timestamp(stroke_df)
            """)

with st.expander("Click here to view the processed dataframe"):
    st.write(
        "We then use the `discover_dfg` function to turn this into a final dataframe that can be understood by the various graphing functions."
    )

    nodes, edges = discover_dfg(stroke_df_timestamp, case_col="id")

    st.code("""
nodes, edges = discover_dfg(stroke_df_timestamp, case_col="id")
""")

    st.subheader("Nodes")
    st.write(nodes)

    st.subheader("Edges")
    st.write(edges)

tab1, tab2 = st.tabs(["Static", "Interactive"])

with tab1:
    with st.spinner():
        st.subheader("Left to right")
        st.image(dfg_to_graphviz(nodes, edges, return_image=True))

        st.subheader("Top to bottom")
        st.image(dfg_to_graphviz(nodes, edges, return_image=True, direction="TD"))


with tab2:

    @st.fragment
    def make_dfg():
        layout = st.selectbox(
            "Select a layout",
            ["breadthfirst", "grid", "circle", "concentric", "cose", "fcose", "klay"],
        )

        if layout == "breadthfirst":
            orientation = st.selectbox(
                "Select an orientation", ["downward", "upward", "rightward", "leftward"]
            )
            selected = dfg_to_cytoscape_streamlit(
                nodes, edges, layout_name=layout, layout_orientation=orientation
            )

        else:
            selected = dfg_to_cytoscape_streamlit(nodes, edges, layout_name=layout)

        st.markdown("**Selected nodes**: %s" % (", ".join(selected["nodes"])))
        st.markdown("**Selected edges**: %s" % (", ".join(selected["edges"])))

    with st.spinner():
        make_dfg()
