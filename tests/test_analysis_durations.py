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


@pytest.mark.parametrize(
    "match,expected",
    [
        ("first", [5.0]),
        ("last", [6.0]),
        ("occurrence", [5.0, 6.0]),
    ],
)
def test_nan_entity_id_pairs_correctly_instead_of_cross_joining(match, expected):
    """Regression test: `groupby(...).cumcount()`/`.head(1)`/`.tail(1)` default to
    `dropna=True`, under which every row in a NaN-keyed group gets `occurrence=NaN`
    (cumcount) or is silently dropped entirely (head/tail) - pandas' `merge` then
    treats `NaN == NaN` as a match, so two starts and two ends with the same NaN
    entity_id previously merged into a spurious 4-row cross-join for
    `match="occurrence"`, and the entity vanished entirely for `match="first"`/
    `"last"`. An entity with no ID is unusual but not something that should
    fabricate or silently drop data.
    """
    log = pd.DataFrame(
        {
            "entity_id": [float("nan")] * 4,
            "event": ["a", "a", "b", "b"],
            "time": [0.0, 2.0, 5.0, 8.0],
        }
    )

    result = event_durations(log, "a", "b", match=match)

    assert list(result["duration"]) == expected


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


# --------------------------------------------------------------------------- #
# Parity with the old pivot-based calculation, on raw event logs
# --------------------------------------------------------------------------- #


def _pivot_duration_reference(event_log, first_event, second_event, run_col=None):
    """Generalisation of the old `pivot`-based calculation, for parity testing only.

    Same shape as the pivot previously inlined in `get_event_duration_stat`, just
    parameterised over an optional run column so it can be run directly against
    conftest's raw event-log fixtures rather than only `TrialLogger` output.
    """
    index_cols = ["entity_id"] + ([run_col] if run_col else [])
    event_df = event_log[event_log["event"].isin([first_event, second_event])][
        index_cols + ["event", "time"]
    ].copy()
    pivoted = event_df.pivot(
        columns="event", index=index_cols, values="time"
    ).reset_index()
    pivoted["duration"] = pivoted[second_event] - pivoted[first_event]
    return pivoted.sort_values(index_cols).reset_index(drop=True)


@pytest.mark.parametrize(
    "fixture_name,run_col",
    [
        ("simple_queue_log", None),
        ("overflow_queue_log", None),
        ("warm_up_log", None),
        ("multi_run_log", "run"),
    ],
)
def test_event_durations_matches_the_old_pivot_on_raw_logs(
    fixture_name, run_col, request
):
    """Parity check against every raw-log fixture where every entity visits
    'arrival'/'depart' at most once - including one with a run column spelled
    plain 'run' rather than 'run_number', to pin `run_col_name="auto"` detection
    against the same reference.
    """
    event_log = request.getfixturevalue(fixture_name)

    old = _pivot_duration_reference(event_log, "arrival", "depart", run_col=run_col)
    new = (
        event_durations(event_log, "arrival", "depart")
        .rename(columns={"run_number": run_col} if run_col else {})
        .sort_values(["entity_id"] + ([run_col] if run_col else []))
        .reset_index(drop=True)
    )

    assert list(new["entity_id"]) == list(old["entity_id"])
    if run_col:
        assert list(new[run_col]) == list(old[run_col])
    pd.testing.assert_series_equal(
        new["duration"], old["duration"], check_names=False
    )


def test_event_absent_from_the_whole_log_raises_clearly_on_both(no_departure_log):
    """When an event never occurs anywhere in the log - as opposed to some
    entities simply never reaching it - `event_durations` treats it as almost
    certainly a typo'd argument and raises `ValueError` naming it, rather than
    silently returning every entity as unserved.

    The old pivot-based calculation also failed here, but with an opaque
    `KeyError` for a column that was never going to exist, giving no hint the
    problem was the event name rather than the data.
    """
    with pytest.raises(KeyError):
        _pivot_duration_reference(no_departure_log, "arrival", "depart")

    with pytest.raises(ValueError, match="'depart'"):
        event_durations(no_departure_log, "arrival", "depart")


# --------------------------------------------------------------------------- #
# warm_up
# --------------------------------------------------------------------------- #


def test_warm_up_default_is_a_verified_no_op():
    log = _rows(("A", "start", 0), ("A", "end", 5), ("B", "start", 10), ("B", "end", 12))

    with_default = event_durations(log, "start", "end")
    explicit_zero = event_durations(log, "start", "end", warm_up=0)

    pd.testing.assert_frame_equal(with_default, explicit_zero)


def test_warm_up_excludes_pairings_that_started_before_it():
    log = _rows(
        ("A", "start", 0),
        ("A", "end", 5),
        ("B", "start", 10),
        ("B", "end", 12),
        ("C", "start", 20),
        ("C", "end", 25),
    )

    result = event_durations(log, "start", "end", warm_up=10)

    assert sorted(result["entity_id"]) == ["B", "C"]


def test_warm_up_boundary_is_inclusive():
    """A pairing starting *exactly* on the boundary is kept (`>=`, not `>`) -
    mutation-proven below."""
    log = _rows(("A", "start", 10), ("A", "end", 15))

    result = event_durations(log, "start", "end", warm_up=10)

    assert list(result["entity_id"]) == ["A"]


def test_warm_up_does_not_exclude_a_pairing_with_no_first_time():
    """An `end` with no matching `start` has a `NaN` `first_time` - there is no
    time to compare against `warm_up`, so it must survive regardless. `B` gives
    `"start"` a genuine occurrence in the log so the event-presence check passes;
    it starts and ends after `warm_up` and is unaffected."""
    log = _rows(("A", "end", 5), ("B", "start", 200), ("B", "end", 205))

    result = event_durations(log, "start", "end", warm_up=100)

    a = result.set_index("entity_id").loc["A"]
    assert pd.isna(a["first_time"])
    assert a["second_time"] == 5


def test_warm_up_combines_with_keep_incomplete_false():
    log = _rows(
        ("A", "start", 0),  # before warm_up - excluded regardless
        ("B", "start", 10),  # after warm_up, never finishes - excluded by keep_incomplete
        ("C", "start", 20),
        ("C", "end", 25),
    )

    result = event_durations(log, "start", "end", warm_up=10, keep_incomplete=False)

    assert list(result["entity_id"]) == ["C"]


def test_warm_up_filters_per_occurrence_not_per_entity(rework_loop_logger):
    """Entity 1 hits `assessment` at t=1 and t=20, `treated` at t=5 and t=30.
    With `match='occurrence'` and `warm_up=10`, the first pairing (started at
    t=1) is excluded while the second (started at t=20) survives - proof the
    filter applies per pairing, not by dropping the whole entity."""
    df = rework_loop_logger.to_dataframe()

    result = event_durations(df, "assessment", "treated", match="occurrence", warm_up=10)

    assert list(result["duration"]) == [10.0]


def test_negative_warm_up_raises():
    log = _rows(("A", "start", 0), ("A", "end", 5))
    with pytest.raises(ValueError, match="warm_up"):
        event_durations(log, "start", "end", warm_up=-1)
