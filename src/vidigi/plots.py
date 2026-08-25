"""DataFrames in, go.Figure out.

Every function here is a thin wrapper over its `vidigi.analysis` twin: axis
formatting and trace styling only, no arithmetic beyond that.

`**kwargs` means two different things depending on the function, and each
docstring says which:

- On `plot_queue_size` and `plot_metric_bar` - both extracted from pre-existing
  code, where `**kwargs` has always forwarded to `plotly.express.line`/`.bar`
  respectively - that meaning is kept, so no existing caller's styling kwargs
  silently start doing something else (the committed example notebook relies on
  exactly this for `plot_metric_bar`'s `title=`/`width=`). Column names are
  separate, explicitly named parameters on both instead.
- On every function new in 1.4.0+ (e.g. `plot_duration_distribution`),
  `**kwargs` is column-name passthrough to the underlying `vidigi.analysis`
  function instead - there is no single plotly call to forward general styling
  to, since `go` builds several traces by hand. Style the returned figure
  directly.
"""

import warnings
from typing import Literal, Optional, Sequence, TypeAlias, Union

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from vidigi.analysis import (
    DurationStat,
    MatchMode,
    ResourceUtilisationBy,
    UnclosedResourceUse,
    WarmUpMethod,
    _ensemble_mean,
    _nearest_match_hint,
    _resolve_resource_capacities,
    _summarise_durations,
    event_durations,
    mean_confidence_interval,
    queue_size_over_time,
    replication_means,
    replication_precision,
    resource_occupancy_over_time,
    resource_use_intervals,
    resource_utilisation,
    welch_moving_average,
)
from vidigi.utils import _resolve_run_column

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
DistributionKind: TypeAlias = Literal[
    "hist", "box", "violin", "ecdf", "ridgeline", "heatmap"
]
_DISTRIBUTION_KINDS = ("hist", "box", "violin", "ecdf", "ridgeline", "heatmap")
_MULTI_GROUP_KINDS = ("ridgeline", "heatmap")

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
    kind : {"hist", "box", "violin", "ecdf", "ridgeline", "heatmap"}, default="hist"
        Chart type.

        - ``"hist"``: a histogram, binned with `numpy.histogram` and drawn as
          bars - never `plotly.graph_objects.Histogram`, which bins in the
          browser and so has no inspectable `y` values.
        - ``"box"`` / ``"violin"``: the raw durations, one trace per group (or a
          single trace when `split_by` is `None`).
        - ``"ecdf"``: the empirical cumulative distribution function, drawn as a
          step line - linear interpolation between the sorted points would draw
          probabilities that never occurred.
        - ``"ridgeline"``: one histogram-derived density curve per group,
          stacked with a vertical offset and slight overlap ("joy plot" style).
          Always compares *shape* (each curve is its own density, area 1)
          rather than raw counts, so groups with different numbers of
          observations remain comparable; `normalise` is ignored. **Requires
          `split_by`** - a ridgeline needs more than one group to stack.
        - ``"heatmap"``: one row per group, duration binned along the x-axis,
          colour showing count or density per cell. Scales to far more groups
          than `"ridgeline"` can stay readable at, since it costs no vertical
          space per row. **Requires `split_by`.**
    split_by : {"run", "pathway"} or None, default=None
        If given, produces one trace (or, for `"heatmap"`, one row) per
        distinct value of the corresponding column (`run_number` or
        `pathway`) instead of a single trace over every duration pooled
        together. Required for `kind="ridgeline"` or `kind="heatmap"`.
    bins : int, sequence, or None, default=None
        Passed to `numpy.histogram` when `kind` is `"hist"`, `"ridgeline"` or
        `"heatmap"`. `None` uses 10 bins, matching `numpy.histogram`'s own
        default. The same bin edges are used for every group when `split_by`
        is set, so bars/rows stay comparable across groups. Ignored for other
        kinds.
    match : {"first", "last", "occurrence"}, default="first"
        How repeated occurrences of the two events are paired. See
        `vidigi.analysis.event_durations`.
    normalise : bool, default=False
        For `kind="hist"` or `kind="heatmap"`: if True, heights/cell values are
        a probability density (each group's area sums to 1) rather than raw
        counts. Ignored for other kinds - `"ridgeline"` always uses density
        (see above), and the y-axis of `"box"`/`"violin"`/`"ecdf"` is either
        the raw durations or already a proportion.
    title : str, optional
        Figure title. There is no general plotly-kwargs passthrough on this
        function - style the returned figure directly.
    **kwargs : dict
        Additional keyword arguments forwarded to
        `vidigi.analysis.event_durations` (e.g. `entity_col_name`,
        `run_col_name`, `warm_up`).

    Returns
    -------
    plotly.graph_objects.Figure

    Raises
    ------
    ValueError
        If `kind` or `split_by` is not one of the supported values; if `kind`
        is `"ridgeline"` or `"heatmap"` and `split_by` is not set; if no
        complete pairs are found to plot; if `split_by` is set but the
        corresponding column is entirely missing from the durations; or if
        `warm_up` is negative.

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
    if kind not in _DISTRIBUTION_KINDS:
        raise ValueError(
            f"`kind` must be one of {_DISTRIBUTION_KINDS}; got {kind!r}."
        )
    if split_by is not None and split_by not in _SPLIT_BY_COLUMNS:
        raise ValueError(
            f"`split_by` must be one of 'run', 'pathway', or None; got {split_by!r}."
        )
    if kind in _MULTI_GROUP_KINDS and split_by is None:
        raise ValueError(
            f"kind={kind!r} draws one {'curve' if kind == 'ridgeline' else 'row'} "
            f"per group, so needs more than one group to compare - pass "
            f"`split_by='run'` or `split_by='pathway'`. Use `kind='hist'` for a "
            f"single distribution."
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

    if kind in ("hist", "ridgeline", "heatmap"):
        edges = np.histogram_bin_edges(
            durations["duration"].to_numpy(), bins=(10 if bins is None else bins)
        )
        centers = (edges[:-1] + edges[1:]) / 2

    if kind == "hist":
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

    elif kind == "ecdf":
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

    elif kind == "ridgeline":
        # Always a density (area 1) per group, never a raw count: a group with
        # more observations would otherwise draw a taller ridge for the same
        # shape, which reads as "busier" rather than "differently distributed".
        row_height = 1.0
        group_densities = [
            (group_value, np.histogram(group_df["duration"].to_numpy(), bins=edges, density=True)[0])
            for group_value, group_df in groups
        ]
        peak = max((counts.max() for _, counts in group_densities), default=0.0)
        scale = (row_height * 1.5 / peak) if peak > 0 else 1.0

        offsets, labels = [], []
        for i, (group_value, counts) in enumerate(group_densities):
            offset = i * row_height
            offsets.append(offset)
            labels.append(_trace_name(group_value))
            heights = offset + counts * scale
            fig.add_trace(
                go.Scatter(
                    x=[centers[0], *centers, centers[-1], centers[0]],
                    y=[offset, *heights, offset, offset],
                    fill="toself",
                    mode="lines",
                    line=dict(width=1),
                    name=_trace_name(group_value),
                    hoverinfo="skip",
                )
            )
        fig.update_yaxes(tickvals=offsets, ticktext=labels, title_text=split_by)
        fig.update_xaxes(title_text=axis_label)

    else:  # heatmap
        z, labels = [], []
        for group_value, group_df in groups:
            counts, _ = np.histogram(
                group_df["duration"].to_numpy(), bins=edges, density=normalise
            )
            z.append(counts)
            labels.append(_trace_name(group_value))

        fig.add_trace(
            go.Heatmap(
                x=centers,
                y=labels,
                z=z,
                colorbar=dict(title="Density" if normalise else "Count"),
                hovertemplate="Duration: %{x:.2f}<br>"
                f"{split_by.capitalize()}"
                ": %{y}<br>"
                + ("Density" if normalise else "Count")
                + ": %{z}<extra></extra>",
            )
        )
        fig.update_xaxes(title_text=axis_label)
        fig.update_yaxes(title_text=split_by)

    if title is not None:
        fig.update_layout(title=title)

    return fig


# Whether a bar's value/error is computed over pooled entities or over
# replications. Editors offer these as completions, but the value is still
# validated at runtime, since annotations are not enforced.
Across: TypeAlias = Literal["entities", "runs"]

# Which spread `plot_metric_bar` and `plot_resource_utilisation` draw as an
# error bar around a bar computed over per-run values.
ErrorBars: TypeAlias = Literal["ci", "sd", "se", "range", "iqr"]
_ERROR_BAR_KINDS = ("ci", "sd", "se", "range", "iqr")


def _error_bar_bounds(
    run_values: pd.Series, error_bars: ErrorBars, ci_level: float, value: float
) -> tuple:
    """Return `(error_plus, error_minus)` for one group's per-run values.

    Shared by `plot_metric_bar` and `plot_resource_utilisation` - both draw an
    error bar around a bar height computed as the mean of values that are
    already one-per-run, just sourced differently (`replication_means` vs.
    `resource_utilisation`, which is already one row per run per group).
    """
    if error_bars == "ci":
        ci = mean_confidence_interval(run_values, ci_level=ci_level)
        return ci.half_width, ci.half_width
    if error_bars == "sd":
        sd = run_values.std(ddof=1)
        return sd, sd
    if error_bars == "se":
        se = run_values.std(ddof=1) / (len(run_values) ** 0.5)
        return se, se
    if error_bars == "range":
        return run_values.max() - value, value - run_values.min()
    # "iqr"
    q1, q3 = run_values.quantile([0.25, 0.75])
    return q3 - value, value - q1


def plot_metric_bar(
    event_log: pd.DataFrame,
    event_pair_list: list,
    *,
    what: DurationStat = "mean",
    exclude_incomplete: bool = True,
    across: Across = "entities",
    error_bars: Optional[ErrorBars] = None,
    ci_level: float = 0.95,
    show_runs: bool = False,
    match: MatchMode = "first",
    warm_up: float = 0,
    entity_col_name: str = "entity_id",
    time_col_name: str = "time",
    event_col_name: str = "event",
    run_col_name: Optional[str] = "auto",
    pathway_col_name: Optional[str] = "pathway",
    **kwargs,
) -> go.Figure:
    """
    Plot a bar chart of event duration statistics for a list of event pairs.

    Thin wrapper over `vidigi.analysis.event_durations`, `replication_means` and
    `mean_confidence_interval`: this function only aggregates their output into
    one bar per pair and builds the figure.

    Parameters
    ----------
    event_log : pandas.DataFrame
        Long-format event log, e.g. the output of `TrialLogger.to_dataframe()`.
    event_pair_list : list of dict
        A list of dictionaries, each containing:

        - ``"label"`` (str): A label for the event pair.
        - ``"first_event"`` (str): The name of the first event.
        - ``"second_event"`` (str): The name of the second event.
    what : str, default="mean"
        The statistic to compute. See `vidigi.analysis.event_durations`'s
        module for the full set. When `across="runs"`, only a genuine
        per-replication statistic is accepted - `"mean"`, `"median"`, `"max"`,
        `"min"`, `"quantile"`, `"std"`, `"var"`, `"sum"` - see
        `vidigi.analysis.replication_means`.
    exclude_incomplete : bool, default=True
        If True, incomplete pairings (where the second event is missing) are
        excluded from the calculation. Must be True when `across="runs"` - a
        missing duration cannot contribute to a per-replication statistic.
    across : {"entities", "runs"}, default="entities"
        Whether each bar is a statistic pooled over every entity (matching every
        prior release), or the mean of a per-replication statistic computed
        separately for each run. `error_bars` and `show_runs` both require
        `across="runs"` - see *Notes*.
    error_bars : {"ci", "sd", "se", "range", "iqr"} or None, default=None
        The spread drawn as an error bar around each bar, computed over the
        per-run values. `"ci"` is a confidence interval at `ci_level` (see
        `vidigi.analysis.mean_confidence_interval` - requires the optional
        `scipy` dependency, `pip install vidigi[stats]`); `"sd"` is the sample
        standard deviation; `"se"` the standard error of the mean; `"range"` and
        `"iqr"` are asymmetric, spanning min-to-max and the 25th-to-75th
        percentile respectively. Requires `across="runs"`.
    ci_level : float, default=0.95
        Confidence level used when `error_bars="ci"`.
    show_runs : bool, default=False
        If True, overlays each replication's individual value as a semi-transparent
        point on top of its bar. Requires `across="runs"`.
    match : {"first", "last", "occurrence"}, default="first"
        How repeated occurrences of the two events are paired. See
        `vidigi.analysis.event_durations`.
    warm_up : float, default=0
        Pairings whose `first_time` is before `warm_up` are excluded from
        every bar. See `vidigi.analysis.event_durations`'s same parameter.
    entity_col_name, time_col_name, event_col_name, run_col_name,
    pathway_col_name : str or None
        Column names forwarded to `vidigi.analysis.event_durations`.
    **kwargs : dict
        Additional keyword arguments passed to `plotly.express.bar` - e.g.
        `title=`, `width=`. This is the one function in `vidigi.plots` where
        `**kwargs` is plotly passthrough rather than column-name passthrough,
        preserved unchanged from every prior release.

    Returns
    -------
    plotly.graph_objects.Figure

    Raises
    ------
    ValueError
        If `across` or `error_bars` is not one of the supported values; if
        `error_bars` or `show_runs=True` is requested without `across="runs"`;
        if `exclude_incomplete=False` is combined with `across="runs"`; or if
        `what` is not a valid per-replication statistic when `across="runs"`.

    Notes
    -----
    `error_bars` requires `across="runs"` by design: an interval computed over
    replication means attached to a bar height pooled over entities would be
    internally inconsistent, since entities within a run are correlated and
    runs are the independent unit - see
    `vidigi.analysis.mean_confidence_interval`'s *Notes*.

    See Also
    --------
    plot_duration_distribution : The full distribution behind one of these bars.
    vidigi.analysis.event_durations : The underlying per-entity durations.
    vidigi.analysis.replication_means : The underlying per-run statistics used by `across="runs"`.

    Examples
    --------
    >>> event_pairs = [
    ...     {"label": "Start to End", "first_event": "start", "second_event": "end"},
    ... ]
    >>> plot_metric_bar(
    ...     trial.to_dataframe(), event_pairs, across="runs", error_bars="ci"
    ... )
    <plotly.graph_objs._figure.Figure>
    """
    if across not in ("entities", "runs"):
        raise ValueError(f"`across` must be 'entities' or 'runs'; got {across!r}.")

    if error_bars is not None and error_bars not in _ERROR_BAR_KINDS:
        raise ValueError(
            f"`error_bars` must be one of {_ERROR_BAR_KINDS} or None; got "
            f"{error_bars!r}."
        )

    if error_bars is not None and across != "runs":
        raise ValueError(
            "`error_bars` requires `across=\"runs\"`. An interval computed over "
            "replication means attached to a bar height pooled over entities "
            "would be internally inconsistent - entities within a run are "
            "correlated, runs are the independent unit. Pass `across=\"runs\"`, "
            "or drop `error_bars` for a plain pooled bar."
        )

    if show_runs and across != "runs":
        raise ValueError(
            "`show_runs=True` requires `across=\"runs\"` - there is one point "
            "per run to overlay only when the bar itself is a statistic "
            "computed across runs."
        )

    if across == "runs" and not exclude_incomplete:
        raise ValueError(
            "`exclude_incomplete=False` is not supported with `across=\"runs\"`: "
            "a per-replication statistic cannot include an incomplete (NaN) "
            "duration. Use `across=\"entities\"` for `exclude_incomplete=False` "
            "semantics."
        )

    run_col = _resolve_run_column(event_log, run_col_name)
    n_runs = event_log[run_col].nunique() if run_col else 1

    rows = []
    run_points = {}

    for event_pair in event_pair_list:
        label = event_pair["label"]
        durations = event_durations(
            event_log,
            event_pair["first_event"],
            event_pair["second_event"],
            match=match,
            warm_up=warm_up,
            entity_col_name=entity_col_name,
            time_col_name=time_col_name,
            event_col_name=event_col_name,
            run_col_name=run_col_name,
            pathway_col_name=pathway_col_name,
        )

        if across == "entities":
            value = _summarise_durations(
                durations["duration"], what, exclude_incomplete, n_runs
            )
            rows.append({"label": label, "value": value})
            continue

        run_values = replication_means(durations, what=what)["value"]
        if run_values.empty:
            raise ValueError(
                f"No complete '{event_pair['first_event']}' -> "
                f"'{event_pair['second_event']}' pairs were found in any run to "
                f"compute a per-replication statistic from."
            )
        value = run_values.mean()
        row = {"label": label, "value": value}
        run_points[label] = run_values.to_numpy()

        if error_bars is not None:
            row["error_plus"], row["error_minus"] = _error_bar_bounds(
                run_values, error_bars, ci_level, value
            )

        rows.append(row)

    results_df = pd.DataFrame(rows)

    bar_kwargs = dict(kwargs)
    if error_bars is not None:
        bar_kwargs["error_y"] = "error_plus"
        bar_kwargs["error_y_minus"] = "error_minus"

    fig = px.bar(results_df, x="label", y="value", **bar_kwargs)

    if show_runs:
        first_label = event_pair_list[0]["label"]
        for label, values_arr in run_points.items():
            fig.add_trace(
                go.Scatter(
                    x=[label] * len(values_arr),
                    y=values_arr,
                    mode="markers",
                    marker=dict(color="black", opacity=0.4, size=6),
                    name="Runs",
                    legendgroup="runs",
                    showlegend=(label == first_label),
                )
            )

    return fig


# What `plot_resource_utilisation` draws as a bar height.
ResourceMetric: TypeAlias = Literal["busy_time", "mean_in_use", "utilisation"]
_RESOURCE_METRICS = ("busy_time", "mean_in_use", "utilisation")


def plot_resource_utilisation(
    event_log: pd.DataFrame,
    *,
    by: ResourceUtilisationBy = "step",
    metric: ResourceMetric = "utilisation",
    error_bars: Optional[ErrorBars] = "ci",
    ci_level: float = 0.95,
    show_runs: bool = True,
    sort_by: Optional[Literal["value"]] = None,
    scenario=None,
    resource_map: Optional[dict] = None,
    event_position_df: Optional[pd.DataFrame] = None,
    resource_capacities: Optional[dict] = None,
    capacity: Optional[Literal["infer"]] = None,
    warm_up: float = 0,
    limit_duration: Optional[float] = None,
    unclosed: UnclosedResourceUse = "censor",
    entity_col_name: str = "entity_id",
    time_col_name: str = "time",
    event_type_col_name: str = "event_type",
    event_col_name: str = "event",
    resource_col_name: str = "resource_id",
    run_col_name: Optional[str] = "auto",
) -> go.Figure:
    """
    Plot a bar chart of resource utilisation, one bar per group, across runs.

    Thin wrapper over `vidigi.analysis.resource_utilisation`: that function
    already returns one row per run per group, so this only takes the mean
    across runs, builds error bars from the same per-run values, and draws
    the figure - no `replication_means` reduction step is needed first.

    Parameters
    ----------
    event_log : pandas.DataFrame
        Long-format event log, e.g. the output of `TrialLogger.to_dataframe()`.
    by : {"step", "resource", "run"}, default="step"
        What each bar summarises. See `vidigi.analysis.resource_utilisation`.
        `by="run"` draws a single bar labelled "All resources".
    metric : {"busy_time", "mean_in_use", "utilisation"}, default="utilisation"
        Which column of `vidigi.analysis.resource_utilisation`'s output is the
        bar height. If `metric="utilisation"` and no capacity was resolved for
        any group (every value `NaN`), this falls back to `"mean_in_use"`
        instead - which needs no capacity - with a warning and a note in the
        title, rather than drawing an all-`NaN` chart.
    error_bars : {"ci", "sd", "se", "range", "iqr"} or None, default="ci"
        The spread drawn as an error bar around each bar, computed over the
        per-run values for that group. See `vidigi.plots.plot_metric_bar` for
        the full explanation of each. `"ci"` requires the optional `scipy`
        dependency (`pip install vidigi[stats]`).
    ci_level : float, default=0.95
        Confidence level used when `error_bars="ci"`.
    show_runs : bool, default=True
        If True, overlays each run's individual value as a semi-transparent
        point on top of its bar.
    sort_by : {"value"} or None, default=None
        If `"value"`, bars are ordered by descending metric value (`NaN` last)
        rather than by group value.
    scenario, resource_map, event_position_df, resource_capacities, capacity :
        Capacity resolution - see `vidigi.analysis._resolve_resource_capacities`
        for the four routes. Unused when `by="resource"`, whose capacity is
        always 1.
    warm_up, limit_duration, unclosed, entity_col_name, time_col_name,
    event_type_col_name, event_col_name, resource_col_name, run_col_name :
        Forwarded to `vidigi.analysis.resource_utilisation`.

    Returns
    -------
    plotly.graph_objects.Figure

    Raises
    ------
    ValueError
        If `by`, `metric`, `error_bars` or `sort_by` is not one of the
        supported values; or if no resource_use/resource_use_end pairs were
        found to plot.

    Notes
    -----
    A dashed line is drawn at y=1.0 when the plotted metric is (or falls back
    to being) `"utilisation"` - a value above it is never valid for this
    definition (mean number busy / capacity) and is diagnostic of a
    mis-resolved capacity or overlapping resource_use intervals.

    See Also
    --------
    vidigi.analysis.resource_utilisation : The underlying per-run, per-group summary.
    plot_resource_utilisation_over_time : The same data, resolved over time instead of per group.

    Examples
    --------
    >>> plot_resource_utilisation(
    ...     trial.to_dataframe(), by="step", resource_capacities={"treatment_begins": 3}
    ... )
    <plotly.graph_objs._figure.Figure>
    """
    if by not in ("step", "resource", "run"):
        raise ValueError(f"`by` must be one of 'step', 'resource', 'run'; got {by!r}.")
    if metric not in _RESOURCE_METRICS:
        raise ValueError(
            f"`metric` must be one of {_RESOURCE_METRICS}; got {metric!r}."
        )
    if error_bars is not None and error_bars not in _ERROR_BAR_KINDS:
        raise ValueError(
            f"`error_bars` must be one of {_ERROR_BAR_KINDS} or None; got "
            f"{error_bars!r}."
        )
    if sort_by is not None and sort_by != "value":
        raise ValueError(f"`sort_by` must be 'value' or None; got {sort_by!r}.")

    results = resource_utilisation(
        event_log,
        by=by,
        scenario=scenario,
        resource_map=resource_map,
        event_position_df=event_position_df,
        resource_capacities=resource_capacities,
        capacity=capacity,
        warm_up=warm_up,
        limit_duration=limit_duration,
        unclosed=unclosed,
        entity_col_name=entity_col_name,
        time_col_name=time_col_name,
        event_type_col_name=event_type_col_name,
        event_col_name=event_col_name,
        resource_col_name=resource_col_name,
        run_col_name=run_col_name,
    )

    if results.empty:
        raise ValueError(
            "No resource_use/resource_use_end pairs were found to plot resource "
            "utilisation from."
        )

    effective_metric = metric
    if metric == "utilisation" and results["utilisation"].isna().all():
        warnings.warn(
            "metric='utilisation' was requested, but no capacity was resolved "
            "for any group - falling back to metric='mean_in_use', which needs "
            "no capacity. Pass resource_capacities=, scenario= with "
            "resource_map= or event_position_df=, or capacity='infer', for an "
            "actual utilisation figure.",
            UserWarning,
            stacklevel=2,
        )
        effective_metric = "mean_in_use"

    group_col = {"step": "event", "resource": "resource_id", "run": None}[by]
    if group_col is None:
        results = results.assign(_group="All resources")
        group_col = "_group"

    labels, values, run_arrays, error_plus, error_minus = [], [], [], [], []
    for group_value, group_df in results.groupby(group_col, dropna=False):
        run_values = group_df[effective_metric]
        value = run_values.mean()
        labels.append(str(group_value))
        values.append(value)
        run_arrays.append(run_values.to_numpy())
        if error_bars is not None:
            plus, minus = _error_bar_bounds(run_values, error_bars, ci_level, value)
        else:
            plus, minus = None, None
        error_plus.append(plus)
        error_minus.append(minus)

    order = list(range(len(labels)))
    if sort_by == "value":
        order.sort(key=lambda i: (pd.isna(values[i]), -values[i] if pd.notna(values[i]) else 0))

    labels = [labels[i] for i in order]
    values = [values[i] for i in order]
    run_arrays = [run_arrays[i] for i in order]
    error_plus = [error_plus[i] for i in order]
    error_minus = [error_minus[i] for i in order]

    fig = go.Figure()
    bar_kwargs = dict(x=labels, y=values, name=effective_metric)
    if error_bars is not None:
        bar_kwargs["error_y"] = dict(type="data", array=error_plus, arrayminus=error_minus)
    fig.add_trace(go.Bar(**bar_kwargs))

    if show_runs:
        for i, (label, run_values) in enumerate(zip(labels, run_arrays)):
            fig.add_trace(
                go.Scatter(
                    x=[label] * len(run_values),
                    y=run_values,
                    mode="markers",
                    marker=dict(color="black", opacity=0.4, size=6),
                    name="Runs",
                    legendgroup="runs",
                    showlegend=(i == 0),
                )
            )

    if effective_metric == "utilisation":
        fig.add_hline(y=1.0, line_dash="dash", line_color="red")

    title = f"Resource {effective_metric} by {by}"
    if effective_metric != metric:
        title += " (capacity unresolved - showing mean_in_use)"
    fig.update_layout(title=title)
    fig.update_xaxes(title_text=by)
    fig.update_yaxes(title_text=effective_metric)

    return fig


def plot_resource_utilisation_over_time(
    event_log: pd.DataFrame,
    *,
    every_x_time_units: float = 1,
    warm_up: float = 0,
    limit_duration: Optional[float] = None,
    as_proportion: bool = False,
    show_all_runs: bool = True,
    shared_y_axis: bool = True,
    scenario=None,
    resource_map: Optional[dict] = None,
    event_position_df: Optional[pd.DataFrame] = None,
    resource_capacities: Optional[dict] = None,
    capacity: Optional[Literal["infer"]] = None,
    entity_col_name: str = "entity_id",
    time_col_name: str = "time",
    event_type_col_name: str = "event_type",
    event_col_name: str = "event",
    resource_col_name: str = "resource_id",
    run_col_name: Optional[str] = "auto",
) -> go.Figure:
    """
    Plot how many units of each resource step were in use over time, across runs.

    Thin wrapper over `vidigi.analysis.resource_occupancy_over_time`: this
    function only takes the per-snapshot mean across runs (when
    `as_proportion=True`, also resolving capacity) and builds the figure.

    Parameters
    ----------
    event_log : pandas.DataFrame
        Long-format event log, e.g. the output of `TrialLogger.to_dataframe()`.
    every_x_time_units : float, default=1
        Time granularity for snapshots.
    warm_up : float, default=0
        Time at which the plotted window begins. See
        `vidigi.analysis.resource_use_intervals`.
    limit_duration : float, optional
        End of the plotted window. `None` (default) uses the latest time seen
        anywhere in the trial.
    as_proportion : bool, default=False
        If True, each step's count is divided by its resolved capacity (see
        `scenario`/`resource_map`/`event_position_df`/`resource_capacities`/
        `capacity` below), so the y-axis is a proportion in use rather than a
        raw count. Requires a capacity to be resolvable for every step
        plotted - unlike `plot_resource_utilisation`, there is no fallback,
        since a partially-`NaN` proportion plot is more misleading than an
        error naming the problem.
    show_all_runs : bool, default=True
        If True, plots every run with semi-transparent lines and overlays the
        mean trajectory. If False, only the mean trajectory is plotted.
    shared_y_axis : bool, default=True
        If True (and more than one step is plotted), every facet shares a
        y-axis range. If False, each is scaled independently.
    scenario, resource_map, event_position_df, resource_capacities, capacity :
        Capacity resolution, used only when `as_proportion=True` - see
        `vidigi.analysis._resolve_resource_capacities` for the four routes.
    entity_col_name, time_col_name, event_type_col_name, event_col_name,
    resource_col_name, run_col_name : str or None
        Column names forwarded to `vidigi.analysis.resource_occupancy_over_time`.

    Returns
    -------
    plotly.graph_objects.Figure

    Raises
    ------
    ValueError
        If no resource_use/resource_use_end pairs were found to plot; or (with
        `as_proportion=True`) if a step being plotted has no resolvable
        capacity.

    Notes
    -----
    Traces use `line_shape="hv"` - occupancy is a step function (a bout is
    occupied on the half-open interval `[start, end)`), and linear
    interpolation between snapshots would draw fractional resource counts that
    never existed.

    See Also
    --------
    vidigi.analysis.resource_occupancy_over_time : The underlying per-run, per-snapshot counts.
    plot_resource_utilisation : The same data pooled per group instead of over time.

    Examples
    --------
    >>> plot_resource_utilisation_over_time(
    ...     trial.to_dataframe(), every_x_time_units=5, limit_duration=500
    ... )
    <plotly.graph_objs._figure.Figure>
    """
    occupancy = resource_occupancy_over_time(
        event_log,
        every_x_time_units=every_x_time_units,
        warm_up=warm_up,
        limit_duration=limit_duration,
        entity_col_name=entity_col_name,
        time_col_name=time_col_name,
        event_type_col_name=event_type_col_name,
        event_col_name=event_col_name,
        resource_col_name=resource_col_name,
        run_col_name=run_col_name,
    )

    if occupancy.empty:
        raise ValueError(
            "No resource_use/resource_use_end pairs were found to plot resource "
            "occupancy from."
        )

    steps = sorted(occupancy["event"].unique().tolist(), key=str)
    y_col, y_title = "count", "count in use"

    if as_proportion:
        intervals = resource_use_intervals(
            event_log,
            unclosed="censor",
            warm_up=warm_up,
            limit_duration=limit_duration,
            entity_col_name=entity_col_name,
            time_col_name=time_col_name,
            event_type_col_name=event_type_col_name,
            event_col_name=event_col_name,
            resource_col_name=resource_col_name,
            run_col_name=run_col_name,
        )
        capacities = _resolve_resource_capacities(
            intervals,
            scenario=scenario,
            resource_map=resource_map,
            event_position_df=event_position_df,
            resource_capacities=resource_capacities,
            capacity=capacity,
            step_col_name="event",
            resource_col_name=resource_col_name,
        )
        missing = [step for step in steps if pd.isna(capacities.get(step))]
        if missing:
            raise ValueError(
                f"`as_proportion=True` needs a resolvable capacity for every "
                f"step being plotted, but {missing} has none. Pass "
                f"resource_capacities=, scenario= with resource_map= or "
                f"event_position_df=, or capacity='infer'."
            )
        occupancy = occupancy.assign(
            proportion=occupancy["count"] / occupancy["event"].map(capacities)
        )
        y_col, y_title = "proportion", "proportion in use"

    mean_df = occupancy.groupby(["snapshot_time", "event"], as_index=False)[y_col].mean()

    n_steps = len(steps)
    if n_steps > 1:
        fig = make_subplots(
            rows=n_steps, cols=1, shared_yaxes=shared_y_axis, subplot_titles=steps
        )
    else:
        fig = go.Figure()

    step_to_row = {step: i + 1 for i, step in enumerate(steps)}

    def _add_trace(trace, step):
        if n_steps > 1:
            fig.add_trace(trace, row=step_to_row[step], col=1)
        else:
            fig.add_trace(trace)

    if show_all_runs:
        run_ids = sorted(occupancy["run_number"].dropna().unique().tolist()) or [pd.NA]
        for run_id in run_ids:
            run_rows = (
                occupancy[occupancy["run_number"] == run_id]
                if pd.notna(run_id)
                else occupancy[occupancy["run_number"].isna()]
            )
            for j, step in enumerate(steps):
                sub = run_rows[run_rows["event"] == step].sort_values("snapshot_time")
                _add_trace(
                    go.Scatter(
                        x=sub["snapshot_time"],
                        y=sub[y_col],
                        mode="lines",
                        line_shape="hv",
                        opacity=0.2,
                        legendgroup=str(run_id),
                        name=str(run_id),
                        showlegend=(j == 0),
                    ),
                    step,
                )

    for step in steps:
        sub = mean_df[mean_df["event"] == step].sort_values("snapshot_time")
        _add_trace(
            go.Scatter(
                x=sub["snapshot_time"],
                y=sub[y_col],
                mode="lines",
                line_shape="hv",
                line=dict(color="black", width=3),
                name="Mean",
                legendgroup="Mean",
                showlegend=(step == steps[0]),
            ),
            step,
        )

    fig.update_xaxes(title_text="snapshot_time")
    fig.update_yaxes(title_text=y_title)

    return fig


def plot_warm_up_diagnostic(
    event_log: pd.DataFrame,
    *,
    series: Literal["queue", "occupancy", "duration"] = "queue",
    event: Optional[str] = None,
    first_event: Optional[str] = None,
    second_event: Optional[str] = None,
    method: WarmUpMethod = "welch",
    windows: Sequence[int] = (5, 10, 20),
    every_x_time_units: float = 1,
    limit_duration: Optional[float] = None,
    show_ensemble: bool = True,
    show_runs: bool = False,
    **col_kwargs,
) -> go.Figure:
    """
    Plot a Welch (or cumulative-mean) diagnostic for choosing `warm_up=`.

    Ensemble-averages a per-run series across replications, then smooths it
    (see `vidigi.analysis.welch_moving_average`) so the point at which the
    curve stops drifting - the visual signal a modeller reads off to pick
    `warm_up=` for the other analysis functions in this module - is legible.

    Parameters
    ----------
    event_log : pandas.DataFrame
        Long-format event log spanning one or more runs.
    series : {"queue", "occupancy", "duration"}, default="queue"
        What per-run series to diagnose:

        - ``"queue"``: queue length at regular snapshots, from
          `vidigi.analysis.queue_size_over_time`. Requires `event=` naming
          the queue's event.
        - ``"occupancy"``: resource occupancy at regular snapshots, from
          `vidigi.analysis.resource_occupancy_over_time`. Requires `event=`
          naming the resource step.
        - ``"duration"``: per-entity durations in arrival order, from
          `vidigi.analysis.event_durations`. Requires `first_event=` and
          `second_event=`. There is no time axis for this series - the
          x-axis is the entity's position in arrival order, not simulated
          time, so a cutoff read off this plot is an entity count, not a
          time. Apply it via `event_durations`'s own `warm_up=` (a pairing
          is excluded by when it *started*, i.e. `first_time`) - note this
          is a genuinely different truncation rule from `warm_up=` on the
          other two series, which censor/clip a bout rather than exclude an
          atomic observation by its start time. See
          `vidigi.analysis.event_durations`'s `warm_up` parameter.
    event : str, optional
        The queue's or resource step's event name. Required, and only used,
        for `series="queue"`/`"occupancy"`.
    first_event, second_event : str, optional
        The two events to pair. Required, and only used, for
        `series="duration"`.
    method : {"welch", "cumulative", "none"}, default="welch"
        Smoothing procedure - see `vidigi.analysis.welch_moving_average`.
        `"welch"` overlays one curve per entry in `windows`; `"cumulative"`
        and `"none"` each draw a single curve and ignore `windows`.
        `"cumulative"` is the "time series inspection" technique the DES RAP
        book demonstrates (Heather et al., 2026 -
        https://pythonhealthdatascience.github.io/des_rap_book/pages/guide/output_analysis/length_warmup.html);
        `"none"` is the raw ensemble average with no smoothing at all - a
        further step beyond that, not itself what the DES RAP book shows.
        `"none"` is drawn the same way `show_ensemble`'s reference line
        would be, so `show_ensemble` is a no-op under it to avoid drawing
        the identical line twice.
    windows : sequence of int, default=(5, 10, 20)
        Window half-widths to overlay when `method="welch"`. More smoothing
        (a larger window) gives a shorter usable curve - see
        `vidigi.analysis.welch_moving_average`.
    every_x_time_units : float, default=1
        Snapshot granularity. Only used for `series="queue"`/`"occupancy"`.
    limit_duration : float, optional
        End of the window snapshots are taken over. `None` (default) uses
        the latest time seen anywhere in the trial. Only used for
        `series="queue"`/`"occupancy"`.
    show_ensemble : bool, default=True
        If True, also draws the raw (unsmoothed) ensemble-average series as
        a thin dotted line, for comparison against the smoothed curve(s).
        Ignored when `method="none"` - see `method` above.
    show_runs : bool, default=False
        If True, also draws every individual replication's own raw series -
        the same idea as the DES RAP book's own per-replication traces
        (though those plot each run's *cumulative* mean, matching
        `method="cumulative"` above, rather than the fully raw series drawn
        here), and useful with any `method` for seeing how much
        cross-replication spread the smoothing/pooling is hiding.
        Drawn at `opacity=0.2` under one shared legend entry ("individual
        runs") rather than one entry per run, since with a realistic
        replication count a full per-run legend would swamp the `windows=`/
        `method` entries that are the actual point of this plot - unlike
        `plot_queue_size`/`plot_resource_utilisation_over_time`, which plot
        one series at a time and so can afford to label each run. Drawn at
        each run's own full length, not truncated to the shortest run the
        way the summary trace(s) are.
    **col_kwargs : dict
        Column-name keyword arguments forwarded to whichever underlying
        `vidigi.analysis` function `series` selects
        (`queue_size_over_time`/`resource_occupancy_over_time`/
        `event_durations`) - e.g. `run_col_name=`, or `match=` for
        `series="duration"`.

    Returns
    -------
    plotly.graph_objects.Figure

    Raises
    ------
    ValueError
        If `series` is not one of the three supported values; if the
        `event=` (for `series="queue"`/`"occupancy"`) or
        `first_event=`/`second_event=` (for `series="duration"`) the chosen
        `series` requires is missing, or an argument for a different
        `series` is given; or (`series="occupancy"`) if `event` names a step
        that never occurred.

    Notes
    -----
    There is deliberately no automatic warm-up-length selector - see
    `vidigi.analysis.welch_moving_average`.

    See Also
    --------
    vidigi.analysis.welch_moving_average : The underlying smoothing procedure.

    Examples
    --------
    >>> plot_warm_up_diagnostic(trial.to_dataframe(), series="queue", event="waiting")
    <plotly.graph_objs._figure.Figure>
    """
    if series not in ("queue", "occupancy", "duration"):
        raise ValueError(
            f"`series` must be one of 'queue', 'occupancy', 'duration'; got "
            f"{series!r}."
        )

    if series in ("queue", "occupancy"):
        if event is None:
            raise ValueError(
                f"`series={series!r}` requires `event=` naming the "
                f"{'queue' if series == 'queue' else 'resource step'} to "
                f"diagnose."
            )
        if first_event is not None or second_event is not None:
            raise ValueError(
                f"`first_event`/`second_event` are only used with "
                f"`series='duration'`, not `series={series!r}`."
            )
    else:
        if first_event is None or second_event is None:
            raise ValueError(
                "`series='duration'` requires both `first_event=` and "
                "`second_event=`."
            )
        if event is not None:
            raise ValueError(
                "`event=` is only used with `series='queue'`/`'occupancy'`, "
                "not `series='duration'`."
            )

    x_title = "snapshot_time"
    x_values = None

    if series == "queue":
        time_col_name = col_kwargs.get("time_col_name", "time")
        resolved_limit = (
            limit_duration
            if limit_duration is not None
            # `int(round(...))`, not the bare numpy scalar `.max()` returns -
            # `queue_size_over_time` warns whenever it has to coerce a
            # non-`int` `limit_duration`, and an auto-resolved end of window
            # doing that on every call with no explicit `limit_duration`
            # would be a self-inflicted, uninformative warning.
            else int(round(event_log[time_col_name].max()))
        )
        counts = queue_size_over_time(
            event_log,
            [event],
            resolved_limit,
            every_x_time_units=every_x_time_units,
            warm_up=0,
            **col_kwargs,
        )
        run_ids = sorted(counts["run_number"].dropna().unique().tolist()) or [pd.NA]

        def _run_rows(run_id):
            frame = (
                counts[counts["run_number"] == run_id]
                if pd.notna(run_id)
                else counts[counts["run_number"].isna()]
            )
            return frame.sort_values("snapshot_time")

        series_by_run = [_run_rows(r)["count"].to_numpy() for r in run_ids]
        x_values = _run_rows(run_ids[0])["snapshot_time"].to_numpy()
        y_title = f"queue length ({event})"

    elif series == "occupancy":
        occupancy = resource_occupancy_over_time(
            event_log,
            every_x_time_units=every_x_time_units,
            warm_up=0,
            limit_duration=limit_duration,
            **col_kwargs,
        )
        if occupancy.empty:
            raise ValueError(
                "No resource_use/resource_use_end pairs were found to "
                "diagnose resource occupancy from."
            )
        available = sorted(occupancy["event"].unique().tolist(), key=str)
        if event not in available:
            raise ValueError(
                f"`event='{event}'` is not a resource step in this event "
                f"log{_nearest_match_hint(event, available)}. Available "
                f"steps: {available}."
            )
        occupancy = occupancy[occupancy["event"] == event]
        run_ids = sorted(occupancy["run_number"].dropna().unique().tolist()) or [
            pd.NA
        ]

        def _run_rows(run_id):
            frame = (
                occupancy[occupancy["run_number"] == run_id]
                if pd.notna(run_id)
                else occupancy[occupancy["run_number"].isna()]
            )
            return frame.sort_values("snapshot_time")

        series_by_run = [_run_rows(r)["count"].to_numpy() for r in run_ids]
        x_values = _run_rows(run_ids[0])["snapshot_time"].to_numpy()
        y_title = f"occupancy ({event})"

    else:
        durations = event_durations(
            event_log, first_event, second_event, keep_incomplete=False, **col_kwargs
        )
        run_ids = sorted(durations["run_number"].dropna().unique().tolist()) or [
            pd.NA
        ]

        def _run_rows(run_id):
            frame = (
                durations[durations["run_number"] == run_id]
                if pd.notna(run_id)
                else durations[durations["run_number"].isna()]
            )
            return frame.sort_values("first_time")

        series_by_run = [_run_rows(r)["duration"].to_numpy() for r in run_ids]
        x_title = "nth entity (arrival order)"
        y_title = f"duration ({first_event} -> {second_event})"

    full_x_values = x_values

    m, ensemble_mean, trimmed = _ensemble_mean(series_by_run)
    x_values = np.arange(1, m + 1) if x_values is None else x_values[:m]

    fig = go.Figure()

    if show_runs:
        for j, run_series in enumerate(series_by_run):
            run_x = (
                np.arange(1, len(run_series) + 1)
                if full_x_values is None
                else full_x_values[: len(run_series)]
            )
            fig.add_trace(
                go.Scatter(
                    x=run_x,
                    y=run_series,
                    mode="lines",
                    line=dict(width=1),
                    opacity=0.2,
                    legendgroup="individual runs",
                    name="individual runs",
                    showlegend=(j == 0),
                )
            )

    if show_ensemble and method != "none":
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=ensemble_mean,
                mode="lines",
                line=dict(color="grey", dash="dot", width=1),
                opacity=0.6,
                name="ensemble mean",
            )
        )

    if method == "none":
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=ensemble_mean,
                mode="lines",
                line=dict(width=3),
                name="ensemble mean (unsmoothed)",
            )
        )
    elif method == "cumulative":
        cumulative = welch_moving_average(trimmed, method="cumulative")
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=cumulative,
                mode="lines",
                line=dict(width=3),
                name="cumulative mean",
            )
        )
    else:
        for w in windows:
            smoothed = welch_moving_average(trimmed, window=w, method="welch")
            fig.add_trace(
                go.Scatter(
                    x=x_values[: len(smoothed)],
                    y=smoothed,
                    mode="lines",
                    line=dict(width=3),
                    name=f"window={w}",
                )
            )

    fig.update_xaxes(title_text=x_title)
    fig.update_yaxes(title_text=y_title)

    return fig


def plot_replication_analysis(
    event_log: pd.DataFrame,
    first_event: str,
    second_event: str,
    *,
    what: DurationStat = "mean",
    ci_level: float = 0.95,
    deviation_threshold: float = 0.05,
    show_deviation: bool = True,
    match: MatchMode = "first",
    **col_kwargs,
) -> go.Figure:
    """
    Plot cumulative-mean precision against replication count.

    Ensemble-averages `vidigi.analysis.replication_precision`'s running
    confidence interval into a chart: the cumulative mean and its CI band as
    replications accumulate, plus (optionally) the relative half-width
    (`deviation`) underneath - the diagnostic a modeller reads to decide "how
    many replications is enough" for one event-pair metric, the counterpart
    to `plot_warm_up_diagnostic` for "how much warm-up to discard."

    Parameters
    ----------
    event_log : pandas.DataFrame
        Long-format event log spanning one or more runs.
    first_event, second_event : str
        The two events to pair - see `vidigi.analysis.event_durations`.
    what : str, default="mean"
        The per-replication statistic to compute - see
        `vidigi.analysis.replication_means`.
    ci_level : float, default=0.95
        Confidence level for each cumulative interval.
    deviation_threshold : float, default=0.05
        Relative half-width threshold drawn as a dashed reference line on the
        deviation panel, and used to compute the recommended replication
        count annotated there - see
        `vidigi.analysis.replication_precision`'s `stays_below_threshold`.
    show_deviation : bool, default=True
        If True, draws the relative half-width (`deviation`) in a second
        panel stacked below the mean+CI panel, sharing the same x-axis. If
        False, only the mean+CI panel is drawn.
    match : {"first", "last", "occurrence"}, default="first"
        How repeated occurrences of the two events are paired. See
        `vidigi.analysis.event_durations`.
    **col_kwargs : dict
        Column-name keyword arguments forwarded to
        `vidigi.analysis.event_durations`, e.g. `run_col_name=`.

    Returns
    -------
    plotly.graph_objects.Figure

    Raises
    ------
    ValueError
        If no complete pairs are found in any run, or fewer than 2
        replications have a complete pair.
    ImportError
        If `scipy` is not installed - see
        `vidigi.analysis.mean_confidence_interval`.

    Notes
    -----
    Replications are read in `run_number` order - the same deterministic
    ordering `vidigi.analysis.replication_precision` requires - since a
    cumulative diagnostic only means "as replications accumulate" walked
    through in the order they were actually generated.

    See Also
    --------
    vidigi.analysis.replication_precision : The underlying per-k table.
    plot_warm_up_diagnostic : The companion diagnostic for choosing `warm_up=`.

    Examples
    --------
    >>> plot_replication_analysis(trial.to_dataframe(), "start", "end")
    <plotly.graph_objs._figure.Figure>
    """
    durations = event_durations(
        event_log, first_event, second_event, match=match, keep_incomplete=False, **col_kwargs
    )
    run_values = replication_means(durations, what=what)["value"]
    if run_values.empty:
        raise ValueError(
            f"No complete '{first_event}' -> '{second_event}' pairs were found "
            f"in any run to compute a per-replication statistic from."
        )
    if len(run_values) < 2:
        raise ValueError(
            f"Replication analysis needs at least 2 replications with a "
            f"complete '{first_event}' -> '{second_event}' pair; got "
            f"{len(run_values)}."
        )

    precision = replication_precision(
        run_values, ci_level=ci_level, deviation_threshold=deviation_threshold
    )
    recommended = precision.loc[precision["stays_below_threshold"], "n_replications"]
    recommended_n = int(recommended.min()) if not recommended.empty else None

    x = precision["n_replications"]

    if show_deviation:
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            row_heights=[0.65, 0.35],
            vertical_spacing=0.08,
            subplot_titles=(
                f"cumulative mean ({first_event} -> {second_event})",
                "relative half-width (deviation)",
            ),
        )
    else:
        fig = go.Figure()

    def _add_trace(trace, row):
        if show_deviation:
            fig.add_trace(trace, row=row, col=1)
        else:
            fig.add_trace(trace)

    _add_trace(
        go.Scatter(
            x=pd.concat([x, x[::-1]]),
            y=pd.concat([precision["upper"], precision["lower"][::-1]]),
            fill="toself",
            fillcolor="rgba(0,100,200,0.15)",
            line=dict(width=0),
            hoverinfo="skip",
            name=f"{int(ci_level * 100)}% CI",
        ),
        row=1,
    )
    _add_trace(
        go.Scatter(
            x=x,
            y=precision["cumulative_mean"],
            mode="lines+markers",
            line=dict(width=3),
            name="cumulative mean",
        ),
        row=1,
    )

    if show_deviation:
        _add_trace(
            go.Scatter(
                x=x,
                y=precision["deviation"],
                mode="lines+markers",
                line=dict(width=3, color="black"),
                name="deviation",
                showlegend=False,
            ),
            row=2,
        )
        fig.add_hline(
            y=deviation_threshold,
            line_dash="dash",
            line_color="red",
            row=2,
            col=1,
            annotation_text=f"threshold={deviation_threshold}",
            annotation_position="top left",
        )
        fig.update_yaxes(title_text="deviation", row=2, col=1)
        fig.update_xaxes(title_text="n replications", row=2, col=1)
    else:
        fig.update_xaxes(title_text="n replications")

    if show_deviation:
        fig.update_yaxes(title_text="cumulative mean", row=1, col=1)
    else:
        fig.update_yaxes(title_text="cumulative mean")

    subtitle = (
        f"recommended: {recommended_n} replications (deviation stays below "
        f"{deviation_threshold})"
        if recommended_n is not None
        else f"deviation never stays below {deviation_threshold} within the "
        f"{len(run_values)} replications available"
    )
    fig.update_layout(title=subtitle)

    return fig
