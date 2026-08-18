"""DataFrames in, go.Figure out.

Every function here is a thin wrapper over its `vidigi.analysis` twin: axis
formatting and trace styling only, no arithmetic beyond that.

`**kwargs` means two different things depending on the function, and each
docstring says which:

- On `plot_queue_size` - extracted from pre-existing code, where `**kwargs` has
  always forwarded to `plotly.express.line` - that meaning is kept, so no
  existing caller's styling kwargs silently start doing something else. Column
  names are separate, explicitly named parameters there instead.
- On every function new in 1.4.0+ (e.g. `plot_duration_distribution`),
  `**kwargs` is column-name passthrough to the underlying `vidigi.analysis`
  function instead - there is no single plotly call to forward general styling
  to, since `go` builds several traces by hand. Style the returned figure
  directly.
"""

import warnings
from typing import Literal, Optional, TypeAlias, Union

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from vidigi.analysis import event_durations, queue_size_over_time, MatchMode

# Which plotly API draws the chart. Mirrors `vidigi.animation.AnimationBackend`'s
# accepted spellings and case-insensitive matching, for consistency across the
# package. Editors offer these as completions, but the value is still validated
# at runtime, since annotations are not enforced.
PlotBackend: TypeAlias = Literal[
    "express",
    "px",
    "plotly express",
    "go",
    "graph objects",
    "plotly graph objects",
    "plotly go",
]


def _resolve_backend(backend: str) -> str:
    lowered = str.lower(backend)
    if lowered in ("express", "px", "plotly express"):
        return "express"
    if lowered in ("go", "graph objects", "plotly graph objects", "plotly go"):
        return "go"
    raise ValueError(
        f"Invalid backend passed: '{backend}'. Options are: 'express'|'px'|"
        f"'plotly express' for the plotly express backend (default), or "
        f"'go'|'graph objects'|'plotly graph objects'|'plotly go' for the plotly "
        f"graph objects backend. Matching is case-insensitive."
    )


def plot_queue_size(
    event_log: pd.DataFrame,
    event_list: list,
    limit_duration,
    *,
    every_x_time_units: int = 1,
    warm_up: int = 0,
    show_all_runs: bool = True,
    shared_y_axis: bool = True,
    backend: PlotBackend = "express",
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
    backend : {"express", "go"}, default="express"
        Which plotly API builds the figure. `"express"` (several spellings
        accepted, see `vidigi.animation.AnimationBackend` for the equivalent on
        the animation functions) matches the pre-existing behaviour and accepts
        `**kwargs` forwarded to `plotly.express.line` for styling at creation
        time. `"go"` builds every trace explicitly with `plotly.graph_objects`
        instead: trace names, order and legend grouping are then deterministic
        rather than depending on `px`'s automatic grouping, which some callers
        find easier to target when restyling the figure afterwards. `**kwargs`
        is not used by the `"go"` backend - style the returned figure directly.
    run_col_name : str or None, default="auto"
        Column identifying which run each row belongs to. See
        `vidigi.analysis.queue_size_over_time`.
    entity_col_name, time_col_name, event_type_col_name, event_col_name,
    pathway_col_name : str or None
        Column names forwarded to `vidigi.analysis.queue_size_over_time`.
    **kwargs : dict
        Additional keyword arguments passed to `plotly.express.line`. Ignored
        (with a warning) when `backend="go"`.

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
    resolved_backend = _resolve_backend(backend)

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

    if resolved_backend == "express":
        return _plot_queue_size_express(
            event_counts, mean_df, event_list, show_all_runs, shared_y_axis, **kwargs
        )

    if kwargs:
        warnings.warn(
            f"backend='go' does not use **kwargs (got {sorted(kwargs)}); they are "
            f"ignored. Style the returned figure directly instead.",
            UserWarning,
            stacklevel=2,
        )
    return _plot_queue_size_go(event_counts, mean_df, event_list, show_all_runs, shared_y_axis)


def _plot_queue_size_express(
    event_counts, mean_df, event_list, show_all_runs, shared_y_axis, **kwargs
) -> go.Figure:
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


def _plot_queue_size_go(
    event_counts, mean_df, event_list, show_all_runs, shared_y_axis
) -> go.Figure:
    n_events = len(event_list)

    if n_events > 1:
        fig = make_subplots(
            rows=n_events,
            cols=1,
            shared_yaxes=shared_y_axis,
            subplot_titles=event_list,
        )
    else:
        fig = go.Figure()

    event_to_row = {event: i + 1 for i, event in enumerate(event_list)}

    def _add_trace(trace, event):
        if n_events > 1:
            fig.add_trace(trace, row=event_to_row[event], col=1)
        else:
            fig.add_trace(trace)

    if show_all_runs:
        run_ids = list(event_counts["run_number"].dropna().unique())
        try:
            run_ids = sorted(run_ids)
        except TypeError:
            pass
        # A log with no run column produces an all-NA run_number - a single
        # unnamed group, rather than no runs at all.
        if not run_ids:
            run_ids = [None]

        for run_id in run_ids:
            if run_id is None:
                run_rows = event_counts[event_counts["run_number"].isna()]
            else:
                run_rows = event_counts[event_counts["run_number"] == run_id]
            for j, event in enumerate(event_list):
                sub = run_rows[run_rows["event"] == event].sort_values(
                    "snapshot_time"
                )
                _add_trace(
                    go.Scatter(
                        x=sub["snapshot_time"],
                        y=sub["count"],
                        mode="lines",
                        opacity=0.2,
                        legendgroup=str(run_id),
                        name=str(run_id),
                        showlegend=(j == 0),
                    ),
                    event,
                )

    for event in event_list:
        sub = mean_df[mean_df["event"] == event].sort_values("snapshot_time")
        _add_trace(
            go.Scatter(
                x=sub["snapshot_time"],
                y=sub["count"],
                mode="lines",
                line=dict(color="black", width=3),
                name="Mean",
                legendgroup="Mean",
                showlegend=(event == event_list[0]),
            ),
            event,
        )

    fig.update_xaxes(title_text="snapshot_time")
    fig.update_yaxes(title_text="count")

    return fig


# Chart type for `plot_duration_distribution`. Editors offer these as
# completions, but the value is still validated at runtime, since annotations
# are not enforced.
DistributionKind: TypeAlias = Literal["hist", "box", "violin", "ecdf"]

# Which column of `vidigi.analysis.event_durations`'s output `split_by` groups on.
SplitBy: TypeAlias = Literal["run", "pathway"]
_SPLIT_BY_COLUMNS = {"run": "run_number", "pathway": "pathway"}


def plot_duration_distribution(
    event_log: pd.DataFrame,
    first_event: str,
    second_event: str,
    *,
    kind: DistributionKind = "hist",
    split_by: Optional[SplitBy] = None,
    bins: Optional[Union[int, list, np.ndarray]] = None,
    match: MatchMode = "first",
    normalise: bool = False,
    title: Optional[str] = None,
    **kwargs,
) -> go.Figure:
    """
    Plot the distribution of durations between two events.

    Thin wrapper over `vidigi.analysis.event_durations`: this function only bins
    (for `kind="hist"`) or reshapes the resulting durations for the chosen chart
    type - no statistic is computed that isn't already in that DataFrame.

    Parameters
    ----------
    event_log : pandas.DataFrame
        Long-format event log, e.g. the output of `TrialLogger.to_dataframe()`.
    first_event, second_event : str
        The two events to measure the duration between. See
        `vidigi.analysis.event_durations`.
    kind : {"hist", "box", "violin", "ecdf"}, default="hist"
        Chart type.

        - ``"hist"``: a histogram, binned with `numpy.histogram` and drawn as
          bars - never `plotly.graph_objects.Histogram`, which bins in the
          browser and so has no inspectable `y` values.
        - ``"box"`` / ``"violin"``: the raw durations, one trace per group (or a
          single trace when `split_by` is `None`).
        - ``"ecdf"``: the empirical cumulative distribution function, drawn as a
          step line - linear interpolation between the sorted points would draw
          probabilities that never occurred.
    split_by : {"run", "pathway"} or None, default=None
        If given, produces one trace per distinct value of the corresponding
        column (`run_number` or `pathway`) instead of a single trace over every
        duration pooled together.
    bins : int, sequence, or None, default=None
        Passed to `numpy.histogram` when `kind="hist"`. `None` uses 10 bins,
        matching `numpy.histogram`'s own default. The same bin edges are used
        for every group when `split_by` is set, so bars stay comparable across
        groups. Ignored for other kinds.
    match : {"first", "last", "occurrence"}, default="first"
        How repeated occurrences of the two events are paired. See
        `vidigi.analysis.event_durations`.
    normalise : bool, default=False
        For `kind="hist"` only: if True, bar heights are a probability density
        (area sums to 1) rather than raw counts. Ignored for other kinds, whose
        y-axis is either the raw durations or already a proportion (`"ecdf"`).
    title : str, optional
        Figure title. There is no general plotly-kwargs passthrough on this
        function - style the returned figure directly.
    **kwargs : dict
        Additional keyword arguments forwarded to
        `vidigi.analysis.event_durations` (e.g. `entity_col_name`,
        `run_col_name`).

    Returns
    -------
    plotly.graph_objects.Figure

    Raises
    ------
    ValueError
        If `kind` or `split_by` is not one of the supported values; if no
        complete pairs are found to plot; or if `split_by` is set but the
        corresponding column is entirely missing from the durations.

    See Also
    --------
    vidigi.analysis.event_durations : The underlying per-entity durations.

    Notes
    -----
    Rows with an incomplete pairing (`duration` is `NaN` - an entity that never
    reached `second_event`, or vice versa) cannot be plotted on a distribution
    and are dropped before drawing. Call `vidigi.analysis.event_durations`
    directly if you need to know how many were excluded.
    """
    if kind not in ("hist", "box", "violin", "ecdf"):
        raise ValueError(
            f"`kind` must be one of 'hist', 'box', 'violin', 'ecdf'; got {kind!r}."
        )
    if split_by is not None and split_by not in _SPLIT_BY_COLUMNS:
        raise ValueError(
            f"`split_by` must be one of 'run', 'pathway', or None; got {split_by!r}."
        )

    durations = event_durations(
        event_log, first_event, second_event, match=match, **kwargs
    )
    durations = durations[durations["duration"].notna()]

    if durations.empty:
        raise ValueError(
            f"No complete '{first_event}' -> '{second_event}' pairs were found to "
            f"plot a distribution from."
        )

    axis_label = f"{first_event} -> {second_event} duration"

    if split_by is None:
        groups = [(None, durations)]
    else:
        group_col = _SPLIT_BY_COLUMNS[split_by]
        if durations[group_col].isna().all():
            raise ValueError(
                f"`split_by=\"{split_by}\"` was requested, but the '{group_col}' "
                f"column is entirely missing from the durations - `event_log` has "
                f"no {split_by} information for this event pair. Pass "
                f"`split_by=None`, or check `run_col_name`/`pathway_col_name`."
            )
        groups = list(durations.groupby(group_col, dropna=True))

    fig = go.Figure()

    def _trace_name(group_value):
        return str(group_value) if group_value is not None else axis_label

    if kind == "hist":
        edges = np.histogram_bin_edges(
            durations["duration"].to_numpy(), bins=(10 if bins is None else bins)
        )
        centers = (edges[:-1] + edges[1:]) / 2
        widths = np.diff(edges)
        for group_value, group_df in groups:
            counts, _ = np.histogram(
                group_df["duration"].to_numpy(), bins=edges, density=normalise
            )
            fig.add_trace(
                go.Bar(
                    x=centers,
                    y=counts,
                    width=widths,
                    name=_trace_name(group_value),
                    opacity=0.7 if split_by is not None else 1.0,
                    hovertemplate="Duration: %{x:.2f}<br>"
                    + ("Density" if normalise else "Count")
                    + ": %{y}<extra></extra>",
                )
            )
        if split_by is not None:
            fig.update_layout(barmode="overlay")
        fig.update_xaxes(title_text=axis_label)
        fig.update_yaxes(title_text="density" if normalise else "count")

    elif kind in ("box", "violin"):
        trace_cls = go.Box if kind == "box" else go.Violin
        for group_value, group_df in groups:
            fig.add_trace(
                trace_cls(y=group_df["duration"], name=_trace_name(group_value))
            )
        fig.update_yaxes(title_text=axis_label)

    else:  # ecdf
        for group_value, group_df in groups:
            sorted_durations = np.sort(group_df["duration"].to_numpy())
            n = len(sorted_durations)
            fig.add_trace(
                go.Scatter(
                    x=sorted_durations,
                    y=np.arange(1, n + 1) / n,
                    mode="lines",
                    line_shape="hv",
                    name=_trace_name(group_value),
                    hovertemplate="Duration: %{x:.2f}<br>"
                    "Cumulative proportion: %{y:.3f}<extra></extra>",
                )
            )
        fig.update_xaxes(title_text=axis_label)
        fig.update_yaxes(title_text="cumulative proportion")

    if title is not None:
        fig.update_layout(title=title)

    return fig
