"""Tests for `vidigi.analysis.resource_use_intervals`, `_resolve_resource_capacities`
and `resource_utilisation`."""

import warnings

import numpy as np
import pandas as pd
import pytest

from vidigi.analysis import (
    _resolve_resource_capacities,
    resource_use_intervals,
    resource_utilisation,
)
from vidigi.logging import EventLogger, TrialLogger
from vidigi.utils import EventPosition, create_event_position_df


def _trial_df(loggers):
    return TrialLogger(loggers).to_dataframe()


class _Scenario:
    n_cubicles = 3


# --------------------------------------------------------------------------- #
# resource_use_intervals
# --------------------------------------------------------------------------- #


def test_basic_pairing_matches_the_hand_computed_fixture(resource_use_loggers):
    intervals = resource_use_intervals(_trial_df(resource_use_loggers), limit_duration=20)

    rows = {
        (row.run_number, row.resource_id): (row.start, row.end, row.busy_time)
        for row in intervals.itertuples()
    }
    assert rows[(1, 1)] == (0.0, 10.0, 10.0)
    assert rows[(1, 2)] == (0.0, 5.0, 5.0)
    assert rows[(2, 2)] == (0.0, 20.0, 20.0)
    assert rows[(2, 3)] == (5.0, 15.0, 10.0)
    assert (intervals["event"] == "treatment_begins").all()
    assert not intervals["censored"].any()


def test_unclosed_censor_is_the_default(unclosed_resource_use_logger):
    intervals = resource_use_intervals(
        _trial_df([unclosed_resource_use_logger]), limit_duration=20
    )

    assert len(intervals) == 1
    row = intervals.iloc[0]
    assert row["start"] == 15.0
    assert row["end"] == 20.0
    assert row["censored"]
    assert row["busy_time"] == 5.0


def test_unclosed_censor_warns(unclosed_resource_use_logger):
    with pytest.warns(UserWarning, match="still open"):
        resource_use_intervals(_trial_df([unclosed_resource_use_logger]), limit_duration=20)


def test_unclosed_drop_excludes_the_interval_entirely(unclosed_resource_use_logger):
    """Mutation-proof pair with the censor test above: if `unclosed="censor"`
    silently behaved like `"drop"`, both tests would report `busy_time` in a way
    that could be confused - this asserts zero rows survive, not zero busy_time."""
    intervals = resource_use_intervals(
        _trial_df([unclosed_resource_use_logger]), limit_duration=20, unclosed="drop"
    )
    assert intervals.empty


def test_invalid_unclosed_raises(unclosed_resource_use_logger):
    with pytest.raises(ValueError, match="`unclosed`"):
        resource_use_intervals(
            _trial_df([unclosed_resource_use_logger]), limit_duration=20, unclosed="nonsense"
        )


def test_missing_event_type_col_name_raises_a_legible_error(resource_use_loggers):
    with pytest.raises(ValueError, match="`event_type_col_name`"):
        resource_use_intervals(
            _trial_df(resource_use_loggers),
            limit_duration=20,
            event_type_col_name="nonexistent_column",
        )


def test_orphan_end_is_dropped_and_warns():
    logger = EventLogger(run_number=1)
    logger.log_resource_use_end(
        entity_id=1, resource_id=1, time=5.0, event="treatment_ends"
    )

    with pytest.warns(UserWarning, match="had no matching"):
        intervals = resource_use_intervals(_trial_df([logger]), limit_duration=20)

    assert intervals.empty


def test_missing_resource_id_falls_back_to_run_entity_pairing(
    resource_use_no_resource_id_logger,
):
    with pytest.warns(UserWarning, match="falls back to"):
        intervals = resource_use_intervals(
            _trial_df([resource_use_no_resource_id_logger]), limit_duration=20
        )

    assert len(intervals) == 1
    row = intervals.iloc[0]
    assert row["start"] == 0.0
    assert row["end"] == 10.0
    assert row["busy_time"] == 10.0
    assert pd.isna(row["resource_id"])


def test_partially_null_resource_id_raises():
    """One row with a resource_id, one row without, for the same event type -
    pairing on (run, entity) would silently cross physical units, so this must
    raise rather than guess."""
    logger = EventLogger(run_number=1)
    logger.log_resource_use_start(
        entity_id=1, resource_id=1, time=0.0, event="treatment_begins"
    )
    logger.log_event(
        entity_id=2,
        event_type="resource_use",
        event="treatment_begins",
        time=0.0,
        run_number=1,
    )
    logger.log_resource_use_end(
        entity_id=1, resource_id=1, time=10.0, event="treatment_ends"
    )
    logger.log_event(
        entity_id=2,
        event_type="resource_use_end",
        event="treatment_ends",
        time=10.0,
        run_number=1,
    )

    with pytest.raises(ValueError, match="pairing would silently cross"):
        resource_use_intervals(_trial_df([logger]), limit_duration=20)


def test_nan_entity_id_pairs_correctly_instead_of_cross_joining():
    """Regression test: `groupby(group_keys).cumcount()` defaults to `dropna=True`,
    under which every row in a NaN-keyed group gets `occurrence=NaN` - the
    subsequent outer merge then treats `NaN == NaN` as a match, fabricating a
    cross-join. Two starts and two ends sharing entity_id=NaN previously produced
    4 rows (including a bogus interval) instead of the correct 2."""
    log = pd.DataFrame(
        {
            "entity_id": [float("nan")] * 4,
            "event_type": [
                "resource_use",
                "resource_use",
                "resource_use_end",
                "resource_use_end",
            ],
            "event": ["treatment_begins"] * 2 + ["treatment_ends"] * 2,
            "time": [0.0, 2.0, 5.0, 8.0],
            "resource_id": [1, 2, 1, 2],
        }
    )

    intervals = resource_use_intervals(log, limit_duration=20)

    rows = {
        row.resource_id: (row.start, row.end, row.busy_time)
        for row in intervals.itertuples()
    }
    assert rows == {1: (0.0, 5.0, 5.0), 2: (2.0, 8.0, 6.0)}


def test_revisiting_the_same_resource_pairs_both_bouts_correctly():
    """The same entity using the same resource_id twice in one run - the
    `occurrence` key (n-th start with n-th end) is what prevents this from
    becoming a cartesian-product merge; deleting it from the pairing keys
    would cross-join the two bouts into 4 rows with corrupted busy_time."""
    logger = EventLogger(run_number=1)
    logger.log_resource_use_start(
        entity_id=1, resource_id=1, time=0.0, event="treatment_begins"
    )
    logger.log_resource_use_end(
        entity_id=1, resource_id=1, time=5.0, event="treatment_ends"
    )
    logger.log_resource_use_start(
        entity_id=1, resource_id=1, time=10.0, event="treatment_begins"
    )
    logger.log_resource_use_end(
        entity_id=1, resource_id=1, time=18.0, event="treatment_ends"
    )

    intervals = resource_use_intervals(_trial_df([logger]), limit_duration=20)

    assert len(intervals) == 2
    bouts = sorted(zip(intervals["start"], intervals["end"], intervals["busy_time"]))
    assert bouts == [(0.0, 5.0, 5.0), (10.0, 18.0, 8.0)]


def test_busy_time_is_clipped_to_the_window(resource_use_loggers):
    """warm_up=5 truncates resource 1's run-1 interval (0->10) to (5->10)=5;
    resource 2's run-1 interval (0->5) is clipped to nothing, busy_time=0."""
    intervals = resource_use_intervals(
        _trial_df(resource_use_loggers), warm_up=5, limit_duration=20
    )

    run1 = intervals[intervals["run_number"] == 1]
    busy = dict(zip(run1["resource_id"], run1["busy_time"]))
    assert busy[1] == 5.0
    assert busy[2] == 0.0


# --------------------------------------------------------------------------- #
# _resolve_resource_capacities
# --------------------------------------------------------------------------- #


def _intervals(resource_use_loggers):
    return resource_use_intervals(_trial_df(resource_use_loggers), limit_duration=20)


def test_route_a_resource_capacities_dict(resource_use_loggers):
    intervals = _intervals(resource_use_loggers)
    caps = _resolve_resource_capacities(
        intervals, resource_capacities={"treatment_begins": 3}
    )
    assert caps == {"treatment_begins": 3}


def test_route_b_resource_map_and_scenario(resource_use_loggers):
    intervals = _intervals(resource_use_loggers)
    caps = _resolve_resource_capacities(
        intervals,
        scenario=_Scenario(),
        resource_map={"treatment_begins": "n_cubicles"},
    )
    assert caps == {"treatment_begins": 3}


def test_route_c_event_position_df_and_scenario(resource_use_loggers):
    intervals = _intervals(resource_use_loggers)
    epdf = create_event_position_df(
        [EventPosition(event="treatment_begins", x=0, y=0, label="x", resource="n_cubicles")]
    )
    caps = _resolve_resource_capacities(intervals, scenario=_Scenario(), event_position_df=epdf)
    assert caps == {"treatment_begins": 3}


def test_route_d_infer_gives_a_lower_bound_and_warns(resource_use_loggers):
    """Only 2 distinct resource_ids are actually *used* (1 idle in run 2's
    events overall the trial sees resource_ids {1,2,3} across both runs) - the
    fixture uses 3 distinct resource_ids across the whole trial, so infer
    should report 3, not the per-run count."""
    intervals = _intervals(resource_use_loggers)
    with pytest.warns(UserWarning, match="lower bound"):
        caps = _resolve_resource_capacities(intervals, capacity="infer")
    assert caps == {"treatment_begins": 3}


def test_route_a_takes_precedence_over_scenario_routes(resource_use_loggers):
    """Precedence order A > B > C > D - resource_capacities wins even if a
    scenario/resource_map is also (redundantly) supplied."""
    intervals = _intervals(resource_use_loggers)
    caps = _resolve_resource_capacities(
        intervals,
        resource_capacities={"treatment_begins": 99},
        scenario=_Scenario(),
        resource_map={"treatment_begins": "n_cubicles"},
    )
    assert caps == {"treatment_begins": 99}


def test_route_b_takes_precedence_over_route_c(resource_use_loggers):
    """Precedence order also holds between B and C specifically, not just
    "A beats everything" - resource_map wins over event_position_df when both
    are (redundantly) supplied alongside scenario."""
    intervals = _intervals(resource_use_loggers)

    class _TwoAttrScenario:
        n_cubicles = 3
        n_beds = 7

    epdf = create_event_position_df(
        [EventPosition(event="treatment_begins", x=0, y=0, label="x", resource="n_cubicles")]
    )
    caps = _resolve_resource_capacities(
        intervals,
        scenario=_TwoAttrScenario(),
        resource_map={"treatment_begins": "n_beds"},
        event_position_df=epdf,
    )
    assert caps == {"treatment_begins": 7}


def test_scenario_without_a_mapping_source_raises(resource_use_loggers):
    intervals = _intervals(resource_use_loggers)
    with pytest.raises(ValueError, match="resource_map"):
        _resolve_resource_capacities(intervals, scenario=_Scenario())


def test_resource_map_naming_a_missing_attribute_raises(resource_use_loggers):
    intervals = _intervals(resource_use_loggers)
    with pytest.raises(AttributeError, match="n_cubicles") as excinfo:
        _resolve_resource_capacities(
            intervals,
            scenario=_Scenario(),
            resource_map={"treatment_begins": "n_beds"},
        )
    assert "n_beds" in str(excinfo.value)
    assert "treatment_begins" in str(excinfo.value)
    assert "n_cubicles" in str(excinfo.value)  # listed among available attributes


def test_step_with_no_capacity_warns_and_is_nan(resource_use_loggers):
    intervals = _intervals(resource_use_loggers)
    with pytest.warns(UserWarning, match="No capacity given"):
        caps = _resolve_resource_capacities(intervals, resource_capacities={})
    assert np.isnan(caps["treatment_begins"])


def test_capacity_for_a_step_not_in_the_log_warns():
    logger = EventLogger(run_number=1)
    logger.log_resource_use_start(
        entity_id=1, resource_id=1, time=0.0, event="treatment_begins"
    )
    logger.log_resource_use_end(
        entity_id=1, resource_id=1, time=10.0, event="treatment_ends"
    )
    intervals = resource_use_intervals(_trial_df([logger]), limit_duration=20)

    with pytest.warns(UserWarning, match="do not appear in the log"):
        _resolve_resource_capacities(
            intervals, resource_capacities={"treatment_begins": 3, "typo_step": 5}
        )


def test_nothing_given_returns_an_empty_mapping(resource_use_loggers):
    intervals = _intervals(resource_use_loggers)
    assert _resolve_resource_capacities(intervals) == {}


# --------------------------------------------------------------------------- #
# resource_utilisation
# --------------------------------------------------------------------------- #


def test_by_resource_gives_the_full_hand_computed_dict(resource_use_loggers):
    result = resource_utilisation(
        _trial_df(resource_use_loggers),
        by="resource",
        resource_capacities={"treatment_begins": 3},
        limit_duration=20,
    )

    run1 = result[result["run_number"] == 1]
    run2 = result[result["run_number"] == 2]

    assert dict(zip(run1["resource_id"], run1["busy_time"])) == {1: 10.0, 2: 5.0, 3: 0.0}
    assert dict(zip(run2["resource_id"], run2["busy_time"])) == {1: 0.0, 2: 20.0, 3: 10.0}
    # capacity is always 1 per physical unit
    assert (result["capacity"] == 1.0).all()
    assert dict(zip(run1["resource_id"], run1["mean_in_use"])) == {1: 0.5, 2: 0.25, 3: 0.0}


def test_resource_idle_in_one_run_but_used_in_another_reports_a_genuine_zero(
    resource_use_loggers,
):
    """Resource 3 never appears in run 1's log at all - proves it is filled as
    a real zero, not simply absent, the same convention as
    `queue_size_over_time`."""
    result = resource_utilisation(_trial_df(resource_use_loggers), by="resource", limit_duration=20)

    run1_resource_3 = result[(result["run_number"] == 1) & (result["resource_id"] == 3)]
    assert len(run1_resource_3) == 1
    assert run1_resource_3.iloc[0]["busy_time"] == 0.0


def test_by_resource_with_missing_resource_id_pools_into_one_row_per_run_and_warns():
    """Regression test: `by="resource"` used to `.dropna()` the (entirely null)
    resource_id column when building the group index, leaving zero groups and
    silently returning zero rows - reading as "no resource use happened"
    rather than "no per-unit breakdown is available". One pooled row per run
    is what the "genuine zero, not a missing row" convention actually
    requires here."""
    logger = EventLogger(run_number=1)
    logger.log_event(
        entity_id=1,
        event_type="resource_use",
        event="treatment_begins",
        time=0.0,
        run_number=1,
    )
    logger.log_event(
        entity_id=1,
        event_type="resource_use_end",
        event="treatment_ends",
        time=10.0,
        run_number=1,
    )

    with pytest.warns(UserWarning, match="reporting one pooled row per run"):
        result = resource_utilisation(_trial_df([logger]), by="resource", limit_duration=20)

    assert len(result) == 1
    assert result.iloc[0]["busy_time"] == 10.0
    assert result.iloc[0]["utilisation"] == 0.5


def test_by_step_matches_the_summed_busy_time(resource_use_loggers):
    result = resource_utilisation(
        _trial_df(resource_use_loggers),
        by="step",
        resource_capacities={"treatment_begins": 3},
        limit_duration=20,
    )

    by_run = dict(zip(result["run_number"], result["busy_time"]))
    assert by_run == {1: 15.0, 2: 30.0}
    by_run_util = dict(zip(result["run_number"], result["utilisation"]))
    assert by_run_util == pytest.approx({1: 0.25, 2: 0.5})


def test_by_run_matches_by_step_when_only_one_step_exists(resource_use_loggers):
    """With a single resource-use step, `by="run"` (pooling everything) and
    `by="step"` (one row per step) must agree exactly."""
    by_run = resource_utilisation(
        _trial_df(resource_use_loggers),
        by="run",
        resource_capacities={"treatment_begins": 3},
        limit_duration=20,
    )
    by_step = resource_utilisation(
        _trial_df(resource_use_loggers),
        by="step",
        resource_capacities={"treatment_begins": 3},
        limit_duration=20,
    )

    assert list(by_run["busy_time"]) == list(by_step["busy_time"])
    assert list(by_run["utilisation"]) == list(by_step["utilisation"])


def test_by_run_capacity_is_the_sum_of_every_pooled_step_and_warns():
    """Two different steps pooled under one "run" row - `capacity` is the SUM
    of both steps' capacities (1 + 3 = 4), not one arbitrarily chosen value:
    triage busy=5, treatment busy=5, total busy=10, mean_in_use=10/20=0.5,
    utilisation=0.5/4=0.125. Pooling more than one distinct step also warns,
    since a blended figure across resource types is rarely what a
    capacity-planning question wants."""
    logger = EventLogger(run_number=1)
    logger.log_resource_use_start(
        entity_id=1, resource_id=1, time=0.0, event="triage_begins"
    )
    logger.log_resource_use_end(
        entity_id=1, resource_id=1, time=5.0, event="triage_ends"
    )
    logger.log_resource_use_start(
        entity_id=2, resource_id=2, time=0.0, event="treatment_begins"
    )
    logger.log_resource_use_end(
        entity_id=2, resource_id=2, time=5.0, event="treatment_ends"
    )

    with pytest.warns(UserWarning, match="pooling 2 distinct steps"):
        result = resource_utilisation(
            _trial_df([logger]),
            by="run",
            resource_capacities={"triage_begins": 1, "treatment_begins": 3},
            limit_duration=20,
        )

    assert result.iloc[0]["busy_time"] == 10.0
    assert result.iloc[0]["capacity"] == 4.0
    assert result.iloc[0]["utilisation"] == pytest.approx(0.125)


def test_by_run_capacity_is_nan_when_any_pooled_step_has_no_capacity():
    """If even one of the pooled steps has an unresolved capacity, the summed
    total must propagate NaN rather than silently summing only the known
    ones - a partial sum would understate the true (unknown) total capacity."""
    logger = EventLogger(run_number=1)
    logger.log_resource_use_start(
        entity_id=1, resource_id=1, time=0.0, event="triage_begins"
    )
    logger.log_resource_use_end(
        entity_id=1, resource_id=1, time=5.0, event="triage_ends"
    )
    logger.log_resource_use_start(
        entity_id=2, resource_id=2, time=0.0, event="treatment_begins"
    )
    logger.log_resource_use_end(
        entity_id=2, resource_id=2, time=5.0, event="treatment_ends"
    )

    with pytest.warns(UserWarning):
        result = resource_utilisation(
            _trial_df([logger]),
            by="run",
            resource_capacities={"triage_begins": 1},
            limit_duration=20,
        )

    assert np.isnan(result.iloc[0]["utilisation"])


def test_by_run_does_not_warn_when_only_one_step_is_pooled(resource_use_loggers):
    """The "blended figure" warning is about pooling *distinct* steps - a
    single-step system (this fixture) must not trigger it."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        resource_utilisation(
            _trial_df(resource_use_loggers),
            by="run",
            resource_capacities={"treatment_begins": 3},
            limit_duration=20,
        )


def test_no_capacity_given_leaves_utilisation_nan_but_mean_in_use_intact(
    resource_use_loggers,
):
    """`by="step"` has no built-in capacity - unlike `by="resource"`, where a
    single physical unit's own capacity is always 1 regardless of what the
    caller supplies."""
    result = resource_utilisation(_trial_df(resource_use_loggers), by="step", limit_duration=20)

    assert result["utilisation"].isna().all()
    assert not result["mean_in_use"].isna().any()


def test_by_resource_capacity_is_always_one_regardless_of_capacity_routes(
    resource_use_loggers,
):
    """None of the four capacity routes are keyed by resource_id, so
    `by="resource"` utilisation is always `mean_in_use / 1` - this must hold
    whether or not a capacity route is supplied."""
    without_route = resource_utilisation(
        _trial_df(resource_use_loggers), by="resource", limit_duration=20
    )
    with_route = resource_utilisation(
        _trial_df(resource_use_loggers),
        by="resource",
        resource_capacities={"treatment_begins": 3},
        limit_duration=20,
    )

    assert (without_route["capacity"] == 1.0).all()
    assert (with_route["capacity"] == 1.0).all()
    assert list(without_route["utilisation"]) == list(without_route["mean_in_use"])


def test_invalid_by_raises(resource_use_loggers):
    with pytest.raises(ValueError, match="`by`"):
        resource_utilisation(_trial_df(resource_use_loggers), by="nonsense", limit_duration=20)


def test_warm_up_reduces_mean_in_use(resource_use_loggers):
    full = resource_utilisation(
        _trial_df(resource_use_loggers), by="resource", limit_duration=20
    )
    trimmed = resource_utilisation(
        _trial_df(resource_use_loggers), by="resource", warm_up=5, limit_duration=20
    )

    full_r1 = dict(zip(full[full["run_number"] == 1]["resource_id"], full[full["run_number"] == 1]["busy_time"]))
    trimmed_r1 = dict(
        zip(
            trimmed[trimmed["run_number"] == 1]["resource_id"],
            trimmed[trimmed["run_number"] == 1]["busy_time"],
        )
    )
    assert full_r1[1] == 10.0
    assert trimmed_r1[1] == 5.0


def test_utilisation_over_one_warns(resource_use_loggers):
    """Capacity given as 1 when 3 units were genuinely observed busy at once in
    run 2 (busy_time=30 over a 20-length window means mean_in_use=1.5) is
    always a sign of a data or configuration problem - never a valid
    steady-state reading - so it should be surfaced immediately rather than
    only visually once a plotting layer exists."""
    with pytest.warns(UserWarning, match="utilisation over 1"):
        resource_utilisation(
            _trial_df(resource_use_loggers),
            by="run",
            resource_capacities={"treatment_begins": 1},
            limit_duration=20,
        )


def test_warm_up_equal_to_limit_duration_raises(resource_use_loggers):
    """A zero-length window would otherwise divide by zero silently
    (`mean_in_use = busy_time / 0`), giving a NaN with no explanation."""
    with pytest.raises(ValueError, match="zero length"):
        resource_utilisation(
            _trial_df(resource_use_loggers), by="resource", warm_up=20, limit_duration=20
        )
