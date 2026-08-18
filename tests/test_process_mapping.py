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

from vidigi.logging import EventLogger
from vidigi.process_mapping import add_sim_timestamp, discover_dfg


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
