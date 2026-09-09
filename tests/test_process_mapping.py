"""Tests for discarding a warm-up period before building a process map.

`process_mapping` had no dedicated test file before this one - the module was
entirely uncovered.

This file covers only `warm_up`, added to `add_sim_timestamp` and threaded
through `EventLogger.generate_dfg`. It is deliberately a plain time-based
filter rather than a port of `reshape_for_animations`' `warm_up`: `discover_dfg`
builds each case's edges from its own consecutive rows, not by reconstructing
who was present at a given moment from arrival/departure rows, so dropping
early rows here cannot make a case vanish from output it should still appear
in the way it could for the animation. The tests below exist to pin exactly
what a case straddling the cutoff loses, and to prove the parameter is a
drop-in replacement for the manual filter it was added to replace.
"""

import pandas as pd
import pytest

from pandas.testing import assert_frame_equal

from vidigi.analysis import activity_occupancy_stats
from vidigi.logging import EventLogger
from vidigi.process_mapping import (
    _transitions,
    add_sim_timestamp,
    dfg_to_graphviz,
    discover_dfg,
    process_nodes_and_edges_for_cytoscape,
)


def _log(*specs):
    """Build a minimal event log from (time, entity_id, event) tuples."""
    return pd.DataFrame(specs, columns=["time", "entity_id", "event"])


@pytest.fixture
def straddling_log():
    """Three cases positioned around a warm_up=100 cutoff.

    - Entity 1 straddles it: queues at 50 (pre-cutoff), treated at 120,
      departs at 150.
    - Entity 2 is entirely pre-cutoff and should disappear completely.
    - Entity 3 is entirely post-cutoff and should be unaffected.
    """
    return _log(
        (50, 1, "waiting"),
        (120, 1, "treatment"),
        (150, 1, "depart"),
        (10, 2, "waiting"),
        (40, 2, "depart"),
        (110, 3, "waiting"),
        (140, 3, "depart"),
    )


# --------------------------------------------------------------------------- #
# add_sim_timestamp: the filter itself
# --------------------------------------------------------------------------- #


def test_warm_up_default_is_a_true_noop(straddling_log):
    """The default must be identical output, not merely similar."""
    default = add_sim_timestamp(straddling_log)
    explicit = add_sim_timestamp(straddling_log, warm_up=None)

    assert default.equals(explicit)


def test_warm_up_drops_rows_at_or_before_the_threshold(straddling_log):
    """The boundary itself is dropped, matching `time > warm_up`."""
    log = _log((100, 1, "on_the_boundary"), (101, 1, "just_after"))

    result = add_sim_timestamp(log, warm_up=100)

    assert list(result["event"]) == ["just_after"]


def test_warm_up_matches_manually_filtering_before_conversion(straddling_log):
    """Proves the parameter is a drop-in replacement for the taught workaround.

    The recipe being replaced is:
        filtered = event_log[event_log["time"] > warm_up]
        filtered_with_timestamp = add_sim_timestamp(filtered)
    """
    via_parameter = add_sim_timestamp(straddling_log, warm_up=100)

    manually_filtered = straddling_log[straddling_log["time"] > 100]
    via_manual_filter = add_sim_timestamp(manually_filtered)

    assert via_parameter.equals(via_manual_filter)


def test_negative_warm_up_raises(straddling_log):
    with pytest.raises(ValueError, match="must not be negative"):
        add_sim_timestamp(straddling_log, warm_up=-10)


# --------------------------------------------------------------------------- #
# Consequences downstream in discover_dfg - the behaviour worth knowing about
# before relying on this for reporting.
# --------------------------------------------------------------------------- #


def _edge_set(edges):
    return set(zip(edges["source"], edges["target"]))


def test_case_entirely_within_warm_up_is_dropped_completely(straddling_log):
    """Entity 2 (waiting at 10, depart at 40) contributes nothing at all.

    Both entity 2 and entity 3 produce a waiting -> depart edge, so this only
    proves entity 2 is gone by checking the frequency drops from 2 to 1 rather
    than just checking the edge is still present.
    """
    unfiltered = add_sim_timestamp(straddling_log)
    _, edges_unfiltered = discover_dfg(unfiltered)
    unfiltered_frequency = edges_unfiltered.loc[
        (edges_unfiltered["source"] == "waiting")
        & (edges_unfiltered["target"] == "depart"),
        "frequency",
    ].item()
    assert unfiltered_frequency == 2  # entities 2 and 3 both contribute this edge

    filtered = add_sim_timestamp(straddling_log, warm_up=100)
    _, edges_filtered = discover_dfg(filtered)
    filtered_frequency = edges_filtered.loc[
        (edges_filtered["source"] == "waiting")
        & (edges_filtered["target"] == "depart"),
        "frequency",
    ].item()
    assert filtered_frequency == 1  # only entity 3 remains


def test_case_straddling_the_cutoff_loses_the_boundary_edge(straddling_log):
    """The edge connecting entity 1's pre- and post-cutoff events must not
    appear, since one side of that pair is no longer in the log."""
    unfiltered = add_sim_timestamp(straddling_log)
    _, edges_unfiltered = discover_dfg(unfiltered)
    assert ("waiting", "treatment") in _edge_set(edges_unfiltered)

    filtered = add_sim_timestamp(straddling_log, warm_up=100)
    _, edges_filtered = discover_dfg(filtered)
    assert ("waiting", "treatment") not in _edge_set(edges_filtered)


# --------------------------------------------------------------------------- #
# EventLogger.generate_dfg: the convenience wrapper most users call
# --------------------------------------------------------------------------- #


@pytest.fixture
def straddling_logger():
    logger = EventLogger(run_number=1)
    logger.log_arrival(entity_id=1, time=50.0)
    logger.log_queue(entity_id=1, event="waiting", time=50.0)
    logger.log_queue(entity_id=1, event="treatment", time=120.0)
    logger.log_departure(entity_id=1, time=150.0)

    logger.log_arrival(entity_id=2, time=10.0)
    logger.log_departure(entity_id=2, time=40.0)
    return logger


def test_generate_dfg_threads_warm_up_through_to_add_sim_timestamp(
    straddling_logger, monkeypatch
):
    """`generate_dfg` must not silently drop the argument on the floor.

    Spies on `add_sim_timestamp` rather than parsing the rendered graph
    object, since `output_format` returns a Graphviz/Cytoscape object with no
    stable, parseable representation of the edges it was built from.
    """
    calls = []
    import vidigi.logging as logging_module

    real_add_sim_timestamp = logging_module.add_sim_timestamp

    def spy(*args, **kwargs):
        calls.append(kwargs.get("warm_up"))
        return real_add_sim_timestamp(*args, **kwargs)

    monkeypatch.setattr(logging_module, "add_sim_timestamp", spy)

    straddling_logger.generate_dfg(warm_up=100)

    assert calls == [100]


def test_generate_dfg_default_does_not_filter(straddling_logger, monkeypatch):
    calls = []
    import vidigi.logging as logging_module

    real_add_sim_timestamp = logging_module.add_sim_timestamp

    def spy(*args, **kwargs):
        calls.append(kwargs.get("warm_up"))
        return real_add_sim_timestamp(*args, **kwargs)

    monkeypatch.setattr(logging_module, "add_sim_timestamp", spy)

    straddling_logger.generate_dfg()

    assert calls == [None]


# --------------------------------------------------------------------------- #
# Occupancy metrics on the nodes (issue #176)
#
# `activity_occupancy_stats` itself is covered in test_analysis_activity_occupancy.py;
# these pin how its output is merged onto the node table and rendered.
# --------------------------------------------------------------------------- #


@pytest.fixture
def occupancy_logger():
    """One run: two entities queue ('waiting') then hold a resource ('in_service').

    With ``every_x_time_units=5``, ``limit_duration=20`` the snapshots are
    0, 5, 10, 15, 20 and both steps hold two entities at their peak:

    - ``waiting``:    counts [2, 2, 0, 0, 0] -> mean 0.8, min 0, max 2, median 0
    - ``in_service``: counts [0, 0, 2, 2, 0] -> mean 0.8, min 0, max 2, median 0
    """
    logger = EventLogger(run_number=1)
    for entity_id in (1, 2):
        logger.log_arrival(entity_id=entity_id, time=0.0)
        logger.log_queue(entity_id=entity_id, event="waiting", time=0.0)
        logger.log_resource_use_start(
            entity_id=entity_id, resource_id=entity_id, time=10.0, event="in_service"
        )
        logger.log_resource_use_end(
            entity_id=entity_id, resource_id=entity_id, time=20.0, event="done"
        )
        logger.log_departure(entity_id=entity_id, time=20.0)
    return logger


def _stats(logger):
    return activity_occupancy_stats(
        logger.to_dataframe(), every_x_time_units=5, limit_duration=20
    )


def _col_map(nodes, col):
    return {
        activity: (None if pd.isna(value) else value)
        for activity, value in zip(nodes["activity"], nodes[col])
    }


def test_occupancy_stats_merge_onto_the_right_nodes(occupancy_logger):
    df = occupancy_logger.to_dataframe()
    nodes, _ = discover_dfg(
        add_sim_timestamp(df), occupancy_stats=_stats(occupancy_logger)
    )

    # Only the queue and resource steps get a figure; arrival/depart/the
    # resource_use_end label are left NaN, not zero-filled or dropped.
    assert _col_map(nodes, "kind") == {
        "arrival": None,
        "depart": None,
        "done": None,
        "waiting": "queue",
        "in_service": "resource",
    }
    assert _col_map(nodes, "max_occupancy") == {
        "arrival": None,
        "depart": None,
        "done": None,
        "waiting": 2.0,
        "in_service": 2.0,
    }


def test_discover_dfg_without_occupancy_stats_leaves_nodes_unchanged(occupancy_logger):
    nodes, _ = discover_dfg(add_sim_timestamp(occupancy_logger.to_dataframe()))
    assert list(nodes.columns) == ["activity", "count"]


def test_dfg_to_graphviz_shows_occupancy_only_when_asked(occupancy_logger):
    df = occupancy_logger.to_dataframe()
    nodes, edges = discover_dfg(
        add_sim_timestamp(df), occupancy_stats=_stats(occupancy_logger)
    )

    shown = dfg_to_graphviz(nodes.copy(), edges.copy(), show_occupancy=True).source
    assert "avg queued 0.8 (min 0.0, max 2.0)" in shown
    assert "avg in use 0.8 (min 0.0, max 2.0)" in shown

    hidden = dfg_to_graphviz(nodes.copy(), edges.copy(), show_occupancy=False).source
    assert "avg queued" not in hidden
    assert "avg in use" not in hidden


def test_cytoscape_elements_show_occupancy_in_the_node_label(occupancy_logger):
    df = occupancy_logger.to_dataframe()
    nodes, edges = discover_dfg(
        add_sim_timestamp(df), occupancy_stats=_stats(occupancy_logger)
    )

    cy_nodes, _ = process_nodes_and_edges_for_cytoscape(
        nodes, edges, show_occupancy=True
    )
    labels = {n["data"]["id"]: n["data"]["label"] for n in cy_nodes}

    assert "avg queued 0.8 (min 0.0, max 2.0)" in labels["waiting"]
    assert "avg in use 0.8 (min 0.0, max 2.0)" in labels["in_service"]


def test_renderers_do_not_break_on_a_plain_node_table(straddling_logger):
    """A node table with no occupancy columns must not KeyError under the
    default ``show_occupancy=True``."""
    nodes, edges = discover_dfg(add_sim_timestamp(straddling_logger.to_dataframe()))

    dfg_to_graphviz(nodes.copy(), edges.copy(), show_occupancy=True)
    process_nodes_and_edges_for_cytoscape(nodes, edges, show_occupancy=True)


def test_generate_dfg_occupancy_metrics_end_to_end(occupancy_logger):
    graph = occupancy_logger.generate_dfg(occupancy_metrics=True)

    assert "avg queued" in graph.source
    assert "avg in use" in graph.source


def test_generate_dfg_default_has_no_occupancy(occupancy_logger):
    graph = occupancy_logger.generate_dfg()
    assert "avg queued" not in graph.source


def test_generate_dfg_occupancy_uses_the_raw_log_and_threads_warm_up(
    occupancy_logger, monkeypatch
):
    """The stats must be built from the unfiltered log - so
    `reshape_for_animations` still sees every arrival row - with the same
    `warm_up` the graph itself uses.
    """
    seen = {}
    import vidigi.logging as logging_module

    real = logging_module.activity_occupancy_stats

    def spy(event_log, **kwargs):
        seen["n_rows"] = len(event_log)
        seen["warm_up"] = kwargs.get("warm_up")
        return real(event_log, **kwargs)

    monkeypatch.setattr(logging_module, "activity_occupancy_stats", spy)

    raw_rows = len(occupancy_logger.to_dataframe())
    occupancy_logger.generate_dfg(occupancy_metrics=True, warm_up=5)

    assert seen["warm_up"] == 5
    # warm_up=5 drops the t=0 rows from the graph's own log; the stats call
    # still gets all of them.
    assert seen["n_rows"] == raw_rows


# --------------------------------------------------------------------------- #
# Run-aware transition grouping: `_transitions` / `discover_dfg(run_col_name=)`
#
# `discover_dfg` builds edges from each case's consecutive rows. A concatenated
# multi-run log reuses `entity_id` across runs, so without run awareness the
# last event of one run is joined to the first event of the same id in the
# next run - an edge that occurs in no single replication.
# --------------------------------------------------------------------------- #


@pytest.fixture
def two_run_reused_ids():
    """Two runs, both using entity_id 1, run 2 entirely after run 1 in time.

    Run 1: waiting -> treatment -> depart. Run 2: waiting -> depart.
    Concatenated and sorted by (entity_id, time) the rows are:
        r1 waiting, r1 treatment, r1 depart, r2 waiting, r2 depart
    so an id-only shift fabricates a depart -> waiting edge across the seam.
    """
    return pd.DataFrame(
        [
            (10, 1, "waiting", 1),
            (20, 1, "treatment", 1),
            (30, 1, "depart", 1),
            (110, 1, "waiting", 2),
            (125, 1, "depart", 2),
        ],
        columns=["time", "entity_id", "event", "run_number"],
    )


def test_discover_dfg_single_run_unchanged_by_run_col_name(straddling_logger):
    """`run_col_name` must be a true no-op on a genuinely single-run log."""
    stamped = add_sim_timestamp(straddling_logger.to_dataframe())
    base_nodes, base_edges = discover_dfg(stamped)

    for opt in ("run_number", "auto"):
        nodes, edges = discover_dfg(stamped, run_col_name=opt)
        assert_frame_equal(nodes, base_nodes)
        assert_frame_equal(edges, base_edges)


def test_transitions_extraction_matches_the_inline_discover_dfg(straddling_logger):
    """The `delta_time` column `_transitions` produces is what `discover_dfg`
    aggregates - the split-out helper must not drift from it."""
    stamped = add_sim_timestamp(straddling_logger.to_dataframe())
    t = _transitions(stamped)

    assert list(t.columns) == ["source", "target", "delta_time"]
    # waiting (50) -> treatment (120) is the one multi-minute gap for entity 1
    row = t[(t["source"] == "waiting") & (t["target"] == "treatment")]
    assert row["delta_time"].item() == pytest.approx(70.0)


def test_run_col_name_drops_the_fabricated_cross_run_edge(two_run_reused_ids):
    stamped = add_sim_timestamp(two_run_reused_ids)

    with pytest.warns(UserWarning, match="more than one run"):
        _, id_only = discover_dfg(stamped)
    grouped_nodes, grouped = discover_dfg(stamped, run_col_name="run_number")

    id_only_edges = set(zip(id_only["source"], id_only["target"]))
    grouped_edges = set(zip(grouped["source"], grouped["target"]))

    # The seam edge is present without run awareness and gone with it; every
    # real edge survives.
    assert ("depart", "waiting") in id_only_edges
    assert grouped_edges == {
        ("waiting", "treatment"),
        ("treatment", "depart"),
        ("waiting", "depart"),
    }
    # Node counts are unaffected by grouping - 2 waiting, 1 treatment, 2 depart.
    assert dict(zip(grouped_nodes["activity"], grouped_nodes["count"])) == {
        "waiting": 2,
        "treatment": 1,
        "depart": 2,
    }


def test_run_col_name_grouping_needs_the_run_key(two_run_reused_ids):
    """Mutation guard: grouping on the case column alone still fabricates the
    seam edge, so the test above is really pinning the run key."""
    stamped = add_sim_timestamp(two_run_reused_ids)
    t_grouped = _transitions(stamped, run_col="run_number")
    t_case_only = _transitions(stamped, run_col=None)

    assert ("depart", "waiting") not in set(
        zip(t_grouped["source"], t_grouped["target"])
    )
    assert ("depart", "waiting") in set(
        zip(t_case_only["source"], t_case_only["target"])
    )


def test_multi_run_log_without_run_col_name_warns(two_run_reused_ids):
    stamped = add_sim_timestamp(two_run_reused_ids)
    with pytest.warns(UserWarning, match="will raise in vidigi 3.0"):
        discover_dfg(stamped)


def test_no_warning_when_run_col_name_is_given(two_run_reused_ids):
    stamped = add_sim_timestamp(two_run_reused_ids)
    import warnings as _w

    with _w.catch_warnings():
        _w.simplefilter("error")
        discover_dfg(stamped, run_col_name="run_number")
        discover_dfg(stamped, run_col_name="auto")


def test_no_warning_on_a_single_run_log(straddling_logger):
    import warnings as _w

    with _w.catch_warnings():
        _w.simplefilter("error")
        discover_dfg(add_sim_timestamp(straddling_logger.to_dataframe()))


# --------------------------------------------------------------------------- #
# Between-run range annotations on the renderers (cross-run graph only).
# --------------------------------------------------------------------------- #


def _cross_run_tables():
    """Minimal node/edge tables shaped like `_dfg_across_runs` output."""
    nodes = pd.DataFrame(
        {
            "activity": ["waiting", "treatment"],
            "count": [3.5, 2.0],
            "count_run_min": [1, 2],
            "count_run_max": [7, 2],
        }
    )
    edges = pd.DataFrame(
        {
            "source": ["waiting"],
            "target": ["treatment"],
            "frequency": [3.5],
            "mean_time": [42.0],
            "median_time": [40.0],
            "max_time": [60.0],
            "min_time": [20.0],
            "standard_deviation_time": [5.0],
            "probability": [1.0],
            "frequency_run_min": [1],
            "frequency_run_max": [7],
            "mean_time_run_min": [35.0],
            "mean_time_run_max": [51.0],
        }
    )
    return nodes, edges


def test_graphviz_shows_between_run_ranges_when_the_columns_are_present():
    nodes, edges = _cross_run_tables()
    src = dfg_to_graphviz(nodes, edges).source

    assert "n=3.5 (1–7)" in src  # node count range and edge frequency range
    assert "mean=42.0 minutes (35.0–51.0 across runs)" in src


def test_graphviz_between_run_ranges_hidden_when_asked():
    nodes, edges = _cross_run_tables()
    src = dfg_to_graphviz(nodes, edges, show_between_run_ci=False).source

    assert "across runs" not in src
    assert "(1–7)" not in src


def test_graphviz_time_range_only_shown_for_the_mean_metric():
    nodes, edges = _cross_run_tables()
    src = dfg_to_graphviz(nodes, edges, time_metric="median").source

    assert "across runs" not in src
    # the count ranges are metric-independent and still shown
    assert "(1–7)" in src


def test_between_run_ranges_are_a_noop_on_a_plain_single_run_graph(straddling_logger):
    """Mutation guard: a single-run graph has none of the range columns, so
    the default `show_between_run_ci=True` must change nothing."""
    nodes, edges = discover_dfg(add_sim_timestamp(straddling_logger.to_dataframe()))
    with_flag = dfg_to_graphviz(nodes.copy(), edges.copy()).source
    without = dfg_to_graphviz(
        nodes.copy(), edges.copy(), show_between_run_ci=False
    ).source
    assert with_flag == without


def test_cytoscape_elements_carry_the_between_run_ranges():
    nodes, edges = _cross_run_tables()
    cy_nodes, cy_edges = process_nodes_and_edges_for_cytoscape(nodes, edges)

    assert "(1–7)" in cy_nodes[0]["data"]["label"]
    assert "across runs" in cy_edges[0]["data"]["label"]
