"""Tests for ``EventLogger``.

logging.py had no dedicated test file. The logger is what produces the event
log everything downstream consumes, so a mistake here corrupts the animation
and every statistic derived from it, usually without raising.
"""

import json
import warnings
from datetime import datetime

import pandas as pd
import pytest

from vidigi.logging import BaseEvent, EventLogger


@pytest.fixture(autouse=True)
def reset_warning_memory():
    """`BaseEvent` remembers warned-about event types on the class itself.

    That set is process-global and never cleared, so without this a test that
    ran earlier would suppress the warning a later test is asserting on.
    """
    BaseEvent._warned_unrecognized_event_types.clear()
    yield
    BaseEvent._warned_unrecognized_event_types.clear()


class SimpyStyleEnv:
    """`env.now` as an attribute, as in simpy."""

    def __init__(self, now=0.0):
        self.now = now


class SalabimStyleEnv:
    """`env.now` as a method, as in salabim."""

    def __init__(self, value=0.0):
        self._value = value

    def now(self):
        return self._value


# --------------------------------------------------------------------------- #
# Helper methods produce the documented event_type / event pairs
# --------------------------------------------------------------------------- #


def test_log_arrival_shape():
    logger = EventLogger()

    logger.log_arrival(entity_id=1, time=3.0)

    assert logger.log == [
        {
            "entity_id": 1,
            "event_type": "arrival_departure",
            "event": "arrival",
            "time": 3.0,
            "pathway": None,
            "run_number": None,
            "timestamp": None,
            "resource_id": None,
        }
    ]


def test_log_departure_shape():
    logger = EventLogger()

    logger.log_departure(entity_id=1, time=9.0)

    assert logger.log[0]["event_type"] == "arrival_departure"
    assert logger.log[0]["event"] == "depart"


def test_log_queue_keeps_caller_event_name():
    logger = EventLogger()

    logger.log_queue(entity_id=1, event="waiting_for_triage", time=4.0)

    assert logger.log[0]["event_type"] == "queue"
    assert logger.log[0]["event"] == "waiting_for_triage"


@pytest.mark.parametrize(
    "method, expected_type, expected_event",
    [
        ("log_resource_use_start", "resource_use", "start"),
        ("log_resource_use_end", "resource_use_end", "end"),
    ],
)
def test_resource_use_helpers(method, expected_type, expected_event):
    logger = EventLogger()

    getattr(logger, method)(entity_id=1, resource_id=2, time=5.0)

    assert logger.log[0]["event_type"] == expected_type
    assert logger.log[0]["event"] == expected_event
    assert logger.log[0]["resource_id"] == 2


def test_log_custom_event_passes_through_both_fields():
    logger = EventLogger()

    logger.log_custom_event(
        entity_id=1, event_type="my_type", event="my_event", time=1.0
    )

    assert logger.log[0]["event_type"] == "my_type"
    assert logger.log[0]["event"] == "my_event"


def test_extra_fields_are_preserved():
    """Arbitrary columns must survive - they are usable as custom hover data."""
    logger = EventLogger()

    logger.log_arrival(entity_id=1, time=1.0, ward="A", priority=3)

    assert logger.log[0]["ward"] == "A"
    assert logger.log[0]["priority"] == 3


# --------------------------------------------------------------------------- #
# Time and run number
# --------------------------------------------------------------------------- #


def test_time_taken_from_simpy_style_env():
    logger = EventLogger(env=SimpyStyleEnv(now=12.5))

    logger.log_arrival(entity_id=1)

    assert logger.log[0]["time"] == 12.5


def test_time_taken_from_salabim_style_callable_env():
    """salabim exposes `now` as a method rather than an attribute."""
    logger = EventLogger(env=SalabimStyleEnv(value=99.0))

    logger.log_arrival(entity_id=1)

    assert logger.log[0]["time"] == 99.0


def test_explicit_time_overrides_env():
    logger = EventLogger(env=SimpyStyleEnv(now=12.5))

    logger.log_arrival(entity_id=1, time=1.0)

    assert logger.log[0]["time"] == 1.0


def test_time_zero_is_not_treated_as_missing():
    """Events at t=0 are common - the first arrival often is one.

    The helpers strip None values before validating, so a falsy-but-valid time
    must not be caught up in that.
    """
    logger = EventLogger()

    logger.log_arrival(entity_id=1, time=0.0)

    assert logger.log[0]["time"] == 0.0


def test_missing_time_without_env_raises():
    logger = EventLogger()

    with pytest.raises(ValueError, match="Missing 'time'"):
        logger.log_arrival(entity_id=1)


def test_run_number_defaults_from_constructor():
    logger = EventLogger(run_number=7)

    logger.log_arrival(entity_id=1, time=1.0)

    assert logger.log[0]["run_number"] == 7


def test_explicit_run_number_overrides_constructor():
    logger = EventLogger(run_number=7)

    logger.log_arrival(entity_id=1, time=1.0, run_number=2)

    assert logger.log[0]["run_number"] == 2


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("event_name", ["arrival", "depart"])
def test_arrival_departure_accepts_only_its_two_events(event_name):
    logger = EventLogger()

    logger.log_event(
        entity_id=1, event_type="arrival_departure", event=event_name, time=1.0
    )

    assert logger.log[0]["event"] == event_name


def test_arrival_departure_rejects_other_events():
    """Otherwise the reshape step cannot pivot arrivals against departures."""
    logger = EventLogger()

    with pytest.raises(ValueError, match="must be 'arrival' or 'depart'"):
        logger.log_event(
            entity_id=1, event_type="arrival_departure", event="waiting", time=1.0
        )


def test_unrecognised_event_type_warns():
    logger = EventLogger()

    with pytest.warns(UserWarning, match="Unrecognized event_type"):
        logger.log_event(entity_id=1, event_type="mystery", event="a", time=1.0)


def test_unrecognised_event_type_warns_only_once_per_type():
    """A per-event warning would be unusable in a simulation logging thousands."""
    logger = EventLogger()

    with pytest.warns(UserWarning) as recorded:
        logger.log_event(entity_id=1, event_type="mystery", event="a", time=1.0)
        logger.log_event(entity_id=2, event_type="mystery", event="b", time=2.0)

    unrecognised = [
        w for w in recorded if "Unrecognized event_type" in str(w.message)
    ]
    assert len(unrecognised) == 1


def test_log_custom_event_does_not_warn_about_its_event_type():
    """Custom types are the whole point of this helper, so warning is noise."""
    logger = EventLogger()

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        logger.log_custom_event(
            entity_id=1, event_type="my_type", event="a", time=1.0
        )

    assert recorded == []


@pytest.mark.parametrize(
    "event_type", ["resource_use", "resource_use_end"]
)
def test_missing_resource_id_warns_on_resource_events(event_type):
    """Resource events without an id cannot be positioned in the animation.

    Regression test: pydantic skips a field's validators when the caller omits
    it, so this recommendation could never fire in exactly the case it exists
    to catch.
    """
    logger = EventLogger()

    with pytest.warns(UserWarning, match="resource_id is recommended"):
        logger.log_event(
            entity_id=1, event_type=event_type, event="x", time=1.0
        )


def test_no_resource_id_warning_for_non_resource_events():
    """Only resource events need an id, so nothing else should be nagged."""
    logger = EventLogger()

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        logger.log_queue(entity_id=1, event="waiting", time=1.0)
        logger.log_arrival(entity_id=1, time=0.0)

    assert recorded == []


def test_non_integer_resource_id_warns():
    logger = EventLogger()

    with pytest.warns(UserWarning, match="resource_id should be an integer"):
        logger.log_resource_use_start(entity_id=1, resource_id=2.0, time=1.0)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2020-01-01 10:30:00", datetime(2020, 1, 1, 10, 30, 0)),
        ("2020-01-01 10:30", datetime(2020, 1, 1, 10, 30)),
        ("2020-01-01", datetime(2020, 1, 1)),
    ],
)
def test_timestamp_parsing(value, expected):
    logger = EventLogger()

    logger.log_arrival(entity_id=1, time=1.0, timestamp=value)

    assert logger.log[0]["timestamp"] == expected


def test_ambiguous_timestamp_rejected():
    """Day-first vs month-first cannot be guessed, so it is refused."""
    logger = EventLogger()

    with pytest.raises(ValueError, match="Unrecognized or ambiguous datetime"):
        logger.log_arrival(entity_id=1, time=1.0, timestamp="01/02/2020")


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #


@pytest.fixture
def populated_logger():
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=0.0)
    logger.log_queue(entity_id=1, event="waiting", time=1.0)
    logger.log_departure(entity_id=1, time=5.0)
    logger.log_arrival(entity_id=2, time=2.0)
    logger.log_queue(entity_id=2, event="waiting", time=3.0)
    return logger


def test_get_events_by_entity(populated_logger):
    result = populated_logger.get_events_by_entity(1)

    assert len(result) == 3
    assert set(result["entity_id"]) == {1}


def test_get_events_by_event_type(populated_logger):
    result = populated_logger.get_events_by_event_type("queue")

    assert len(result) == 2


def test_get_events_by_event_name(populated_logger):
    result = populated_logger.get_events_by_event_name("waiting")

    assert len(result) == 2


def test_get_events_by_run(populated_logger):
    assert len(populated_logger.get_events_by_run(1)) == 5
    assert len(populated_logger.get_events_by_run(99)) == 0


def test_get_events_as_records(populated_logger):
    result = populated_logger.get_events_by_entity(1, as_dataframe=False)

    assert isinstance(result, list)
    assert all(isinstance(record, dict) for record in result)


def test_summary(populated_logger):
    summary = populated_logger.summary()

    assert summary["total_events"] == 5
    assert summary["unique_entities"] == 2
    assert summary["time_range"] == (0.0, 5.0)
    assert summary["event_types"]["queue"] == 2


def test_summary_of_empty_log():
    assert EventLogger().summary() == {"total_events": 0}


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #


def test_to_dataframe_drops_all_empty_columns(populated_logger):
    df = populated_logger.to_dataframe()

    assert "timestamp" not in df.columns
    assert {"entity_id", "event_type", "event", "time"} <= set(df.columns)


def test_to_json_string_round_trips(populated_logger):
    parsed = json.loads(populated_logger.to_json_string())

    assert len(parsed) == 5
    assert parsed[0]["event"] == "arrival"


def test_to_csv_writes_file(populated_logger, tmp_path):
    path = tmp_path / "log.csv"

    populated_logger.to_csv(path)

    assert len(pd.read_csv(path)) == 5


def test_to_json_writes_file(populated_logger, tmp_path):
    path = tmp_path / "log.json"

    populated_logger.to_json(path)

    assert len(json.loads(path.read_text(encoding="utf-8"))) == 5


@pytest.mark.parametrize("method", ["to_csv", "to_json"])
def test_export_of_empty_log_raises(method, tmp_path):
    logger = EventLogger()

    with pytest.raises(ValueError, match="Event log is empty"):
        getattr(logger, method)(tmp_path / "out")


# --------------------------------------------------------------------------- #
# from_csv
# --------------------------------------------------------------------------- #


@pytest.fixture
def external_dataframe():
    return pd.DataFrame(
        {
            "id": [1, 1, 2],
            "t": [0.0, 5.0, 2.0],
            "what": ["arrival", "depart", "arrival"],
            "kind": ["arrival_departure", "arrival_departure", "arrival_departure"],
        }
    )


def test_from_csv_renames_columns(external_dataframe):
    logger = EventLogger()

    logger.from_csv(
        external_dataframe,
        entity_col_name="id",
        time_col_name="t",
        event_col_name="what",
        event_type_col_name="kind",
    )

    assert set(logger.to_dataframe().columns) == {
        "entity_id",
        "time",
        "event",
        "event_type",
    }


def test_from_csv_leaves_logger_usable(external_dataframe):
    """Regression test: `_log` is a list of records everywhere else.

    Assigning the DataFrame itself left the logger in a state where iteration
    walked column names (AttributeError), truthiness checks raised, and JSON
    export failed with a TypeError.
    """
    logger = EventLogger()

    logger.from_csv(
        external_dataframe,
        entity_col_name="id",
        time_col_name="t",
        event_col_name="what",
        event_type_col_name="kind",
    )

    assert isinstance(logger.log, list)
    assert len(logger.get_events_by_entity(1)) == 2
    assert len(json.loads(logger.to_json_string())) == 3
    assert logger.summary()["total_events"] == 3


def test_from_csv_optional_columns(external_dataframe):
    df = external_dataframe.assign(run=[1, 1, 1], route=["a", "a", "b"])
    logger = EventLogger()

    logger.from_csv(
        df,
        entity_col_name="id",
        time_col_name="t",
        event_col_name="what",
        event_type_col_name="kind",
        run_col_name="run",
        pathway_col_name="route",
    )

    columns = set(logger.to_dataframe().columns)

    assert "run_number" in columns
    assert "pathway" in columns


# --------------------------------------------------------------------------- #
# Plotting and DFG entry points
# --------------------------------------------------------------------------- #


def test_plot_entity_timeline_rejects_unknown_entity(populated_logger):
    with pytest.raises(ValueError, match="No events found for entity_id"):
        populated_logger.plot_entity_timeline(entity_id=999)


def test_plot_entity_timeline_rejects_empty_log():
    with pytest.raises(ValueError, match="Event log is empty"):
        EventLogger().plot_entity_timeline(entity_id=1)


def test_generate_dfg_rejects_unknown_output_format(populated_logger):
    with pytest.raises(ValueError, match="Invalid output format"):
        populated_logger.generate_dfg(output_format="nonsense")
