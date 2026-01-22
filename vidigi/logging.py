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
import inspect
from vidigi.prep import reshape_for_animations
import plotly.graph_objects as go
from vidigi.process_mapping import (
    discover_dfg,
    add_sim_timestamp,
    dfg_to_graphviz,
    dfg_to_cytoscape,
    dfg_to_cytoscape_streamlit,
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
                event_data["time"] = self.env.now
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
        time: Optional[float] = None,
        pathway: Optional[str] = None,
        run_number: Optional[int] = None,
        **extra_fields,
    ):
        """
        Log the start of resource use. Requires resource_id.
        """
        event_data = {
            "entity_id": entity_id,
            "event_type": "resource_use",
            "event": "start",
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
        time: Optional[float] = None,
        pathway: Optional[str] = None,
        run_number: Optional[int] = None,
        **extra_fields,
    ):
        """
        Log the end of resource use. Requires resource_id.
        """
        event_data = {
            "entity_id": entity_id,
            "event_type": "resource_use_end",
            "event": "end",
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

        self._log = df.copy()

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
        print(entity_events)

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
        df = add_sim_timestamp(df, time_unit=input_time_format)
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
    get_event_duration_stat(first_event, second_event, what="mean",
                            exclude_incomplete=True, dp=2, label=None, **kwargs)
        Compute statistics on durations between two event types across runs.

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
                    {"run_id": log._log[0]["run_number"], "run_data": log}
                )

        self._run_index = {r["run_id"]: r for r in self._event_logs}

        self._trial_dataframe = pd.concat(
            [pd.DataFrame(log["run_data"].to_dataframe()) for log in self._event_logs]
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
            {"run_id": event_log._log[0]["run_number"], "run_data": event_log}
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
            return self._run_index[run]["run_data"]

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

    def get_event_duration_stat(
        self,
        first_event,
        second_event,
        what="mean",
        exclude_incomplete=True,
        dp=2,
        label=None,
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
        """
        event_df = self._trial_dataframe[
            self._trial_dataframe["event"].isin([first_event, second_event])
        ][["entity_id", "run_number", "event", "time"]].copy()

        n_runs = len(event_df["run_number"].unique())

        pivoted_df = event_df.pivot(
            columns="event", index=["entity_id", "run_number"], values="time"
        ).reset_index()[["entity_id", "run_number", first_event, second_event]]

        pivoted_df["duration"] = pivoted_df[second_event] - pivoted_df[first_event]

        series = pivoted_df["duration"]

        # Define special cases
        special_aggs = {
            "count",
            "unserved_count",
            "served_count",
            "unserved_rate",
            "served_rate",
            "summary",
        }

        # Collect allowed methods dynamically (only callables, no private methods)
        allowed = {
            "mean",
            "median",
            "max",
            "min",
            "quantile",
            "std",
            "var",
            "sum",
        } | special_aggs

        # check if valid
        if what not in allowed:
            # Build helpful message
            sigs = []
            for name in sorted(allowed):
                try:
                    func = getattr(series, name)
                    sig = str(inspect.signature(func))
                except Exception:
                    sig = "()"
                sigs.append(f"  - {name}{sig}")
            raise ValueError(
                f"Unsupported aggregation: {what}.\n"
                f"Allowed aggregations:\n" + "\n".join(sigs)
            )

        # Handle count separately
        if what == "count":
            if exclude_incomplete:
                result = series.count()  # excludes NaN
            else:
                result = series.size  # includes NaN
        elif what == "unserved_count":
            result = series.size - series.count()
        elif what == "served_count":
            result = series.count()  # excludes NaN
        elif what == "unserved_rate":
            result = (series.size - series.count()) / series.size
        elif what == "served_rate":
            result = series.count() / series.size
        elif what == "summary":
            result = {
                "mean (of complete)": series.mean(skipna=True),
                "median (of complete)": series.median(skipna=True),
                "min": series.min(),
                "max": series.max(),
                "unserved_count": series.size,
                "served_count": series.count(),
                "unserved_rate": (series.size - series.count()) / series.size,
                "served_rate": series.count() / series.size,
                "unserved_count_mean_per_run": series.size / n_runs,
                "served_count_mean_per_run": series.count() / n_runs,
            }

        # Otherwise, use predefined methods
        else:
            method = getattr(series, what)

            # Some methods accept skipna, others don't (like size, nunique with dropna instead).
            try:
                result = method(skipna=exclude_incomplete, **kwargs)
            except TypeError:
                # fallback if skipna isn't a parameter
                result = method(**kwargs)

        if what == "summary":
            result = {k: round(v, dp) for k, v in result.items()}
        else:
            result = round(result, dp)

        if label:
            return {"stat": label, "value": result}
        else:
            return result

    def plot_metric_bar(
        self,
        event_pair_list: list[dict],
        what: str = "mean",
        exclude_incomplete: bool = True,
        interactive=True,
        **kwargs,
    ):
        """
        Plot a bar chart of event duration statistics for a list of event pairs.

        This function computes a specified statistic (e.g., mean, median) of
        durations between pairs of events and plots the results as a bar chart.
        Interactive plotting is supported via Plotly.

        Parameters
        ----------
        event_pair_list : list of dict
            A list of dictionaries, each containing:

            - ``"label"`` (str): A label for the event pair.
            - ``"first_event"`` (str): The name of the first event.
            - ``"second_event"`` (str): The name of the second event.
        what : str, default="mean"
            The statistic to compute on event durations. Supported values depend on
            the implementation of ``get_event_duration_stat`` (e.g., "mean", "median").
        exclude_incomplete : bool, default=True
            If True, incomplete event durations (where the second event is missing)
            are excluded from the calculation.
        interactive : bool, default=True
            If True, returns an interactive Plotly bar chart. If False, static
            plotting is not currently supported (a message will be printed).
        **kwargs : dict
            Additional keyword arguments passed to ``plotly.express.bar``.

        Returns
        -------
        plotly.graph_objs._figure.Figure or None
            An interactive Plotly bar chart if ``interactive=True``.
            Otherwise, prints a message and returns None.

        See Also
        --------
        plot_queue_size : Plot the size of queues for events over time.

        Notes
        -----
        This method relies on ``self.get_event_duration_stat`` to compute the
        chosen statistic for each event pair.

        Examples
        --------
        >>> event_pairs = [
        ...     {"label": "Start to End", "first_event": "start", "second_event": "end"},
        ...     {"label": "Check to Approve", "first_event": "check", "second_event": "approve"},
        ... ]
        >>> fig = obj.plot_metric_bar(event_pairs, what="mean")
        >>> fig.show()
        """
        results = []
        for event_pair in event_pair_list:
            results.append(
                {
                    "label": event_pair["label"],
                    "value": self.get_event_duration_stat(
                        event_pair["first_event"],
                        event_pair["second_event"],
                        what=what,
                        exclude_incomplete=exclude_incomplete,
                    ),
                }
            )

        results_df = pd.DataFrame(results)

        if interactive:
            return px.bar(results_df, x="label", y="value", **kwargs)
        else:
            print("Static plotting not currently supported - please use 'interactive'")

    def plot_queue_size(
        self,
        event_list: list[str],
        limit_duration,
        every_x_time_units=1,
        interactive=True,
        show_all_runs=True,
        shared_y_axis=True,
        **kwargs,
    ):
        """
        Plot the size of one or more queues over time across simulation runs.

        This function processes logged simulation events, computes queue sizes
        for specified event types, and visualizes the results. If multiple runs
        are available, individual trajectories and/or their mean are shown.
        Currently, only interactive Plotly-based plotting is supported.

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
        **kwargs
            Additional keyword arguments passed to `plotly.express.line`.

        Returns
        -------
        fig : plotly.graph_objects.Figure
            Interactive Plotly figure containing the queue size plot.

        Notes
        -----
        - When multiple event types are specified, they are faceted in separate
        panels if `show_all_runs=False`.
        - The function relies on `reshape_for_animations` to transform raw
        event logs into a time-indexed format suitable for plotting.
        - If `interactive=False`, no plot is returned and a message is printed
        instead.

        See Also
        --------
        reshape_for_animations : Helper function for snapshotting simulation logs.

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
        results = []

        for run in self._event_logs:
            df = reshape_for_animations(
                run["run_data"].to_dataframe(),
                every_x_time_units=every_x_time_units,
                limit_duration=limit_duration,
            )
            df = df[df["event"].isin(event_list)]
            results.append(df.groupby(["run_number", "event", "snapshot_time"]).size())

        event_counts = pd.concat(results).reset_index(name="count")

        mean_df = event_counts.groupby(["snapshot_time", "event"], as_index=False)[
            "count"
        ].mean()

        if len(event_list) > 1:
            faceting_variable = "event"
        else:
            faceting_variable = None

        if interactive:
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

                    fig.for_each_annotation(
                        lambda a: a.update(text=a.text.split("=")[-1])
                    )

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

        else:
            print("Static plotting not currently supported - please use 'interactive'")
