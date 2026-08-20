from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
    ValidationInfo,
)
from typing import Optional, Any, List, ClassVar, Set, Literal, TypeAlias
import json
import pandas as pd
from pathlib import Path
from io import TextIOBase
from datetime import datetime
import plotly.express as px
import warnings
from vidigi.process_mapping import (
    discover_dfg,
    add_sim_timestamp,
    dfg_to_graphviz,
    dfg_to_cytoscape,
    dfg_to_cytoscape_streamlit,
)
from vidigi.analysis import (
    DurationStat,
    MatchMode,
    ResourceUtilisationBy,
    UnclosedResourceUse,
    _summarise_durations,
    event_durations,
    resource_utilisation,
)
from vidigi.plots import (
    plot_queue_size as _plot_queue_size,
    plot_duration_distribution as _plot_duration_distribution,
    plot_metric_bar as _plot_metric_bar,
    plot_resource_utilisation as _plot_resource_utilisation,
    plot_resource_utilisation_over_time as _plot_resource_utilisation_over_time,
    Across,
    DistributionKind,
    ErrorBars,
    PlotBackend,
    ResourceMetric,
    SplitBy,
)

RECOGNIZED_EVENT_TYPES = {
    "arrival_departure",
    "resource_use",
    "resource_use_end",
    "queue",
}


DFGType: TypeAlias = Literal[
    "graphviz-object", "graphviz-image", "cytoscape-jupyter", "cytoscape-streamlit"
]


class BaseEvent(BaseModel):
    _warned_unrecognized_event_types: ClassVar[Set[str]] = set()

    entity_id: Any = Field(
        ...,
        description="Identifier for the entity related to this event (e.g. patient ID, customer ID). Can be any type.",
    )

    event_type: str = Field(
        ...,
        description=f"Type of event. Recommended values: {', '.join(RECOGNIZED_EVENT_TYPES)}",
    )

    event: str = Field(..., description="Name of the specific event.")

    time: float = Field(..., description="Simulation time or timestamp of event.")

    # Optional commonly-used fields
    pathway: Optional[str] = None

    run_number: Optional[int] = Field(
        default=None,
        description="A numeric value identifying the simulation run this record is associated with.",
    )

    timestamp: Optional[datetime] = Field(
        default=None,
        description="Real-world timestamp of the event, if available.",
    )

    resource_id: Optional[int] = Field(
        None,
        description="ID of the resource involved (required for resource use events).",
        # Without this, pydantic skips the field's validators when the caller omits it,
        # so the "resource_id is recommended" check below could never fire in the one
        # case it exists to catch.
        validate_default=True,
    )

    # Allow arbitrary extra fields
    model_config = {"extra": "allow"}

    @field_validator("event_type", mode="before")
    @classmethod
    def warn_if_unrecognized_event_type(cls, v: str, info: ValidationInfo):
        """
        Warns if the event_type is not in the set of recognized types.

        A warning for each unrecognized type is issued only once.
        """
        # Skip check if context flag is set
        if info.context and info.context.get("skip_event_type_check"):
            return v

        if (
            v not in RECOGNIZED_EVENT_TYPES
            and v not in cls._warned_unrecognized_event_types
        ):
            warnings.warn(
                f"Unrecognized event_type '{v}'. Recommended values are: {', '.join(RECOGNIZED_EVENT_TYPES)}.",
                UserWarning,
                stacklevel=4,
            )
            cls._warned_unrecognized_event_types.add(v)
        return v

    @field_validator("resource_id", mode="before")
    @classmethod
    def warn_if_missing_resource_id(cls, v, info: ValidationInfo):
        etype = info.data.get("event_type")  # <-- access validated fields here
        if etype in ("resource_use", "resource_use_end"):
            if v is None:
                warnings.warn(
                    f"resource_id is recommended for event_type '{etype}', but was not provided.",
                    UserWarning,
                    stacklevel=3,
                )
            elif not isinstance(v, int):
                warnings.warn(
                    "resource_id should be an integer, but received type "
                    f"{type(v).__name__}.",
                    UserWarning,
                    stacklevel=3,
                )
        return v

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, value):
        if value is None or isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
        # Try other common formats
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        raise ValueError(
            f'Unrecognized or ambiguous datetime format for timestamp: {value}. Please use a year-first format such as "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", or "%Y-%m-%d".'
        )

    @model_validator(mode="after")
    def validate_event_logic(self) -> "BaseEvent":
        """
        Enforce constraints between event_type and event.
        """
        if self.event_type == "arrival_departure":
            if self.event not in ["arrival", "depart"]:
                raise ValueError(
                    f"When event_type is 'arrival_departure', event must be 'arrival' or 'depart'. Got '{self.event}'."
                )
        # Here we could add more logic if desired

        return self


class EventLogger:
    def __init__(self, event_model=BaseEvent, env: Any = None, run_number: int = None):
        self.event_model = event_model
        self.env = env  # Optional simulation env with .now
        self.run_number = run_number
        self._log: List[dict] = []

    def log_event(self, context: Optional[dict] = None, **event_data):
        if "time" not in event_data:
            if self.env is not None and hasattr(self.env, "now"):
                now_attr = self.env.now
                event_data["time"] = (
                    now_attr() if callable(now_attr) else now_attr
                )
            else:
                raise ValueError(
                    "Missing 'time' and no simulation environment provided."
                )

        if "run_number" not in event_data:
            if self.run_number is not None:
                event_data["run_number"] = self.run_number

        try:
            event = self.event_model.model_validate(event_data, context=context or {})
        except Exception as e:
            raise ValueError(f"Invalid event data: {e}")

        self._log.append(event.model_dump())

    #################################################################
    # Logging Helper Functions                                      #
    #################################################################

    def log_arrival(
        self,
        *,
        entity_id: Any,
        time: Optional[float] = None,
        pathway: Optional[str] = None,
        run_number: Optional[int] = None,
        **extra_fields,
    ):
        """
        Helper to log an arrival event with the correct event_type and event fields.
        """
        event_data = {
            "entity_id": entity_id,
            "event_type": "arrival_departure",
            "event": "arrival",
            "time": time,
            "pathway": pathway,
            "run_number": run_number,
        }
        event_data.update(extra_fields)
        self.log_event(**{k: v for k, v in event_data.items() if v is not None})

    def log_departure(
        self,
        *,
        entity_id: Any,
        time: Optional[float] = None,
        pathway: Optional[str] = None,
        run_number: Optional[int] = None,
        **extra_fields,
    ):
        """
        Helper to log a departure event with the correct event_type and event fields.
        """
        event_data = {
            "entity_id": entity_id,
            "event_type": "arrival_departure",
            "event": "depart",
            "time": time,
            "pathway": pathway,
            "run_number": run_number,
        }
        event_data.update(extra_fields)
        self.log_event(**{k: v for k, v in event_data.items() if v is not None})

    def log_queue(
        self,
        *,
        entity_id: Any,
        event: str,
        time: Optional[float] = None,
        pathway: Optional[str] = None,
        run_number: Optional[int] = None,
        **extra_fields,
    ):
        """
        Log a queue event. The 'event' here can be any string describing the queue event.
        """
        event_data = {
            "entity_id": entity_id,
            "event_type": "queue",
            "event": event,
            "time": time,
            "pathway": pathway,
            "run_number": run_number,
        }
        event_data.update(extra_fields)
        self.log_event(**{k: v for k, v in event_data.items() if v is not None})

    def log_resource_use_start(
        self,
        *,
        entity_id: Any,
        resource_id: int,
        event: str = "start",
        time: Optional[float] = None,
        pathway: Optional[str] = None,
        run_number: Optional[int] = None,
        **extra_fields,
    ):
        """
        Log the start of resource use. Requires resource_id.

        Parameters
        ----------
        event : str, default="start"
            Name of the specific step, e.g. `"treatment_begins"`. The default
            of `"start"` is fine for a model with only one resource-use step;
            with more than one, a distinct name per step is what lets
            `vidigi.analysis.resource_use_intervals`/`resource_utilisation`
            report them separately rather than pooling every resource
            together under one name.

        Notes
        -----
        This was already possible by passing `event=...` as an extra keyword
        argument - it silently overrode the literal `"start"` above, since
        `**extra_fields` is applied last. `event` is now an explicit,
        documented parameter instead; behaviour for existing callers is
        unchanged either way.
        """
        event_data = {
            "entity_id": entity_id,
            "event_type": "resource_use",
            "event": event,
            "time": time,
            "resource_id": resource_id,
            "pathway": pathway,
            "run_number": run_number,
        }
        event_data.update(extra_fields)
        self.log_event(**{k: v for k, v in event_data.items() if v is not None})

    def log_resource_use_end(
        self,
        *,
        entity_id: Any,
        resource_id: int,
        event: str = "end",
        time: Optional[float] = None,
        pathway: Optional[str] = None,
        run_number: Optional[int] = None,
        **extra_fields,
    ):
        """
        Log the end of resource use. Requires resource_id.

        Parameters
        ----------
        event : str, default="end"
            Name of the specific step, e.g. `"treatment_ends"`. Only used as a
            label by `vidigi.analysis.resource_use_intervals` - grouping uses
            the matching `log_resource_use_start` call's `event` instead - but
            still worth naming distinctly for readability.

        Notes
        -----
        This was already possible by passing `event=...` as an extra keyword
        argument - it silently overrode the literal `"end"` above, since
        `**extra_fields` is applied last. `event` is now an explicit,
        documented parameter instead; behaviour for existing callers is
        unchanged either way.
        """
        event_data = {
            "entity_id": entity_id,
            "event_type": "resource_use_end",
            "event": event,
            "time": time,
            "resource_id": resource_id,
            "pathway": pathway,
            "run_number": run_number,
        }
        event_data.update(extra_fields)
        self.log_event(**{k: v for k, v in event_data.items() if v is not None})

    def log_custom_event(
        self,
        *,
        entity_id: Any,
        event_type: str,
        event: str,
        time: Optional[float] = None,
        pathway: Optional[str] = None,
        run_number: Optional[int] = None,
        **extra_fields,
    ):
        """
        Log a custom event. The 'event' here can be any string describing the queue event.
        An 'event_type' must also be passed, but can be any string of the user's choosing.
        """
        event_data = {
            "entity_id": entity_id,
            "event_type": event_type,
            "event": event,
            "time": time,
            "pathway": pathway,
            "run_number": run_number,
        }
        event_data.update(extra_fields)
        self.log_event(
            **{k: v for k, v in event_data.items() if v is not None},
            context={"skip_event_type_check": True},
        )

    ####################################################
    # Accessing and exporting the resulting logs       #
    ####################################################

    @property
    def log(self):
        return self._log

    def get_log(self) -> List[dict]:
        return self._log

    def to_json_string(self, indent: int = 2) -> str:
        """Return the event log as a pretty JSON string."""
        return json.dumps(self._log, indent=indent)

    def to_json(self, path_or_buffer: str | Path | TextIOBase, indent: int = 2) -> None:
        """Write the event log to a JSON file or file-like buffer."""
        if not self._log:
            raise ValueError("Event log is empty.")
        json_str = self.to_json_string(indent=indent)

        if isinstance(path_or_buffer, (str, Path)):
            with open(path_or_buffer, "w", encoding="utf-8") as f:
                f.write(json_str)
        else:
            # Assume it's a writable file-like object
            path_or_buffer.write(json_str)

    def to_csv(self, path_or_buffer: str | Path | TextIOBase) -> None:
        """Write the log to a CSV file."""
        if not self._log:
            raise ValueError("Event log is empty.")

        df = self.to_dataframe().dropna(axis=1, how="all")
        df.to_csv(path_or_buffer, index=False)

    def to_dataframe(self) -> pd.DataFrame:
        """Convert the event log to a pandas DataFrame."""
        return pd.DataFrame(self._log).dropna(axis=1, how="all")

    ####################################################
    # Creating a log from an existing dataframe        #
    ####################################################

    def from_csv(
        self,
        df: pd.DataFrame,
        entity_col_name: str = "entity_id",
        time_col_name: str = "time",
        event_col_name: str = "event",
        event_type_col_name: str = "event_type",
        run_col_name: Optional[str] = None,
        pathway_col_name: Optional[str] = None,
    ):
        df = df.rename(
            columns={
                entity_col_name: "entity_id",
                time_col_name: "time",
                event_col_name: "event",
                event_type_col_name: "event_type",
            }
        )

        if run_col_name is not None:
            df = df.rename(columns={run_col_name: "run_number"})

        if pathway_col_name is not None:
            df = df.rename(columns={pathway_col_name: "pathway"})

        # `_log` is a list of records everywhere else. Assigning the DataFrame itself
        # left the logger in a state where iteration walked column names, truthiness
        # checks raised, and JSON export failed.
        self._log = df.to_dict("records")

    ####################################################
    # Summarising Logs                                 #
    ####################################################

    def summary(self) -> dict:
        if not self._log:
            return {"total_events": 0}
        df = self.to_dataframe()
        return {
            "total_events": len(df),
            "event_types": df["event_type"].value_counts().to_dict(),
            "time_range": (df["time"].min(), df["time"].max()),
            "unique_entities": (
                df["entity_id"].nunique() if "entity_id" in df else None
            ),
        }

    ####################################################
    # Accessing certain elements of logs               #
    ####################################################

    def get_events_by_run(self, run_number: Any, as_dataframe: bool = True):
        """Return all events associated with a specific entity_id."""
        filtered = [
            event for event in self._log if event.get("run_number") == run_number
        ]
        return pd.DataFrame(filtered) if as_dataframe else filtered

    def get_events_by_entity(self, entity_id: Any, as_dataframe: bool = True):
        """Return all events associated with a specific entity_id."""
        filtered = [event for event in self._log if event.get("entity_id") == entity_id]
        return pd.DataFrame(filtered) if as_dataframe else filtered

    def get_events_by_event_type(self, event_type: str, as_dataframe: bool = True):
        """Return all events of a specific event_type."""
        filtered = [
            event for event in self._log if event.get("event_type") == event_type
        ]
        return pd.DataFrame(filtered) if as_dataframe else filtered

    def get_events_by_event_name(self, event_name: str, as_dataframe: bool = True):
        """Return all events of a specific event_type."""
        filtered = [event for event in self._log if event.get("event") == event_name]
        return pd.DataFrame(filtered) if as_dataframe else filtered

    ####################################################
    # Plotting from logs                               #
    ####################################################

    def plot_entity_timeline(
        self,
        entity_id: any,
        split_by_entity_type: bool = False,
        show_labels: bool = False,
    ):
        """
        Plot a timeline of events for a given entity.

        This method visualizes the sequence of events for a specified entity
        from the event log as a scatter plot. The timeline is plotted using
        Plotly, with events displayed along the time axis. Events can be
        split vertically by their type or shown by event labels. Optionally,
        labels can be displayed directly on the plot.

        Parameters
        ----------
        entity_id : any
            Identifier of the entity whose events should be plotted.
        split_by_entity_type : bool, default=False
            If True, the y-axis shows event types to separate events vertically.
            If False, the y-axis shows the event labels.
        show_labels : bool, default=False
            If True, the event labels are displayed as text on the plot.
            If False, no labels are shown.

        Raises
        ------
        ValueError
            If the event log is empty.
        ValueError
            If no events are found for the given ``entity_id``.

        See Also
        --------
        to_dataframe : Convert the event log into a DataFrame for analysis.

        Notes
        -----
        - The plot is displayed using `plotly.express.scatter`.
        - The y-axis is treated as categorical to improve readability.
        - Marker styling includes a fixed size and outline color for clarity.
        """
        if not self._log:
            raise ValueError("Event log is empty.")

        df = self.to_dataframe()
        entity_events = df[df["entity_id"] == entity_id]

        if entity_events.empty:
            raise ValueError(f"No events found for entity_id = {entity_id}")

        # Sort by time for timeline plot
        entity_events = entity_events.sort_values("time")

        if not show_labels:
            text_label = None
        else:
            text_label = "event"

        if split_by_entity_type:
            fig = px.scatter(
                entity_events,
                x="time",
                y="event_type",  # y axis can show event_type to separate events vertically
                color="event_type",
                hover_data=["event", "run_number"],
                labels={"time": "Time", "event_type": "Event Type"},
                title=f"Timeline of Events for Entity {entity_id}",
                text=text_label,
            )
        else:
            fig = px.scatter(
                entity_events,
                x="time",
                y="event",  # y axis can show event_type to separate events vertically
                color="event_type",
                hover_data=["event", "run_number"],
                labels={"time": "Time", "event_type": "Event Type"},
                title=f"Timeline of Events for Entity {entity_id}",
                text=text_label,
            )

        # Optional: jitter y axis for better visualization if multiple events at same time
        fig.update_traces(
            marker=dict(size=10, line=dict(width=1, color="DarkSlateGrey"))
        )

        fig.update_yaxes(type="category")  # treat event_type as categorical on y-axis

        fig.show()

    def generate_dfg(
        self,
        output_format: DFGType = "graphviz-object",
        input_time_format="minutes",
        warm_up: Optional[float] = None,
        **kwargs,
    ):
        """
        Generate a Directly-Follows Graph (DFG) from the simulation data.

        This method converts the object to a dataframe, appends simulation
        timestamps, discovers transitions between activities, and renders
        the result using the specified visualization backend.



        Parameters
        ----------
        output_format : DFGType, optional
            The format of the returned graph. Supported values are:
            - "graphviz-object": Returns a Graphviz object for rendering.
            - "graphviz-image": Returns a static image of the graph.
            - "cytoscape-jupyter": Returns an interactive Cytoscape widget
              for Jupyter notebooks.
            - "cytoscape-streamlit": Returns a Cytoscape component
              compatible with Streamlit.
            By default "graphviz-object".
        input_time_format : str, optional
            The time unit used to calculate durations and timestamps,
            by default "minutes".
        warm_up : float, optional
            Discard a warm-up period before the graph is built, by dropping
            events at or before this simulation time. Default is `None`,
            which keeps every event. See
            :func:`vidigi.process_mapping.add_sim_timestamp` for what this
            does and does not affect.
        **kwargs
            Arbitrary keyword arguments passed to the underlying rendering
            functions (`dfg_to_graphviz`, `dfg_to_cytoscape`, etc.).

        Returns
        -------
        graphviz.Source or ipycytoscape.CytoscapeWidget or bytes
            The rendered graph object in the format specified by `output_format`.

        Raises
        ------
        ValueError
            If the provided `output_format` is not a valid `DFGType`.

        Notes
        -----
        This function is a wrapper. For detailed information on how nodes and
        edges are calculated, or for specific rendering parameters available
        in ``**kwargs``, please refer to the documentation for:

        - :func:`discover_dfg`: For edge discovery logic.
        - :func:`dfg_to_graphviz`: For Graphviz-specific styling kwargs.
        - :func:`dfg_to_cytoscape`: For jupyter cytoscape styling kwargs.
        - :func:`dfg_to_cytoscape_streamlit`: For streamlit cytoscape styling kwargs.

        """
        df = self.to_dataframe()
        df = add_sim_timestamp(df, time_unit=input_time_format, warm_up=warm_up)
        nodes, edges = discover_dfg(df, time_unit=input_time_format)

        if output_format == "graphviz-object":
            return dfg_to_graphviz(nodes, edges, time_unit=input_time_format, **kwargs)
        elif output_format == "graphviz-image":
            return dfg_to_graphviz(
                nodes, edges, return_image=True, time_unit=input_time_format, **kwargs
            )
        elif output_format == "cytoscape-jupyter":
            return dfg_to_cytoscape(nodes, edges, time_unit=input_time_format, **kwargs)
        elif output_format == "cytoscape-streamlit":
            return dfg_to_cytoscape_streamlit(
                nodes, edges, time_unit=input_time_format, **kwargs
            )
        else:
            raise ValueError(
                f"Invalid output format passed. Valid formats are {DFGType}."
            )


class TrialLogger:
    """
    A container and analysis utility for managing multiple event logs from repeated
    simulation runs or trials.

    The `TrialLogger` aggregates logs produced by `EventLogger` instances,
    indexes them by run ID, and provides utilities for retrieving logs,
    summarizing trial statistics, and computing event-to-event durations.

    Methods include
    add_log(event_log)
        Add a new `EventLogger` log to the trial collection.
    get_log_by_run(run, as_df=False)
        Retrieve the log for a specific run. Can return raw records or as a DataFrame.
    to_dataframe()
        Return the full trial data as a pandas DataFrame.
    summary()
        Return a simple summary of the number of runs in the trial.
    get_event_durations(first_event, second_event, match="first", **kwargs)
        Compute per-entity durations between two event types across every run.
    get_event_duration_stat(first_event, second_event, what="mean",
                            exclude_incomplete=True, dp=2, label=None, **kwargs)
        Compute statistics on durations between two event types across runs.
    plot_duration_distribution(first_event, second_event, kind="hist", **kwargs)
        Plot the distribution of durations between two events, across every run.

    Parameters
    ----------
    event_logs : list[EventLogger], optional
        A list of vidigi `EventLogger` instances to initialize the trial log with.

    """

    def __init__(self, event_logs: Optional[list[EventLogger]] = None):
        self._event_logs = []

        if event_logs is not None:
            for log in event_logs:
                self._event_logs.append(
                    {"run_id": self._run_id_of(log), "run_data": log}
                )

        self._run_index = {r["run_id"]: r for r in self._event_logs}

    @staticmethod
    def _run_id_of(event_log: EventLogger):
        """Read the run number off a log, with a message that says what is wrong."""
        if not event_log._log:
            raise ValueError(
                "Cannot add an empty EventLogger to a TrialLogger - the run number is "
                "read from its first event."
            )
        run_number = event_log._log[0].get("run_number")
        if run_number is None:
            raise ValueError(
                "The EventLogger being added has no `run_number` on its first event. "
                "Construct it with EventLogger(run_number=...) so its events can be "
                "told apart from other runs in the trial."
            )
        return run_number

    @property
    def _trial_dataframe(self):
        """Every run's events in one frame, rebuilt from the current logs.

        This is derived rather than stored: it was previously built once in
        __init__, so any log added later was counted by `summary()` but absent
        from every statistic computed off this frame.
        """
        if not self._event_logs:
            return pd.DataFrame()

        return pd.concat(
            [log["run_data"].to_dataframe() for log in self._event_logs],
            ignore_index=True,
        )

    def add_log(self, event_log: EventLogger):
        """
        Add a new event log to the trial collection.

        Parameters
        ----------
        event_log : EventLogger
            An `EventLogger` instance containing a log of events for a single run.
        """
        self._event_logs.append(
            {"run_id": self._run_id_of(event_log), "run_data": event_log}
        )
        self._run_index = {r["run_id"]: r for r in self._event_logs}

    def get_log_by_run(self, run, as_df=False):
        """
        Retrieve the log for a specific run.

        Parameters
        ----------
        run : int or str
            The run identifier to fetch.
        as_df : bool, default=False
            If True, return the log as a pandas DataFrame.
            Otherwise, return the raw event records (list of dicts).

        Returns
        -------
        list of dict or pandas.DataFrame
            The requested run log, either as raw records or a DataFrame.
        """
        if not as_df:
            return self._run_index[run]["run_data"]
        else:
            return self._run_index[run]["run_data"].to_dataframe()

    def to_dataframe(self):
        """
        Return the full trial data as a single concatenated DataFrame.

        Returns
        -------
        pandas.DataFrame
            A dataframe containing all events from all runs.
        """
        return self._trial_dataframe

    def summary(self):
        """
        Summarize the trial logs.

        Returns
        -------
        dict
            Dictionary with summary information:
            - ``"number_of_runs"`` : int
              The number of runs currently stored.
        """
        return {"number_of_runs": len(self._event_logs)}

    def get_event_durations(
        self,
        first_event,
        second_event,
        *,
        match: MatchMode = "first",
        **kwargs,
    ):
        """
        Compute per-entity durations between two event types across every run.

        Thin wrapper over `vidigi.analysis.event_durations`, called on the trial's
        combined dataframe. See that function for the full parameter list, the
        meaning of `match`, and how incomplete pairs are handled.

        Parameters
        ----------
        first_event : str
            Name of the first event.
        second_event : str
            Name of the second event.
        match : {"first", "last", "occurrence"}, default="first"
            How repeated occurrences of the two events for the same entity are
            paired. See `vidigi.analysis.event_durations`.
        **kwargs : dict
            Additional keyword arguments forwarded to
            `vidigi.analysis.event_durations` (e.g. `entity_col_name`,
            `keep_incomplete`).

        Returns
        -------
        pandas.DataFrame
            One row per matched pair, with columns ``entity_id``, ``run_number``,
            ``pathway``, ``occurrence``, ``first_time``, ``second_time``,
            ``duration``.

        See Also
        --------
        vidigi.analysis.event_durations : Full parameter list and pairing semantics.
        """
        return event_durations(
            self._trial_dataframe, first_event, second_event, match=match, **kwargs
        )

    def get_event_duration_stat(
        self,
        first_event,
        second_event,
        what: DurationStat = "mean",
        exclude_incomplete=True,
        dp=2,
        label=None,
        match: MatchMode = "first",
        **kwargs,
    ):
        """
        Compute statistics on durations between two event types across runs.

        Parameters
        ----------
        first_event : str
            Name of the first event (start).
        second_event : str
            Name of the second event (end).
        what : str, default="mean"
            Statistic to compute. Options include:
            - Standard aggregations: {"mean", "median", "max", "min",
              "quantile", "std", "var", "sum"}
            - Special aggregations: {"count", "unserved_count", "served_count",
              "unserved_rate", "served_rate", "summary"}
        exclude_incomplete : bool, default=True
            If True, ignore cases where the second event is missing (NaN).
        dp : int, default=2
            Number of decimal places to round numeric results to.
        label : str, optional
            If provided, return the result as a dictionary with keys
            {"stat": label, "value": result}.
        match : {"first", "last", "occurrence"}, default="first"
            How repeated occurrences of the two events for the same entity are
            paired, for entities that revisit a step. See
            `vidigi.analysis.event_durations` for the full explanation. The
            default matches the behaviour of every prior release, where an
            entity visiting either event more than once was unsupported.
        **kwargs : dict
            Additional arguments passed to the pandas Series method
            corresponding to `what` (e.g., `quantile(q=0.9)`).

        Returns
        -------
        float or dict
            The computed statistic, rounded to ``dp`` if numeric.
            If ``what="summary"``, returns a dictionary with multiple statistics.
            If ``label`` is provided, wraps the result in a dict with the label.

        Raises
        ------
        ValueError
            If `what` is not a supported aggregation function.

        See Also
        --------
        get_event_durations : The per-entity durations this method summarises.
        """
        # Every run in the trial, not just those where one of the two events
        # occurred - otherwise a run with neither event is silently uncounted,
        # inflating served/unserved rates that are meant to be per-run averages.
        n_runs = len(self._event_logs)

        series = self.get_event_durations(first_event, second_event, match=match)[
            "duration"
        ]

        result = _summarise_durations(
            series, what, exclude_incomplete, n_runs, dp=dp, **kwargs
        )

        if label:
            return {"stat": label, "value": result}
        else:
            return result

    def get_resource_utilisation(
        self,
        *,
        by: ResourceUtilisationBy = "step",
        scenario=None,
        resource_map: Optional[dict] = None,
        event_position_df: Optional[pd.DataFrame] = None,
        resource_capacities: Optional[dict] = None,
        capacity: Optional[Literal["infer"]] = None,
        warm_up: float = 0,
        limit_duration: Optional[float] = None,
        unclosed: UnclosedResourceUse = "censor",
        resource_col_name: str = "resource_id",
    ):
        """
        Summarise resource use into busy time, mean-in-use and utilisation, per run.

        Thin wrapper over `vidigi.analysis.resource_utilisation`, called on the
        trial's combined dataframe. See that function for the full parameter
        list, the four capacity-resolution routes, and how an unclosed resource
        use is handled.

        Parameters
        ----------
        by : {"step", "resource", "run"}, default="step"
            What each row summarises. See `vidigi.analysis.resource_utilisation`.
        scenario, resource_map, event_position_df, resource_capacities, capacity :
            Capacity resolution - see `vidigi.analysis._resolve_resource_capacities`
            for the four routes. All optional; with none given, `utilisation`
            is `NaN` throughout and only `busy_time`/`mean_in_use` are
            meaningful.
        warm_up : float, default=0
            Start of the analysis window.
        limit_duration : float, optional
            End of the analysis window. `None` (default) uses the latest time
            seen anywhere in the trial.
        unclosed : {"censor", "drop"}, default="censor"
            How an entity still holding a resource at the end of the window is
            handled. See `vidigi.analysis.resource_use_intervals`.
        resource_col_name : str, default="resource_id"
            Which column identifies the physical resource for `by="resource"`.
            Point this at a globally-unique column (e.g. `"unique_resource_id"`,
            logged via `log_resource_use_start`/`_end`'s `**extra_fields`) if
            your model has more than one `VidigiStore`/`VidigiPriorityStore`
            pool constructed with a `label=` - see `vidigi.resources.VidigiStore`.

        Returns
        -------
        pandas.DataFrame
            One row per run per group - see `vidigi.analysis.resource_utilisation`.

        See Also
        --------
        vidigi.analysis.resource_utilisation : The underlying implementation.
        vidigi.analysis.resource_use_intervals : The underlying per-bout intervals.
        """
        return resource_utilisation(
            self._trial_dataframe,
            by=by,
            scenario=scenario,
            resource_map=resource_map,
            event_position_df=event_position_df,
            resource_capacities=resource_capacities,
            capacity=capacity,
            warm_up=warm_up,
            limit_duration=limit_duration,
            unclosed=unclosed,
            resource_col_name=resource_col_name,
        )

    def plot_duration_distribution(
        self,
        first_event,
        second_event,
        *,
        kind: DistributionKind = "hist",
        split_by: Optional[SplitBy] = None,
        bins=None,
        match: MatchMode = "first",
        normalise: bool = False,
        title: Optional[str] = None,
        **kwargs,
    ):
        """
        Plot the distribution of durations between two events, across every run.

        Thin wrapper over `vidigi.plots.plot_duration_distribution`, called on
        this trial's combined dataframe. See that function for the full
        parameter list.

        Parameters
        ----------
        first_event, second_event : str
            The two events to measure the duration between.
        kind : {"hist", "box", "violin", "ecdf", "ridgeline", "heatmap"}, default="hist"
            Chart type. `"ridgeline"` and `"heatmap"` require `split_by` to be
            set - see `vidigi.plots.plot_duration_distribution` for the full
            explanation of each.
        split_by : {"run", "pathway"} or None, default=None
            If given, one trace (or, for `"heatmap"`, one row) per distinct
            value of that column.
        bins : int, sequence, or None, default=None
            Passed to `numpy.histogram` when `kind` is `"hist"`, `"ridgeline"`
            or `"heatmap"`.
        match : {"first", "last", "occurrence"}, default="first"
            How repeated occurrences of the two events are paired.
        normalise : bool, default=False
            For `kind="hist"` or `kind="heatmap"`: heights/cells as a
            probability density rather than raw counts. `"ridgeline"` always
            uses density, regardless of this argument.
        title : str, optional
            Figure title.
        **kwargs : dict
            Additional keyword arguments forwarded to
            `vidigi.analysis.event_durations`.

        Returns
        -------
        plotly.graph_objects.Figure

        See Also
        --------
        vidigi.plots.plot_duration_distribution : The underlying implementation.
        vidigi.analysis.event_durations : The underlying per-entity durations.
        """
        return _plot_duration_distribution(
            self._trial_dataframe,
            first_event,
            second_event,
            kind=kind,
            split_by=split_by,
            bins=bins,
            match=match,
            normalise=normalise,
            title=title,
            **kwargs,
        )

    def plot_metric_bar(
        self,
        event_pair_list: list[dict],
        what: DurationStat = "mean",
        exclude_incomplete: bool = True,
        across: Across = "entities",
        error_bars: Optional[ErrorBars] = None,
        ci_level: float = 0.95,
        show_runs: bool = False,
        match: MatchMode = "first",
        interactive=True,
        **kwargs,
    ):
        """
        Plot a bar chart of event duration statistics for a list of event pairs.

        Thin wrapper over `vidigi.plots.plot_metric_bar`, called on this trial's
        combined dataframe. See that function for the full parameter list.

        Parameters
        ----------
        event_pair_list : list of dict
            A list of dictionaries, each containing:

            - ``"label"`` (str): A label for the event pair.
            - ``"first_event"`` (str): The name of the first event.
            - ``"second_event"`` (str): The name of the second event.
        what : str, default="mean"
            The statistic to compute on event durations. See
            `vidigi.analysis.event_durations`'s module for the full set. When
            `across="runs"`, only a genuine per-replication statistic is
            accepted - see `vidigi.analysis.replication_means`.
        exclude_incomplete : bool, default=True
            If True, incomplete event durations (where the second event is missing)
            are excluded from the calculation. Must be True when `across="runs"`.
        across : {"entities", "runs"}, default="entities"
            Whether each bar is a statistic pooled over every entity (matching
            every prior release), or the mean of a per-replication statistic
            computed separately for each run. `error_bars` and `show_runs`
            both require `across="runs"`.
        error_bars : {"ci", "sd", "se", "range", "iqr"} or None, default=None
            The spread drawn as an error bar around each bar. `"ci"` requires
            the optional `scipy` dependency (`pip install vidigi[stats]`). See
            `vidigi.plots.plot_metric_bar` for the full explanation of each.
        ci_level : float, default=0.95
            Confidence level used when `error_bars="ci"`.
        show_runs : bool, default=False
            If True, overlays each replication's individual value as a
            semi-transparent point on top of its bar.
        match : {"first", "last", "occurrence"}, default="first"
            How repeated occurrences of the two events are paired. See
            `vidigi.analysis.event_durations`.
        interactive : bool, default=True
            If True, returns an interactive Plotly bar chart. If False, static
            plotting is not currently supported (a message will be printed).
        **kwargs : dict
            Additional keyword arguments passed to ``plotly.express.bar`` (e.g.
            `title=`, `width=`).

        Returns
        -------
        plotly.graph_objs._figure.Figure or None
            An interactive Plotly bar chart if ``interactive=True``.
            Otherwise, prints a message and returns None.

        See Also
        --------
        plot_duration_distribution : The full distribution behind one of these bars.
        vidigi.plots.plot_metric_bar : The underlying implementation.

        Examples
        --------
        >>> event_pairs = [
        ...     {"label": "Start to End", "first_event": "start", "second_event": "end"},
        ...     {"label": "Check to Approve", "first_event": "check", "second_event": "approve"},
        ... ]
        >>> fig = obj.plot_metric_bar(event_pairs, what="mean")
        >>> fig.show()
        """
        if not interactive:
            print("Static plotting not currently supported - please use 'interactive'")
            return None

        return _plot_metric_bar(
            self._trial_dataframe,
            event_pair_list,
            what=what,
            exclude_incomplete=exclude_incomplete,
            across=across,
            error_bars=error_bars,
            ci_level=ci_level,
            show_runs=show_runs,
            match=match,
            **kwargs,
        )

    def plot_queue_size(
        self,
        event_list: list[str],
        limit_duration,
        every_x_time_units=1,
        interactive=True,
        show_all_runs=True,
        shared_y_axis=True,
        warm_up: int = 0,
        backend: PlotBackend = "express",
        **kwargs,
    ):
        """
        Plot the size of one or more queues over time across simulation runs.

        Thin wrapper over `vidigi.plots.plot_queue_size`, called on this trial's
        combined dataframe.

        Parameters
        ----------
        event_list : list of str
            List of event types (e.g., `"queue_enter"`, `"queue_exit"`)
            to include in the plot.
        limit_duration : int or float
            Maximum simulation duration (time units) to include in the plot.
        every_x_time_units : int, default=1
            Time granularity for snapshots. Larger values aggregate queue size
            over coarser time intervals.
        interactive : bool, default=True
            If True, generates an interactive Plotly figure. Static plotting is
            not currently implemented.
        show_all_runs : bool, default=True
            If True, plots all runs with semi-transparent lines and overlays
            the mean trajectory. If False, only the mean trajectory is plotted.
        warm_up : int, default=0
            Time at which the plotted window begins. Snapshots run from `warm_up`
            to `limit_duration`. See `vidigi.prep.reshape_for_animations` for why
            this - and not filtering the log by time - is the correct way to
            discard a warm-up period. The default of `0` is a no-op.
        backend : {"express", "go"}, default="express"
            Which plotly API builds the figure. See `vidigi.plots.plot_queue_size`
            for the full explanation - in short, `"go"` gives every trace a
            deterministic name and order instead of `px`'s automatic grouping,
            which some callers find easier to target when restyling the figure
            afterwards. `**kwargs` is ignored when `backend="go"`.
        **kwargs
            Additional keyword arguments passed to `plotly.express.line`. Ignored
            (with a warning) when `backend="go"`.

        Returns
        -------
        fig : plotly.graph_objects.Figure
            Interactive Plotly figure containing the queue size plot.

        Notes
        -----
        - When multiple event types are specified, they are faceted in separate
        panels if `show_all_runs=False`.
        - Queue lengths are **not** capped at `step_snapshot_max`, unlike the
        animation functions, so long queues are plotted at their full length
        rather than flattening off. Reshaping without that cap uses more memory
        than an equivalent animation would.
        - Snapshots at which an event has nobody queuing are plotted as zero
        rather than omitted, so a queue that empties is drawn dropping to the
        axis and the mean is taken across every run. An event in `event_list`
        that occurs in no run is plotted as zero throughout, with a warning.
        - If `interactive=False`, no plot is returned and a message is printed
        instead.

        See Also
        --------
        vidigi.plots.plot_queue_size : The underlying implementation.
        vidigi.analysis.queue_size_over_time : The underlying per-run, per-snapshot counts.

        Examples
        --------
        >>> sim.plot_queue_size(
        ...     event_list=["queue_enter", "queue_exit"],
        ...     limit_duration=500,
        ...     every_x_time_units=5,
        ...     show_all_runs=True
        ... )
        <plotly.graph_objs._figure.Figure>
        """
        if not interactive:
            print("Static plotting not currently supported - please use 'interactive'")
            return None

        return _plot_queue_size(
            self._trial_dataframe,
            event_list,
            limit_duration,
            every_x_time_units=every_x_time_units,
            warm_up=warm_up,
            show_all_runs=show_all_runs,
            shared_y_axis=shared_y_axis,
            backend=backend,
            **kwargs,
        )

    def plot_resource_utilisation(
        self,
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
        resource_col_name: str = "resource_id",
    ):
        """
        Plot a bar chart of resource utilisation, one bar per group, across runs.

        Thin wrapper over `vidigi.plots.plot_resource_utilisation`, called on
        this trial's combined dataframe. See that function for the full
        parameter list.

        Parameters
        ----------
        by : {"step", "resource", "run"}, default="step"
            What each bar summarises. See `vidigi.analysis.resource_utilisation`.
        metric : {"busy_time", "mean_in_use", "utilisation"}, default="utilisation"
            Which quantity is the bar height. Falls back to `"mean_in_use"`,
            with a warning, if no capacity was resolved for any group.
        error_bars : {"ci", "sd", "se", "range", "iqr"} or None, default="ci"
            The spread drawn as an error bar around each bar, computed over
            the per-run values. `"ci"` requires the optional `scipy`
            dependency (`pip install vidigi[stats]`).
        ci_level : float, default=0.95
            Confidence level used when `error_bars="ci"`.
        show_runs : bool, default=True
            If True, overlays each run's individual value as a
            semi-transparent point on top of its bar.
        sort_by : {"value"} or None, default=None
            If `"value"`, bars are ordered by descending metric value.
        scenario, resource_map, event_position_df, resource_capacities, capacity :
            Capacity resolution - see
            `vidigi.analysis._resolve_resource_capacities` for the four
            routes. Unused when `by="resource"`.
        warm_up : float, default=0
            Start of the analysis window.
        limit_duration : float, optional
            End of the analysis window. `None` (default) uses the latest time
            seen anywhere in the trial.
        unclosed : {"censor", "drop"}, default="censor"
            How an entity still holding a resource at the end of the window is
            handled. See `vidigi.analysis.resource_use_intervals`.
        resource_col_name : str, default="resource_id"
            Which column identifies the physical resource for `by="resource"`.
            Point this at a globally-unique column (e.g. `"unique_resource_id"`,
            logged via `log_resource_use_start`/`_end`'s `**extra_fields`) if
            your model has more than one `VidigiStore`/`VidigiPriorityStore`
            pool constructed with a `label=` - see `vidigi.resources.VidigiStore`.

        Returns
        -------
        plotly.graph_objects.Figure

        See Also
        --------
        vidigi.plots.plot_resource_utilisation : The underlying implementation.
        get_resource_utilisation : The underlying per-run, per-group summary.
        """
        return _plot_resource_utilisation(
            self._trial_dataframe,
            by=by,
            metric=metric,
            error_bars=error_bars,
            ci_level=ci_level,
            show_runs=show_runs,
            sort_by=sort_by,
            scenario=scenario,
            resource_map=resource_map,
            event_position_df=event_position_df,
            resource_capacities=resource_capacities,
            capacity=capacity,
            warm_up=warm_up,
            limit_duration=limit_duration,
            unclosed=unclosed,
            resource_col_name=resource_col_name,
        )

    def plot_resource_utilisation_over_time(
        self,
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
    ):
        """
        Plot how many units of each resource step were in use over time, across runs.

        Thin wrapper over `vidigi.plots.plot_resource_utilisation_over_time`,
        called on this trial's combined dataframe. See that function for the
        full parameter list.

        Parameters
        ----------
        every_x_time_units : float, default=1
            Time granularity for snapshots.
        warm_up : float, default=0
            Time at which the plotted window begins.
        limit_duration : float, optional
            End of the plotted window. `None` (default) uses the latest time
            seen anywhere in the trial.
        as_proportion : bool, default=False
            If True, each step's count is divided by its resolved capacity, so
            the y-axis is a proportion in use rather than a raw count. Requires
            a capacity to be resolvable for every step plotted.
        show_all_runs : bool, default=True
            If True, plots every run with semi-transparent lines and overlays
            the mean trajectory.
        shared_y_axis : bool, default=True
            If True (and more than one step is plotted), every facet shares a
            y-axis range.
        scenario, resource_map, event_position_df, resource_capacities, capacity :
            Capacity resolution, used only when `as_proportion=True`.

        Returns
        -------
        plotly.graph_objects.Figure

        Notes
        -----
        Traces use `line_shape="hv"` - occupancy is a step function, and linear
        interpolation between snapshots would draw fractional resource counts
        that never existed.

        See Also
        --------
        vidigi.plots.plot_resource_utilisation_over_time : The underlying implementation.
        vidigi.analysis.resource_occupancy_over_time : The underlying per-run, per-snapshot counts.
        """
        return _plot_resource_utilisation_over_time(
            self._trial_dataframe,
            every_x_time_units=every_x_time_units,
            warm_up=warm_up,
            limit_duration=limit_duration,
            as_proportion=as_proportion,
            show_all_runs=show_all_runs,
            shared_y_axis=shared_y_axis,
            scenario=scenario,
            resource_map=resource_map,
            event_position_df=event_position_df,
            resource_capacities=resource_capacities,
            capacity=capacity,
        )

