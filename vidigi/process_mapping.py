import pandas as pd
from graphviz import Digraph
import ipycytoscape
import ipywidgets as widgets

VALID_TIME_UNITS = {"seconds", "minutes", "hours", "days", "weeks"}

VALID_FORMATS = {
    "ascii",
    "bmp",
    "dot",
    "gif",
    "jpeg",
    "json",
    "pdf",
    "png",
    "svg",
    "tiff",
}


def add_sim_timestamp(
    log: pd.DataFrame,
    time_col: str = "time",
    timestamp_col: str = "timestamp",
    sim_start: pd.Timestamp | str | None = None,
    time_unit: str = "minutes",
) -> pd.DataFrame:
    """
    Add a pseudo-timestamp column to a simulation event log.
    This is a helper function for process-mining style outputs.

    If the simulation does not have a 'true' start time

    Parameters
    ----------
    log : pd.DataFrame
        Event log with a column containing the simulation-relative time per event.
    time_col : str
        Column containing simulation time since model start.
        Default: "time". This will be the name of the column if you have
        made use of Vidigi's EventLogger defaults.
    timestamp_col : str
        Desired name of output timestamp column.
        Default: "timestamp"
    sim_start : pd.Timestamp, str, or None
        Start datetime of the simulation.
        If None, a fixed pseudo-start of '2000-01-01 00:00:00' is used.
    time_unit : str
        Unit of the simulation time.
        Accepted values are 'seconds', 'minutes', 'hours', 'days' or 'weeks'.
        Default: "minutes".

    Returns
    -------
    pd.DataFrame
        Copy of the provided event log (parameter `log`) with an added timestamp column.
    """
    if time_unit not in VALID_TIME_UNITS:
        raise ValueError(
            f"Invalid time_unit '{time_unit}'. "
            f"Supported values are: {', '.join(sorted(VALID_TIME_UNITS))}."
        )

    if time_unit == "weeks":
        time_unit = "W"

    if time_col not in log.columns:
        raise KeyError(f"Column '{time_col}' not found in event log")

    df = log.copy()

    if sim_start is None:
        sim_start = pd.Timestamp("2000-01-01 00:00:00")
    else:
        sim_start = pd.to_datetime(sim_start)

    df[timestamp_col] = sim_start + pd.to_timedelta(df[time_col], unit=time_unit)

    return df


def discover_dfg(
    log: pd.DataFrame,
    case_col: str = "entity_id",
    activity_col: str = "event",
    timestamp_col: str = "timestamp",
    time_unit: str = "minutes",
):
    """
    Discover a Directly-Follows Graph (DFG) from an event log.
    Returns node and edge tables.
    """
    if time_unit not in VALID_TIME_UNITS:
        raise ValueError(
            f"Invalid time_unit '{time_unit}'. "
            f"Supported values are: {', '.join(sorted(VALID_TIME_UNITS))}."
        )

    df = log.sort_values([case_col, timestamp_col]).copy()

    # Shift to get "next activity" per case
    df["next_activity"] = df.groupby(case_col)[activity_col].shift(-1)
    df["next_time"] = df.groupby(case_col)[timestamp_col].shift(-1)

    # Drop case endings
    dfg = df.dropna(subset=["next_activity"]).copy()

    # Transition duration
    if time_unit == "seconds":
        dfg["delta_time"] = (dfg["next_time"] - dfg[timestamp_col]).dt.total_seconds()
    elif time_unit == "minutes":
        dfg["delta_time"] = (
            (dfg["next_time"] - dfg[timestamp_col]).dt.total_seconds()
        ) / 60
    elif time_unit == "hours":
        dfg["delta_time"] = (
            ((dfg["next_time"] - dfg[timestamp_col]).dt.total_seconds()) / 60 / 60
        )
    elif time_unit == "days":
        dfg["delta_time"] = (
            ((dfg["next_time"] - dfg[timestamp_col]).dt.total_seconds()) / 60 / 60 / 24
        )
    elif time_unit == "weeks":
        dfg["delta_time"] = (
            ((dfg["next_time"] - dfg[timestamp_col]).dt.total_seconds())
            / 60
            / 60
            / 24
            / 7
        )

    # Aggregate edges
    edges = (
        dfg.groupby([activity_col, "next_activity"])
        .agg(
            frequency=("delta_time", "count"),
            mean_time=("delta_time", "mean"),
            median_time=("delta_time", "median"),
            max_time=("delta_time", "max"),
            min_time=("delta_time", "min"),
            standard_deviation_time=("delta_time", "std"),
        )
        .reset_index()
        .rename(columns={activity_col: "source", "next_activity": "target"})
    )

    # Transition probabilities
    edges["probability"] = edges["frequency"] / edges.groupby("source")[
        "frequency"
    ].transform("sum")

    # Node counts
    nodes = (
        df.groupby(activity_col)
        .agg(count=(case_col, "count"))
        .reset_index()
        .rename(columns={activity_col: "activity"})
    )

    return nodes, edges


def scale_penwidth(values, min_width=0.8, max_width=5.0):
    vmin = min(values)
    vmax = max(values)

    if vmax == vmin:
        return {v: (min_width + max_width) / 2 for v in values}

    return {
        v: min_width + (v - vmin) / (vmax - vmin) * (max_width - min_width)
        for v in values
    }


def dfg_to_graphviz(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    min_frequency: int | None = None,
    min_probability: float | None = None,
    time_unit: str = "minutes",
    direction: str = "LR",
    time_metric: str = "mean",
    title: str | None = None,
    title_font_size: int = 20,
    title_loc: str = "t",
    dashed_infrequent_paths: bool = True,
    infrequent_path_dash_threshold: float = 0.1,
    format: str = "png",
    return_image=False,
):
    if time_unit not in VALID_TIME_UNITS:
        raise ValueError(
            f"Invalid time_unit '{time_unit}'. "
            f"Supported values are: {', '.join(sorted(VALID_TIME_UNITS))}."
        )

    if format not in VALID_FORMATS:
        raise ValueError(
            f"Invalid format '{format}'. "
            f"Supported values are: {', '.join(sorted(VALID_FORMATS))}."
        )

    dot = Digraph(engine="dot")
    dot.attr(rankdir=direction)

    # Add nodes
    for _, row in nodes.iterrows():
        dot.node(
            row["activity"],
            label=f"{row['activity']}\n(n={row['count']})",
            shape="box",
            style="rounded",
        )

    # Add edges
    freqs = edges["frequency"].tolist()
    penwidth_map = scale_penwidth(freqs)

    for _, row in edges.iterrows():
        if dashed_infrequent_paths:
            style = (
                "dashed"
                if row["probability"] < infrequent_path_dash_threshold
                else "solid"
            )
        else:
            None

        pw = penwidth_map[row["frequency"]]

        if min_frequency is not None:
            if row["frequency"] < min_frequency:
                continue

        if min_probability is not None:
            if row["probability"] < min_probability:
                continue

        time_label = f"{row[f'{time_metric}_time']:.1f} {time_unit}"

        label = f"n={row['frequency']}\np={row['probability']:.2f}\navg={time_label}"

        dot.edge(
            row["source"], row["target"], label=label, penwidth=f"{pw:.2f}", style=style
        )

    if title:
        dot.attr(label=title, labelloc=title_loc, fontsize=f"{title_font_size}")

    if not return_image:
        return dot
    else:
        return dot.pipe(format=format)


def dfg_to_cytoscape(
    nodes,
    edges,
    edge_label: str = "frequency",
    node_label: str = "activity",
    min_frequency: int = 1,
    layout_name: str = "dagre",
    layout_orientation: str = "LR",
    spacing_factor: float = 1.0,
    time_unit: str = "minutes",
    time_metric: str = "mean",
    width: int = 1200,
    height: int = 600,
    show_transition_probabilities: bool = True,
    show_edge_counts: bool = True,
    show_metric: bool = True,
    show_node_counts: bool = True,
):
    """
    Convert DFG node/edge tables to interactive Cytoscape widget.

    Parameters
    ----------
    nodes : pd.DataFrame
        Must contain 'activity' (node ID) and optional 'count'
    edges : pd.DataFrame
        Must contain 'source', 'target', and edge_label column
    edge_label : str
        Column to use for edge labels (e.g., frequency, avg_time)
    node_label : str
        Column to use for node labels
    min_frequency : int or None
        Filter edges below this frequency
    layout_name: str
        Algorithm for layout to use. Supported variants include 'cose', 'cose-bilkent',
        'breadthfirst', 'circle', 'grid', 'concentric', and 'dagre'
        Default: 'dagre'
    orientation: str
        Ignored if layout_name is not 'dagre' or 'breadthfirst'.
        Valid inputs are 'TB', 'LR', 'RL', 'BT'

    Returns
    -------
    ipywidgets.Box
    """
    # Filter low-frequency edges
    edges_filtered = edges[edges[edge_label] >= min_frequency]

    # Cast all IDs to strings to ensure matching
    cy_nodes = [
        {
            "data": {
                "id": str(row[node_label]),
                "label": str(row[node_label])
                + (f"\nn={row['count']}" if show_node_counts else ""),
            },
            "classes": "multiline-manual",
        }
        for _, row in nodes.iterrows()
    ]

    cy_edges = [
        {
            "data": {
                "source": str(row["source"]),
                "target": str(row["target"]),
                "label": (f"n={row.frequency}\n" if show_edge_counts else "")
                + (
                    f"p={row.probability:.2f}\n"
                    if show_transition_probabilities
                    else ""
                )
                + (
                    f"avg={row[f'{time_metric}_time']:.1f} {time_unit}"
                    if show_metric
                    else ""
                ),
                "weight": row.probability,
            }
        }
        for _, row in edges_filtered.iterrows()
    ]

    # Build widget
    cytoscapeobj = ipycytoscape.CytoscapeWidget()

    cytoscapeobj.layout.width = f"{width}px"
    cytoscapeobj.layout.height = f"{height}px"

    cytoscapeobj.graph.add_graph_from_json({"nodes": cy_nodes, "edges": cy_edges})

    cytoscapeobj.set_tooltip_source("label")

    # # Style: simple default style
    style_list = [
        {
            "selector": "node",
            "style": {
                "content": "data(label)",
                "background-color": "skyblue",
                "text-valign": "center",
                "text-halign": "center",
                "width": "40px",
                "height": "40px",
                "font-size": "10px",
                "text-wrap": "wrap",
                "text-max-width": 40,
            },
        },
        {
            "selector": "edge",
            "style": {
                "content": "data(label)",
                "curve-style": "bezier",
                "target-arrow-shape": "triangle",
                "line-color": "#9dbaea",
                "target-arrow-color": "#9dbaea",
                "font-size": "8px",
                "text-wrap": "wrap",
                "text-max-width": 80,
                "width": "mapData(weight, 0, 1, 1, 6)",
                # 'opacity': 'mapData(weight, 0, 1, 0.3, 1.0)',
            },
        },
    ]
    cytoscapeobj.set_style(style_list)

    layout_options = {
        "name": layout_name,
        "directed": True,
        "animate": True,
        "randomize": True,
        "numIter": 1,
        "fit": False,
        "padding": 30,
        "spacingFactor": spacing_factor,
    }

    if layout_name == "dagre":
        layout_options["rankDir"] = layout_orientation
    elif layout_name == "breadthfirst":
        layout_options["direction"] = layout_orientation

    cytoscapeobj.set_layout(**layout_options)

    container = widgets.Box(
        [cytoscapeobj],
        layout=widgets.Layout(
            width=f"{width + 20}px", height=f"{height}px", border="1px solid lightgray"
        ),
    )

    return container
