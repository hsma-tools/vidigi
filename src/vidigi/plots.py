"""DataFrames in, go.Figure out.

Every function here is a thin wrapper over its `vidigi.analysis` twin: axis
formatting and trace styling only, no arithmetic beyond that. Column-name
overrides are explicit keyword parameters rather than a generic `**kwargs`, so
`**kwargs` stays free to forward styling straight through to the underlying
plotly express call, matching the existing behaviour of `plot_metric_bar`.
"""

from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from vidigi.analysis import queue_size_over_time


def plot_queue_size(
    event_log: pd.DataFrame,
    event_list: list,
    limit_duration,
    *,
    every_x_time_units: int = 1,
    warm_up: int = 0,
    show_all_runs: bool = True,
    shared_y_axis: bool = True,
    run_col_name: Optional[str] = "auto",
    entity_col_name: str = "entity_id",
    time_col_name: str = "time",
    event_type_col_name: str = "event_type",
    event_col_name: str = "event",
    pathway_col_name: Optional[str] = None,
    **kwargs,
) -> go.Figure:
    """
    Plot the size of one or more queues over time, across every run.

    Thin wrapper over `vidigi.analysis.queue_size_over_time`: this function only
    builds the figure from that data.

    Parameters
    ----------
    event_log : pandas.DataFrame
        Long-format event log spanning one or more runs, e.g. the output of
        `TrialLogger.to_dataframe()`.
    event_list : list of str
        Event names (matched against `event_col_name`) to plot a queue size for.
    limit_duration : int or float
        Maximum time to include, in the same units as `time_col_name`.
    every_x_time_units : int, default=1
        Time granularity for snapshots. Larger values aggregate queue size over
        coarser time intervals.
    warm_up : int, default=0
        Time at which the plotted window begins. Snapshots run from `warm_up` to
        `limit_duration`. See `vidigi.prep.reshape_for_animations` for why this -
        and not filtering the log by time - is the correct way to discard a
        warm-up period; the default of `0` is a no-op.
    show_all_runs : bool, default=True
        If True, plots every run with semi-transparent lines and overlays the
        mean trajectory. If False, only the mean trajectory is plotted.
    shared_y_axis : bool, default=True
        If True (and more than one event is plotted), every facet shares a y-axis
        range. If False, each is scaled independently.
    run_col_name : str or None, default="auto"
        Column identifying which run each row belongs to. See
        `vidigi.analysis.queue_size_over_time`.
    entity_col_name, time_col_name, event_type_col_name, event_col_name,
    pathway_col_name : str or None
        Column names forwarded to `vidigi.analysis.queue_size_over_time`.
    **kwargs : dict
        Additional keyword arguments passed to `plotly.express.line`.

    Returns
    -------
    plotly.graph_objects.Figure

    Notes
    -----
    - When multiple event types are specified, they are faceted in separate
      panels.
    - Queue lengths are **not** capped at the display limit used by the
      animation functions, so long queues are plotted at their full length.
    - A snapshot where an event has nobody queuing is plotted as zero rather than
      omitted, so a queue that empties is drawn dropping to the axis, and the
      mean is taken across every run rather than only those with someone
      waiting. An event in `event_list` that occurs in no run is plotted as zero
      throughout, with a warning.

    See Also
    --------
    vidigi.analysis.queue_size_over_time : The underlying per-run, per-snapshot counts.

    Examples
    --------
    >>> plot_queue_size(
    ...     trial.to_dataframe(),
    ...     event_list=["queue_enter", "queue_exit"],
    ...     limit_duration=500,
    ...     every_x_time_units=5,
    ... )
    <plotly.graph_objs._figure.Figure>
    """
    event_counts = queue_size_over_time(
        event_log,
        event_list,
        limit_duration,
        every_x_time_units=every_x_time_units,
        warm_up=warm_up,
        run_col_name=run_col_name,
        entity_col_name=entity_col_name,
        time_col_name=time_col_name,
        event_type_col_name=event_type_col_name,
        event_col_name=event_col_name,
        pathway_col_name=pathway_col_name,
    )

    mean_df = event_counts.groupby(["snapshot_time", "event"], as_index=False)[
        "count"
    ].mean()

    faceting_variable = "event" if len(event_list) > 1 else None

    if show_all_runs:
        fig = px.line(
            event_counts,
            x="snapshot_time",
            y="count",
            color="run_number",
            **kwargs,
            facet_row=faceting_variable,
        )

        fig.update_traces(opacity=0.2)
        if not shared_y_axis:
            fig.update_yaxes(matches=None)

        if faceting_variable is None:
            fig.add_trace(
                go.Scatter(
                    x=mean_df["snapshot_time"],
                    y=mean_df["count"],
                    mode="lines",
                    line=dict(color="black", width=3),
                    name="Mean",
                )
            )
        else:
            # Build mapping from event name -> subplot row index
            event_to_row = {}
            for i, ann in enumerate(fig.layout.annotations):
                if ann.text.startswith(
                    "event="
                ):  # e.g. "event=MINORS_examination_begins"
                    event_name = ann.text.split("=")[-1]
                    # Use enumeration index + 1 for proper row indexing
                    event_to_row[event_name] = i + 1

            # Add mean traces to the correct row
            for event_name, df_event in mean_df.groupby("event"):
                row_idx = event_to_row.get(event_name, 1)
                fig.add_trace(
                    go.Scatter(
                        x=df_event["snapshot_time"],
                        y=df_event["count"],
                        mode="lines",
                        line=dict(color="black", width=3),
                        name="Mean",
                        showlegend=False,
                    ),
                    row=row_idx,
                    col=1,
                )

            # Show legend for just one mean line
            if len(fig.data) > 0:
                fig.data[-1].showlegend = True

            fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))

        return fig
    else:
        fig = px.line(
            mean_df,
            x="snapshot_time",
            y="count",
            facet_row=faceting_variable,
            **kwargs,
        )

        if not shared_y_axis:
            fig.update_yaxes(matches=None)

        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))

        return fig
