"""Tests for `TrialLogger.compare_event_duration_stat`,
`.plot_event_duration_comparison`, `.compare_resource_utilisation` and
`.plot_resource_utilisation_comparison`.

These are thin delegators - `test_analysis_scenario_comparison.py`,
`test_plots_scenario_comparison.py` and
`test_plots_resource_utilisation_comparison.py` cover the underlying
comparison logic in depth; this file checks the delegation itself: argument
forwarding, label/scenario defaulting, and the `TypeError` guard on `other`.
"""

import plotly.graph_objects as go
import pytest

from vidigi.analysis import (
    ScenarioComparison,
    compare_replication_values,
    event_durations,
    replication_means,
)
from vidigi.logging import EventLogger, TrialLogger


def test_compare_event_duration_stat_matches_the_analysis_function_directly(
    unequal_run_loggers, two_run_loggers
):
    trial_a = TrialLogger(unequal_run_loggers)
    trial_b = TrialLogger(two_run_loggers)

    result = trial_a.compare_event_duration_stat(trial_b, "arrival", "depart")

    values_a = replication_means(
        event_durations(trial_a.to_dataframe(), "arrival", "depart")
    )["value"]
    values_b = replication_means(
        event_durations(trial_b.to_dataframe(), "arrival", "depart")
    )["value"]
    expected = compare_replication_values(values_a, values_b, label_a="A", label_b="B")

    assert result == expected
    assert isinstance(result, ScenarioComparison)


def test_labels_default_to_each_trials_label(unequal_run_loggers, two_run_loggers):
    trial_a = TrialLogger(unequal_run_loggers, label="baseline")
    trial_b = TrialLogger(two_run_loggers, label="extra staff")

    result = trial_a.compare_event_duration_stat(trial_b, "arrival", "depart")

    assert result.label_a == "baseline"
    assert result.label_b == "extra staff"


def test_labels_fall_back_to_a_and_b_when_neither_trial_has_a_label(
    unequal_run_loggers, two_run_loggers
):
    trial_a = TrialLogger(unequal_run_loggers)
    trial_b = TrialLogger(two_run_loggers)

    result = trial_a.compare_event_duration_stat(trial_b, "arrival", "depart")

    assert result.label_a == "A"
    assert result.label_b == "B"


def test_explicit_labels_override_the_trials_own_label(unequal_run_loggers, two_run_loggers):
    trial_a = TrialLogger(unequal_run_loggers, label="baseline")
    trial_b = TrialLogger(two_run_loggers, label="extra staff")

    result = trial_a.compare_event_duration_stat(
        trial_b, "arrival", "depart", label_a="scenario 1", label_b="scenario 2"
    )

    assert result.label_a == "scenario 1"
    assert result.label_b == "scenario 2"


def test_compare_event_duration_stat_raises_typeerror_for_a_non_triallogger(
    unequal_run_loggers,
):
    trial_a = TrialLogger(unequal_run_loggers)

    with pytest.raises(TypeError, match="TrialLogger"):
        trial_a.compare_event_duration_stat(EventLogger(run_number=1), "arrival", "depart")


def test_plot_event_duration_comparison_returns_a_figure(unequal_run_loggers, two_run_loggers):
    trial_a = TrialLogger(unequal_run_loggers)
    trial_b = TrialLogger(two_run_loggers)

    fig = trial_a.plot_event_duration_comparison(trial_b, "arrival", "depart")

    assert isinstance(fig, go.Figure)
    assert list(fig.data[0].x) == ["A", "B"]


def test_plot_event_duration_comparison_raises_typeerror_for_a_non_triallogger(
    unequal_run_loggers,
):
    trial_a = TrialLogger(unequal_run_loggers)

    with pytest.raises(TypeError, match="TrialLogger"):
        trial_a.plot_event_duration_comparison("not a trial", "arrival", "depart")


def test_compare_resource_utilisation_identical_scenario_overlaps_with_itself(
    resource_use_loggers,
):
    trial = TrialLogger(resource_use_loggers)

    result = trial.compare_resource_utilisation(
        TrialLogger(resource_use_loggers),
        resource_capacities={"treatment_begins": 3},
        limit_duration=20,
    )

    assert result.delta == pytest.approx(0.0)
    assert result.ci_overlap is True
    assert result.n_a == 2
    assert result.n_b == 2


def test_compare_resource_utilisation_matches_hand_computed_utilisation(resource_use_loggers):
    """`resource_use_loggers`'s own docstring hand-computes utilisation 0.25
    (run 1) and 0.5 (run 2) with this exact capacity - both trials here are
    built from the same fixture, so both sides' per-run values are [0.25, 0.5]."""
    trial_a = TrialLogger(resource_use_loggers)
    trial_b = TrialLogger(resource_use_loggers)

    result = trial_a.compare_resource_utilisation(
        trial_b, resource_capacities={"treatment_begins": 3}, limit_duration=20
    )

    assert result.mean_a == pytest.approx(0.375)
    assert result.mean_b == pytest.approx(0.375)


def test_compare_resource_utilisation_rejects_an_unknown_metric(resource_use_loggers):
    trial_a = TrialLogger(resource_use_loggers)
    trial_b = TrialLogger(resource_use_loggers)

    with pytest.raises(ValueError, match="metric"):
        trial_a.compare_resource_utilisation(trial_b, metric="not_a_real_metric")


def test_compare_resource_utilisation_raises_typeerror_for_a_non_triallogger(
    resource_use_loggers,
):
    trial_a = TrialLogger(resource_use_loggers)

    with pytest.raises(TypeError, match="TrialLogger"):
        trial_a.compare_resource_utilisation(EventLogger(run_number=1))


def test_plot_resource_utilisation_comparison_returns_a_figure(resource_use_loggers):
    trial_a = TrialLogger(resource_use_loggers)
    trial_b = TrialLogger(resource_use_loggers)

    fig = trial_a.plot_resource_utilisation_comparison(
        trial_b, resource_capacities={"treatment_begins": 3}, limit_duration=20
    )

    assert isinstance(fig, go.Figure)
    assert list(fig.data[0].x) == ["A", "B"]


def test_plot_resource_utilisation_comparison_defaults_scenario_from_each_trial(
    resource_use_loggers, scenario_with_resources
):
    """`scenario_a`/`scenario_b` default to each trial's own `.scenario`,
    exactly as `get_resource_utilisation` defaults `scenario=self.scenario` -
    so passing only `resource_map` still resolves capacity correctly."""
    trial_a = TrialLogger(resource_use_loggers, scenario=scenario_with_resources)
    trial_b = TrialLogger(resource_use_loggers, scenario={"n_cubicles": 6})

    fig = trial_a.plot_resource_utilisation_comparison(
        trial_b,
        resource_map={"treatment_begins": "n_cubicles"},
        limit_duration=20,
    )

    # Same busy time, twice the capacity in B: its utilisation must halve.
    assert list(fig.data[0].y) == pytest.approx([0.375, 0.1875])


def test_plot_resource_utilisation_comparison_raises_typeerror_for_a_non_triallogger(
    resource_use_loggers,
):
    trial_a = TrialLogger(resource_use_loggers)

    with pytest.raises(TypeError, match="TrialLogger"):
        trial_a.plot_resource_utilisation_comparison(EventLogger(run_number=1))
