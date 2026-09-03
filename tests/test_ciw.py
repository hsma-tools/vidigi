"""Tests for ``vidigi.ciw``.

``vidigi.ciw`` is the only bridge from a ciw simulation into vidigi, and had no
dedicated test file. ``ciw`` is a hard dependency (``ciw>=3.2.5,<4.0.0``), so
these run unconditionally.

The three public functions share one private generator, ``_ciw_event_dicts``.
The first test pins that the generator refactor left ``event_log_from_ciw_recs``
byte-identical; the rest check the two new logger-returning wrappers.
"""

import warnings

import ciw
import pandas as pd
import pytest

from vidigi.ciw import (
    _ciw_event_dicts,
    event_log_from_ciw_recs,
    event_logger_from_ciw_recs,
    trial_logger_from_ciw_recs,
)
from vidigi.logging import EventLogger, TrialLogger

NODE_NAMES = ["operator"]


def _run(seed, max_time=100):
    """A tiny single-node M/M/2 queue - deterministic given the seed."""
    network = ciw.create_network(
        arrival_distributions=[ciw.dists.Exponential(rate=0.3)],
        service_distributions=[ciw.dists.Exponential(rate=0.5)],
        number_of_servers=[2],
    )
    ciw.seed(seed)
    sim = ciw.Simulation(network)
    sim.simulate_until_max_time(max_time)
    return sim.get_all_records()


@pytest.fixture(scope="module")
def recs():
    return _run(seed=1)


@pytest.fixture(scope="module")
def three_runs():
    return [_run(seed=s) for s in (1, 2, 3)]


# --------------------------------------------------------------------------- #
# Refactor no-op
# --------------------------------------------------------------------------- #


def _reference_event_log(ciw_recs_obj, node_name_list):
    """The pre-refactor body of ``event_log_from_ciw_recs``, verbatim.

    Kept here so the generator refactor is pinned against the exact list-append
    implementation it replaced.
    """
    entity_ids = list(set([log.id_number for log in ciw_recs_obj]))
    event_logs = []
    for entity_id in entity_ids:
        entity_tuples = [log for log in ciw_recs_obj if log.id_number == entity_id]
        entity_tuples.sort(key=lambda x: x.service_start_date)
        total_steps = len(entity_tuples)
        for i, event in enumerate(entity_tuples):
            if i == 0:
                event_logs.append(
                    {
                        "entity_id": entity_id,
                        "pathway": "Model",
                        "event_type": "arrival_departure",
                        "event": "arrival",
                        "time": event.arrival_date,
                    }
                )
            event_logs.append(
                {
                    "entity_id": entity_id,
                    "pathway": "Model",
                    "event_type": "queue",
                    "event": f"{node_name_list[event.node - 1]}_wait_begins",
                    "time": event.arrival_date,
                }
            )
            event_logs.append(
                {
                    "entity_id": entity_id,
                    "pathway": "Model",
                    "event_type": "resource_use",
                    "event": f"{node_name_list[event.node - 1]}_begins",
                    "time": event.service_start_date,
                    "resource_id": event.server_id,
                }
            )
            event_logs.append(
                {
                    "entity_id": entity_id,
                    "pathway": "Model",
                    "event_type": "resource_use_end",
                    "event": f"{node_name_list[event.node - 1]}_ends",
                    "time": event.service_end_date,
                    "resource_id": event.server_id,
                }
            )
            if i == total_steps - 1:
                event_logs.append(
                    {
                        "entity_id": entity_id,
                        "pathway": "Model",
                        "event_type": "arrival_departure",
                        "event": "depart",
                        "time": event.exit_date,
                    }
                )
    return pd.DataFrame(event_logs)


def test_event_log_from_ciw_recs_unchanged_by_refactor(recs):
    """The generator refactor must not move a single row or value."""
    pd.testing.assert_frame_equal(
        event_log_from_ciw_recs(recs, NODE_NAMES),
        _reference_event_log(recs, NODE_NAMES),
    )


def test_reference_helper_actually_catches_a_regression(recs):
    """Guard the guard: a broken generator must fail the comparison above.

    Mirrors dropping the ``depart`` row from ``_ciw_event_dicts``.
    """
    broken = pd.DataFrame(
        [d for d in _ciw_event_dicts(recs, NODE_NAMES) if d["event"] != "depart"]
    )
    with pytest.raises(AssertionError):
        pd.testing.assert_frame_equal(broken, _reference_event_log(recs, NODE_NAMES))


# --------------------------------------------------------------------------- #
# event_logger_from_ciw_recs
# --------------------------------------------------------------------------- #


def test_returns_populated_event_logger(recs):
    logger = event_logger_from_ciw_recs(recs, NODE_NAMES)

    assert isinstance(logger, EventLogger)

    from_df = event_log_from_ciw_recs(recs, NODE_NAMES)
    from_logger = logger.to_dataframe()

    assert len(from_logger) == len(from_df)

    sort_cols = ["entity_id", "time", "event"]
    left = from_df.sort_values(sort_cols).reset_index(drop=True)
    right = from_logger[from_df.columns].sort_values(sort_cols).reset_index(drop=True)
    pd.testing.assert_frame_equal(left, right)


def test_event_logger_population_is_warning_free(recs):
    """Every event_type produced is recognised and every resource_id is an int,
    so populating the logger must not emit an ``EventLogger`` warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        event_logger_from_ciw_recs(recs, NODE_NAMES)


def test_run_number_absent_by_default_and_stamped_when_given(recs):
    assert (
        "run_number" not in event_logger_from_ciw_recs(recs, NODE_NAMES).to_dataframe()
    )

    stamped = event_logger_from_ciw_recs(recs, NODE_NAMES, run_number=7).to_dataframe()
    assert (stamped["run_number"] == 7).all()


def test_single_entity_event_sequence(recs):
    """The whole ordered event sequence for one entity, DataFrame vs logger."""
    entity_id = event_log_from_ciw_recs(recs, NODE_NAMES)["entity_id"].iloc[0]

    def sequence(df):
        rows = df[df["entity_id"] == entity_id].sort_values("time")
        return list(zip(rows["event_type"], rows["event"]))

    df_seq = sequence(event_log_from_ciw_recs(recs, NODE_NAMES))
    logger_seq = sequence(event_logger_from_ciw_recs(recs, NODE_NAMES).to_dataframe())

    assert df_seq == logger_seq
    assert df_seq[0] == ("arrival_departure", "arrival")
    assert df_seq[-1] == ("arrival_departure", "depart")
    assert ("queue", "operator_wait_begins") in df_seq
    assert ("resource_use", "operator_begins") in df_seq
    assert ("resource_use_end", "operator_ends") in df_seq


# --------------------------------------------------------------------------- #
# trial_logger_from_ciw_recs
# --------------------------------------------------------------------------- #


def test_returns_trial_logger_with_one_run_per_recs(three_runs):
    trial = trial_logger_from_ciw_recs(three_runs, NODE_NAMES)

    assert isinstance(trial, TrialLogger)
    assert trial.summary() == {"number_of_runs": 3}
    assert sorted(trial._run_index.keys()) == [1, 2, 3]


def test_trial_row_count_is_sum_of_per_run_logs(three_runs):
    trial = trial_logger_from_ciw_recs(three_runs, NODE_NAMES)

    expected = sum(
        len(event_logger_from_ciw_recs(r, NODE_NAMES).to_dataframe())
        for r in three_runs
    )
    assert len(trial.to_dataframe()) == expected


def test_custom_run_numbers_respected(three_runs):
    trial = trial_logger_from_ciw_recs(three_runs, NODE_NAMES, run_numbers=[10, 20, 30])
    assert sorted(trial._run_index.keys()) == [10, 20, 30]


def test_empty_recs_list_raises(three_runs):
    with pytest.raises(ValueError, match="no runs"):
        trial_logger_from_ciw_recs([], NODE_NAMES)


def test_mismatched_run_numbers_length_raises(three_runs):
    with pytest.raises(ValueError, match="must match"):
        trial_logger_from_ciw_recs(three_runs, NODE_NAMES, run_numbers=[1, 2])


def test_run_with_no_records_raises(three_runs):
    with pytest.raises(ValueError, match="Run 2 has no ciw records"):
        trial_logger_from_ciw_recs([three_runs[0], [], three_runs[2]], NODE_NAMES)
