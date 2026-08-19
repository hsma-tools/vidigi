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
from typing import Literal, Optional, TypeAlias, Union

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from vidigi.analysis import (
    DurationStat,
    MatchMode,
    _summarise_durations,
    event_durations,
    mean_confidence_interval,
    queue_size_over_time,
    replication_means,
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
        `run_col_name`).

    Returns
    -------
    plotly.graph_objects.Figure

    Raises
    ------
    ValueError
        If `kind` or `split_by` is not one of the supported values; if `kind`
        is `"ridgeline"` or `"heatmap"` and `split_by` is not set; if no
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

# Which spread `plot_metric_bar` draws as an error bar around a bar computed
# `across="runs"`.
ErrorBars: TypeAlias = Literal["ci", "sd", "se", "range", "iqr"]
_ERROR_BAR_KINDS = ("ci", "sd", "se", "range", "iqr")


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

        if error_bars == "ci":
            ci = mean_confidence_interval(run_values, ci_level=ci_level)
            row["error_plus"] = ci.half_width
            row["error_minus"] = ci.half_width
        elif error_bars == "sd":
            sd = run_values.std(ddof=1)
            row["error_plus"] = sd
            row["error_minus"] = sd
        elif error_bars == "se":
            se = run_values.std(ddof=1) / (len(run_values) ** 0.5)
            row["error_plus"] = se
            row["error_minus"] = se
        elif error_bars == "range":
            row["error_plus"] = run_values.max() - value
            row["error_minus"] = value - run_values.min()
        elif error_bars == "iqr":
            q1, q3 = run_values.quantile([0.25, 0.75])
            row["error_plus"] = q3 - value
            row["error_minus"] = value - q1

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
