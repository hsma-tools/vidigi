from pydantic import BaseModel, Field, field_validator, model_validator, ValidationInfo
from typing import Optional, Any, List, ClassVar, Set
import json
import pandas as pd
from pathlib import Path
from io import TextIOBase
from datetime import datetime
import plotly.express as px
import warnings

RECOGNIZED_EVENT_TYPES = {'arrival_departure', 'resource_use', 'resource_use_end', 'queue'}

class BaseEvent(BaseModel):
    _warned_unrecognized_event_types: ClassVar[Set[str]] = set()

    entity_id: Any = Field(
        ...,
        description="Identifier for the entity related to this event (e.g. patient ID, customer ID). Can be any type."
    )

    event_type: str = Field(
        ...,
        description=f"Type of event. Recommended values: {', '.join(RECOGNIZED_EVENT_TYPES)}"
    )

    event: str = Field(..., description="Name of the specific event.")

    time: float = Field(..., description="Simulation time or timestamp of event.")

    # Optional commonly-used fields
    pathway: Optional[str] = None

    run_number: Optional[int] = Field(
        default=None,
        description="A numeric value identifying the simulation run this record is associated with."
    )

    timestamp: Optional[datetime] = Field(
        default=None,
        description="Real-world timestamp of the event, if available."
    )

    resource_id: Optional[int] = Field(
        None,
        description="ID of the resource involved (required for resource use events)."
        )

    # Allow arbitrary extra fields
    model_config = {
        "extra": "allow"
    }

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

        if v not in RECOGNIZED_EVENT_TYPES and v not in cls._warned_unrecognized_event_types:
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
                    stacklevel=3
                )
            elif not isinstance(v, int):
                warnings.warn(
                    "resource_id should be an integer, but received type "
                    f"{type(v).__name__}.",
                    UserWarning,
                    stacklevel=3
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
        raise ValueError(f'Unrecognized or ambiguous datetime format for timestamp: {value}. Please use a year-first format such as "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", or "%Y-%m-%d".')

    @model_validator(mode="after")
    def validate_event_logic(self) -> 'BaseEvent':
        """
        Enforce constraints between event_type and event.
        """
        if self.event_type == 'arrival_departure':
            if self.event not in ['arrival', 'depart']:
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
                raise ValueError("Missing 'time' and no simulation environment provided.")

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

    def log_arrival(self, *, entity_id: Any, time: Optional[float] = None,
                    pathway: Optional[str] = None, run_number: Optional[int] = None,
                    **extra_fields):
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

    def log_departure(self, *, entity_id: Any, time: Optional[float] = None,
                      pathway: Optional[str] = None, run_number: Optional[int] = None,
                      **extra_fields):
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

    def log_queue(self, *, entity_id: Any, event: str, time: Optional[float] = None,
                  pathway: Optional[str] = None, run_number: Optional[int] = None,
                  **extra_fields):
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

    def log_resource_use_start(self, *, entity_id: Any, resource_id: int, time: Optional[float] = None,
                               pathway: Optional[str] = None, run_number: Optional[int] = None,
                               **extra_fields):
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

    def log_resource_use_end(self, *, entity_id: Any, resource_id: int, time: Optional[float] = None,
                             pathway: Optional[str] = None, run_number: Optional[int] = None,
                             **extra_fields):
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

    def log_custom_event(self, *, entity_id: Any, event_type: str,
                         event: str,
                         time: Optional[float] = None,
                         pathway: Optional[str] = None,
                         run_number: Optional[int] = None,
                        **extra_fields):
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
            context={"skip_event_type_check": True}
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
            with open(path_or_buffer, 'w', encoding='utf-8') as f:
                f.write(json_str)
        else:
            # Assume it's a writable file-like object
            path_or_buffer.write(json_str)

    def to_csv(self, path_or_buffer: str | Path | TextIOBase) -> None:
        """Write the log to a CSV file."""
        if not self._log:
            raise ValueError("Event log is empty.")

        df = self.to_dataframe()
        df.to_csv(path_or_buffer, index=False)

    def to_dataframe(self) -> pd.DataFrame:
        """Convert the event log to a pandas DataFrame."""
        return pd.DataFrame(self._log)

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
            "unique_entities": df["entity_id"].nunique() if "entity_id" in df else None,
        }

    ####################################################
    # Accessing certain elements of logs               #
    ####################################################

    def get_events_by_run(self, run_number: Any, as_dataframe: bool = True):
        """Return all events associated with a specific entity_id."""
        filtered = [event for event in self._log if event.get("run_number") == run_number]
        return pd.DataFrame(filtered) if as_dataframe else filtered

    def get_events_by_entity(self, entity_id: Any, as_dataframe: bool = True):
        """Return all events associated with a specific entity_id."""
        filtered = [event for event in self._log if event.get("entity_id") == entity_id]
        return pd.DataFrame(filtered) if as_dataframe else filtered

    def get_events_by_event_type(self, event_type: str, as_dataframe: bool = True):
        """Return all events of a specific event_type."""
        filtered = [event for event in self._log if event.get("event_type") == event_type]
        return pd.DataFrame(filtered) if as_dataframe else filtered

    def get_events_by_event_name(self, event: str, as_dataframe: bool = True):
        """Return all events of a specific event_type."""
        filtered = [event for event in self._log if event.get("event") == event]
        return pd.DataFrame(filtered) if as_dataframe else filtered

    ####################################################
    # Plotting from logs                               #
    ####################################################

    def plot_entity_timeline(self, entity_id: any):
        """
        Plot a timeline of events for a specific entity_id.
        """
        if not self._log:
            raise ValueError("Event log is empty.")

        df = self.to_dataframe()
        entity_events = df[df["entity_id"] == entity_id]

        if entity_events.empty:
            raise ValueError(f"No events found for entity_id = {entity_id}")

        # Sort by time for timeline plot
        entity_events = entity_events.sort_values("time")

        fig = px.scatter(entity_events,
                         x="time",
                         y=["event_type"],  # y axis can show event_type to separate events vertically
                         color="event_type",
                         hover_data=["event", "pathway", "run_number"],
                         labels={"time": "Time", "event_type": "Event Type"},
                         title=f"Timeline of Events for Entity {entity_id}")

        # Optional: jitter y axis for better visualization if multiple events at same time
        fig.update_traces(marker=dict(size=10, line=dict(width=1, color='DarkSlateGrey')))

        fig.update_yaxes(type="category")  # treat event_type as categorical on y-axis

        fig.show()
