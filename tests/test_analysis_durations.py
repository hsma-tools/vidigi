"""Tests for `vidigi.analysis.event_durations`."""

import pandas as pd
import pytest

from vidigi.analysis import event_durations


def _rows(*specs):
    """Build a minimal event log from (entity_id, event, time) tuples."""
    return pd.DataFrame(
        [
            {"entity_id": entity_id, "event": event, "time": time}
            for entity_id, event, time in specs
        ]
    )


def test_basic_pairing_no_run_or_pathway_column(resource_log):
    result = event_durations(resource_log, "treatment_begins", "treatment_ends")

    assert list(result["entity_id"]) == [1, 2]
    assert list(result["occurrence"]) == [0, 0]
    assert list(result["first_time"]) == [10, 30]
    assert list(result["second_time"]) == [30, 50]
    assert list(result["duration"]) == [20, 20]
    assert result["run_number"].isna().all()
    assert result["pathway"].isna().all()


@pytest.mark.parametrize(
    "match,expected",
    [
        ("first", [4]),
        ("last", [10]),
        ("occurrence", [4, 10]),
    ],
)
def test_match_modes_on_rework_loop(rework_loop_logger, match, expected):
    df = rework_loop_logger.to_dataframe()
    result = event_durations(df, "assessment", "treated", match=match)
    assert sorted(result["duration"].tolist()) == expected


def test_occurrence_match_preserves_pairing_order(rework_loop_logger):
    df = rework_loop_logger.to_dataframe()
    result = event_durations(df, "assessment", "treated", match="occurrence")

    assert list(result["occurrence"]) == [0, 1]
    assert list(result["first_time"]) == [1.0, 20.0]
    assert list(result["second_time"]) == [5.0, 30.0]
    assert list(result["duration"]) == [4.0, 10.0]


def test_outer_join_keeps_both_directions_of_incompleteness():
    log = _rows(
        ("A", "start", 1),  # started, never finished
        ("B", "end", 5),  # finished, never started
        ("C", "start", 2),
        ("C", "end", 8),
    )
    result = event_durations(log, "start", "end").set_index("entity_id")

    assert result.loc["A", "first_time"] == 1
    assert pd.isna(result.loc["A", "second_time"])
    assert pd.isna(result.loc["A", "duration"])

    assert pd.isna(result.loc["B", "first_time"])
    assert result.loc["B", "second_time"] == 5
    assert pd.isna(result.loc["B", "duration"])

    assert result.loc["C", "first_time"] == 2
    assert result.loc["C", "second_time"] == 8
    assert result.loc["C", "duration"] == 6


def test_keep_incomplete_false_drops_unmatched_rows():
    log = _rows(
        ("A", "start", 1),
        ("B", "end", 5),
        ("C", "start", 2),
        ("C", "end", 8),
    )
    result = event_durations(log, "start", "end", keep_incomplete=False)

    assert list(result["entity_id"]) == ["C"]
    assert list(result["duration"]) == [6]


def test_run_column_keeps_pairing_within_each_run():
    log = pd.DataFrame(
        [
            {"entity_id": 1, "event": "start", "time": 1, "run": 1},
            {"entity_id": 1, "event": "end", "time": 3, "run": 1},
            {"entity_id": 1, "event": "start", "time": 100, "run": 2},
            {"entity_id": 1, "event": "end", "time": 104, "run": 2},
        ]
    )
    result = event_durations(log, "start", "end").sort_values("run_number")

    assert list(result["run_number"]) == [1, 2]
    assert list(result["duration"]) == [2, 4]


def test_no_run_column_fills_run_number_with_na():
    log = _rows(("A", "start", 1), ("A", "end", 3))
    result = event_durations(log, "start", "end")
    assert result["run_number"].isna().all()


def test_explicit_pathway_column_carried_through():
    log = pd.DataFrame(
        [
            {"entity_id": 1, "event": "start", "time": 1, "route": "fast"},
            {"entity_id": 1, "event": "end", "time": 3, "route": "fast"},
        ]
    )
    result = event_durations(log, "start", "end", pathway_col_name="route")
    assert list(result["pathway"]) == ["fast"]


def test_explicit_pathway_column_missing_raises():
    log = _rows(("A", "start", 1), ("A", "end", 3))
    with pytest.raises(ValueError, match="pathway_col_name"):
        event_durations(log, "start", "end", pathway_col_name="route")


def test_default_pathway_column_absent_is_tolerated():
    log = _rows(("A", "start", 1), ("A", "end", 3))
    result = event_durations(log, "start", "end")
    assert result["pathway"].isna().all()


def test_same_event_twice_raises():
    log = _rows(("A", "start", 1))
    with pytest.raises(ValueError, match="are both 'start'"):
        event_durations(log, "start", "start")


def test_unknown_event_raises_with_suggestion():
    log = _rows(("A", "treatment_begins", 1), ("A", "treatment_ends", 5))
    with pytest.raises(ValueError, match="treatment_begin.*did you mean"):
        event_durations(log, "treatment_begin", "treatment_ends")


def test_occurrence_match_warns_on_unequal_counts():
    log = _rows(
        ("A", "start", 1),
        ("A", "start", 2),
        ("A", "end", 3),
    )
    with pytest.warns(UserWarning, match="unequal counts"):
        result = event_durations(log, "start", "end", match="occurrence")

    assert len(result) == 2
    matched = result[result["occurrence"] == 0].iloc[0]
    assert matched["duration"] == 2
    unmatched = result[result["occurrence"] == 1].iloc[0]
    assert pd.isna(unmatched["second_time"])
