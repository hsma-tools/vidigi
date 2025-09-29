import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch
from vidigi.prep import reshape_for_animations

# Tests have been written with the aid of Claude Sonnet 4
# All tests have been reviewed by a human for correctness


@pytest.fixture
def basic_event_log():
    """Create a basic event log for testing."""
    return pd.DataFrame(
        {
            "time": [0, 5, 10, 15, 20, 25, 30, 35, 40],
            "entity_id": [1, 1, 1, 2, 2, 2, 3, 3, 3],
            "event_type": [
                "arrival_departure",
                "queue",
                "arrival_departure",
                "arrival_departure",
                "queue",
                "arrival_departure",
                "arrival_departure",
                "queue",
                "arrival_departure",
            ],
            "event": [
                "arrival",
                "waiting",
                "depart",
                "arrival",
                "waiting",
                "depart",
                "arrival",
                "waiting",
                "depart",
            ],
        }
    )


@pytest.fixture
def event_log_with_resources():
    """Create an event log with resource usage events."""
    return pd.DataFrame(
        {
            "time": [0, 5, 10, 15, 20, 25, 30, 35],
            "entity_id": [1, 1, 1, 1, 2, 2, 2, 2],
            "event_type": [
                "arrival_departure",
                "resource_use",
                "resource_use_end",
                "arrival_departure",
                "arrival_departure",
                "resource_use",
                "resource_use_end",
                "arrival_departure",
            ],
            "event": [
                "arrival",
                "nurse_start",
                "nurse_end",
                "depart",
                "arrival",
                "nurse_start",
                "nurse_end",
                "depart",
            ],
        }
    )


def test_returns_dataframe(basic_event_log):
    """Test that function returns a DataFrame."""
    result = reshape_for_animations(basic_event_log)
    assert isinstance(result, pd.DataFrame), "Output should be a pandas dataframe"


def test_snapshot_time_column_exists(basic_event_log):
    """Test that snapshot_time column is created."""
    result = reshape_for_animations(basic_event_log)
    assert "snapshot_time" in result.columns, "snapshot_time column missing from output"


def test_snapshot_intervals(basic_event_log):
    """Test that snapshots are created at correct intervals."""
    every_x = 5
    result = reshape_for_animations(basic_event_log, every_x_time_units=every_x)
    unique_times = result["snapshot_time"].dropna().unique()

    # Check that all times are multiples of every_x
    assert all(time % every_x == 0 for time in unique_times), (
        "Snapshot time exists that is not a multiple of the provided times"
    )


def test_limit_duration_respected(basic_event_log):
    """Test that snapshots don't exceed limit_duration."""
    limit = 30
    result = reshape_for_animations(basic_event_log, limit_duration=limit)
    max_snapshot = result["snapshot_time"].max()

    assert max_snapshot <= limit, "Snapshot time exceeds passed limit"


def test_output_sorted_by_snapshot_and_event(basic_event_log):
    """Test that output is sorted by snapshot_time and event."""
    result = reshape_for_animations(basic_event_log)

    # Check sorting
    sorted_result = result.sort_values(["snapshot_time", "event"]).reset_index(
        drop=True
    )
    (
        pd.testing.assert_frame_equal(result, sorted_result),
        "Result df is sorted incorrectly",
    )


def test_no_all_nan_columns(basic_event_log):
    """Test that columns with all NaN values are dropped."""
    result = reshape_for_animations(basic_event_log)

    # Check no column is all NaN
    assert not result.isna().all().any(), (
        "Column that is all NA found - should not be present"
    )


def test_custom_time_column():
    """Test with custom time column name."""
    df = pd.DataFrame(
        {
            "simulation_time": [0, 5, 10],
            "entity_id": [1, 1, 1],
            "event_type": ["arrival_departure", "queue", "arrival_departure"],
            "event": ["arrival", "waiting", "depart"],
        }
    )

    result = reshape_for_animations(df, time_col_name="simulation_time")

    assert isinstance(result, pd.DataFrame), "Result should be a pandas DataFrame"
    assert not result.empty, "Result DataFrame should not be empty"
    assert "simulation_time" in result.columns, "Custom time column name not in output"


def test_custom_entity_column():
    """Test with custom entity column name."""
    df = pd.DataFrame(
        {
            "time": [0, 5, 10],
            "patient_id": [1, 1, 1],
            "event_type": ["arrival_departure", "queue", "arrival_departure"],
            "event": ["arrival", "waiting", "depart"],
        }
    )

    result = reshape_for_animations(df, entity_col_name="patient_id")
    assert isinstance(result, pd.DataFrame), "Result should be a pandas DataFrame"
    assert not result.empty, "Result DataFrame should not be empty"
    assert "patient_id" in result.columns, "Custom entity_id column name not in output"


def test_custom_event_type_column():
    """Test with custom event type column name."""
    df = pd.DataFrame(
        {
            "time": [0, 5, 10],
            "entity_id": [1, 1, 1],
            "category": ["arrival_departure", "queue", "arrival_departure"],
            "event": ["arrival", "waiting", "depart"],
        }
    )

    result = reshape_for_animations(df, event_type_col_name="category")
    assert isinstance(result, pd.DataFrame), "Result should be a pandas DataFrame"
    assert not result.empty, "Result DataFrame should not be empty"
    assert "category" in result.columns, "Custom event_type column name not in output"


def test_custom_event_column():
    """Test with custom event column name."""
    df = pd.DataFrame(
        {
            "time": [0, 5, 10],
            "entity_id": [1, 1, 1],
            "event_type": ["arrival_departure", "queue", "arrival_departure"],
            "action": ["arrival", "waiting", "depart"],
        }
    )

    result = reshape_for_animations(df, event_col_name="action")
    assert isinstance(result, pd.DataFrame), "Result should be a pandas DataFrame"
    assert not result.empty, "Result DataFrame should not be empty"
    assert "action" in result.columns, "Custom event column name not in output"


def test_entity_not_present_before_arrival():
    """Test that entity doesn't appear before arrival time."""
    df = pd.DataFrame(
        {
            "time": [20, 50],
            "entity_id": [1, 1],
            "event_type": ["arrival_departure", "arrival_departure"],
            "event": ["arrival", "depart"],
        }
    )

    result = reshape_for_animations(df, every_x_time_units=10, limit_duration=100)

    # Entity should not appear in snapshot at time 10
    early_snapshot = result[
        (result["snapshot_time"] == 10) & (result["entity_id"] == 1)
    ]
    assert len(early_snapshot) == 0


def test_entity_without_departure_handled():
    """
    Test entities that arrive but don't depart (incomplete journey).
    This is only expected to work if at least one entity completes their journey.
    """
    df = pd.DataFrame(
        {
            "time": [0, 5, 10, 15, 20],
            "entity_id": [1, 1, 1, 2, 2],
            "event_type": [
                "arrival_departure",
                "queue",
                "arrival_departure",
                "arrival_departure",
                "queue",
            ],
            "event": ["arrival", "waiting", "depart", "arrival", "waiting"],
        }
    )

    # No departure event - entity still in system
    result = reshape_for_animations(df, every_x_time_units=10, limit_duration=100)

    # Entity should appear in multiple snapshots even without departure
    entity_snapshots = result[result["entity_id"] == 2]
    assert len(entity_snapshots) > 0


def test_simultaneous_events():
    """Test multiple entities with events at same time."""
    df = pd.DataFrame(
        {
            "time": [10, 10, 10, 10, 10, 10, 18, 19, 20],
            "entity_id": [1, 2, 3, 1, 2, 3, 1, 2, 3],
            "event_type": [
                "arrival_departure",
                "arrival_departure",
                "arrival_departure",
                "queue",
                "queue",
                "queue",
                "arrival_departure",
                "arrival_departure",
                "arrival_departure",
            ],
            "event": [
                "arrival",
                "arrival",
                "arrival",
                "treat",
                "treat",
                "treat",
                "depart",
                "depart",
                "depart",
            ],
        }
    )

    result = reshape_for_animations(df, limit_duration=30)

    # All three entities should appear
    entities_at_10 = (
        result[result["snapshot_time"] == 10]["entity_id"].dropna().unique()
    )
    assert len(entities_at_10) == 3


def test_preserves_original_columns(basic_event_log):
    """Test that original columns are preserved in output."""
    result = reshape_for_animations(basic_event_log)

    # Original columns should be present (except those dropped if all NaN)
    for col in ["entity_id", "event_type", "event"]:
        assert col in result.columns


def test_handles_large_dataset():
    """Test function can handle larger datasets."""
    # Create a moderately large dataset
    n_entities = 1000
    events_per_entity = 10

    times = []
    entity_ids = []
    event_types = []
    events = []

    for entity in range(1, n_entities + 1):
        for i in range(1, events_per_entity + 1):
            times.append(i * (entity + 10))
            entity_ids.append(entity)
            if i == 1:
                event_types.append("arrival_departure")
                events.append("arrival")
            elif i == events_per_entity:
                event_types.append("arrival_departure")
                events.append("depart")
            else:
                event_types.append("queue")
                events.append(f"queue_step_{i}")

    df = pd.DataFrame(
        {
            "time": times,
            "entity_id": entity_ids,
            "event_type": event_types,
            "event": events,
        }
    )

    # Should complete without error
    result = reshape_for_animations(
        df, every_x_time_units=10, limit_duration=max(df["time"])
    )
    assert not result.empty
