# AI use disclosure
# Tests written by hand but refactored by ChatGPT and further modified by a human.
# OpenAI. (2025). ChatGPT (GPT-4-turbo) [Large language model]. https://chat.openai.com

import pytest
import pandas as pd
from pandas.testing import assert_frame_equal

from tests.sample_models.simplest_fifo_with_logging_resources \
    import Trial as simplest_fifo_with_logging_resources_TRIAL

from tests.sample_models.simplest_fifo_with_logging_stores \
    import Trial as simplest_fifo_with_logging_store_TRIAL

from tests.sample_models.simplest_fifo_with_logging_stores_context_manager \
    import Trial as simplest_fifo_with_logging_stores_context_manager

from tests.sample_models.simplest_with_logging_priority_resources \
    import Trial as simplest_with_logging_priority_resources

from tests.sample_models.simplest_with_logging_priority_storesLEGACY \
    import Trial as simplest_with_logging_priority_storesLEGACY

from tests.sample_models.simplest_with_logging_priority_stores \
    import Trial as simplest_with_logging_priority_stores


def run_trial(trial_cls, drop_resource_id=False, filename=None, run_kwargs=None):
    trial = trial_cls(master_seed=42)
    trial.run_trial(**(run_kwargs or {}))
    df = trial.all_event_logs.copy()
    if drop_resource_id and "resource_id" in df.columns:
        df.drop(columns="resource_id", inplace=True)
    if filename:
        df.to_csv(f"tests/outputs/{filename}.csv", index=False)
    return df.reset_index(drop=True)

# Updated test cases
trial_cases = [
    # 1. Test that when using resources (unprioritised/FIFO) and a traditional simpy store,
    # you end up with the same output
    (
        {"trial_cls": simplest_fifo_with_logging_resources_TRIAL, "run_kwargs": {}},
        {"trial_cls": simplest_fifo_with_logging_store_TRIAL,
         "run_kwargs": {"use_vidigi_store": False, "use_populate_store_func": False},
         "drop_resource_id": True},
    ),
    # 2. Test that when using a Vidigi store (unprioritised/FIFO) and a traditional simpy store,
    # you end up with the same output
    (
        {"trial_cls": simplest_fifo_with_logging_store_TRIAL,
         "run_kwargs": {"use_vidigi_store": False, "use_populate_store_func": False}},
        {"trial_cls": simplest_fifo_with_logging_store_TRIAL,
         "run_kwargs": {"use_vidigi_store": True, "use_populate_store_func": False}},
    ),
    # 3. Test that when using a simpy store (unprioritised/FIFO) and another simpy store,
    # but filling one with a loop and one using the populate_store func, you end up with
    # the same output
    (
        {"trial_cls": simplest_fifo_with_logging_store_TRIAL,
         "run_kwargs": {"use_vidigi_store": False, "use_populate_store_func": False}},
        {"trial_cls": simplest_fifo_with_logging_store_TRIAL,
         "run_kwargs": {"use_vidigi_store": False, "use_populate_store_func": True}},
    ),
    # 4. Test that when using a vidigi store (unprioritised/FIFO) and another vidigi store,
    # but filling one with a loop and one using the populate_store func, you end up with
    # the same output
    (
        {"trial_cls": simplest_fifo_with_logging_store_TRIAL,
         "run_kwargs": {"use_vidigi_store": True, "use_populate_store_func": False}},
        {"trial_cls": simplest_fifo_with_logging_store_TRIAL,
         "run_kwargs": {"use_vidigi_store": True, "use_populate_store_func": True}},
    ),
    # 5. Test that when using a standard store, and when using a
    # vidigi store with the context manager (with) notation, you get the same output
    (
        {"trial_cls": simplest_fifo_with_logging_store_TRIAL,
         "run_kwargs": {"use_vidigi_store": False, "use_populate_store_func": False}},
        {"trial_cls": simplest_fifo_with_logging_stores_context_manager,
         "run_kwargs": {"use_populate_store_func": False},
         "drop_resource_id": False},
    ),
    # 6. Test that when using a standard resource, and when using a
    # vidigi store with the context manager (with) notation, you get the same output
    (
        {"trial_cls": simplest_fifo_with_logging_resources_TRIAL,
         "run_kwargs": {}},
        {"trial_cls": simplest_fifo_with_logging_stores_context_manager,
         "run_kwargs": {"use_populate_store_func": False},
         "drop_resource_id": True},
    ),
    # 7. Test that when using a vidigi store with the context manager (with) notation, and when using a
    # vidigi store with the context manager (with) notation that has been populated with the
    # populate_store_func, you get the same output
    (
        {"trial_cls": simplest_fifo_with_logging_store_TRIAL,
         "run_kwargs": {"use_vidigi_store": False, "use_populate_store_func": False}},
        {"trial_cls": simplest_fifo_with_logging_stores_context_manager,
         "run_kwargs": {"use_populate_store_func": True},
         "drop_resource_id": False},
    ),
    # 8. Test that when using a priority resource, and when using a
    # VidigiPriorityStore (legacy class), you get the same output
    (
        {"trial_cls": simplest_with_logging_priority_resources,
         "run_kwargs": {}},
        {"trial_cls": simplest_with_logging_priority_storesLEGACY,
         "run_kwargs": {"use_populate_store_func": True},
         "drop_resource_id": True},
    ),
    # 9. Test that when using the VidigiPriorityStoreLegacy with and without
    # the populate_store func, you get the same output
    (
        {"trial_cls": simplest_with_logging_priority_storesLEGACY,
         "run_kwargs": {"use_populate_store_func": False}},
        {"trial_cls": simplest_with_logging_priority_storesLEGACY,
         "run_kwargs": {"use_populate_store_func": True},
         "drop_resource_id": False},
    ),

    # 10. Test priority resource against VidigiPriorityStore
    (
        {"trial_cls": simplest_with_logging_priority_resources,
         "run_kwargs": {}},
        {"trial_cls": simplest_with_logging_priority_stores,
         "run_kwargs": {"use_populate_store_func": False},
         "drop_resource_id": True},
    ),
    # 11. Test VidigiPriorityStoreLegacy against VidigiPriorityStore
    (
        {"trial_cls": simplest_with_logging_priority_storesLEGACY,
         "run_kwargs": {}},
        {"trial_cls": simplest_with_logging_priority_stores,
         "run_kwargs": {"use_populate_store_func": False},
         "drop_resource_id": False},
    ),
    # 12.Test that when using the VidigiPriorityStore with and without
    # the populate_store func, you get the same output
     (
        {"trial_cls": simplest_with_logging_priority_stores,
         "run_kwargs": {"use_populate_store_func": False}},
        {"trial_cls": simplest_with_logging_priority_stores,
         "run_kwargs": {"use_populate_store_func": True},
         "drop_resource_id": False},
    ),
]

trial_ids = [
    "simpy_resource_vs_store", # 1
    "simpy_vs_vidigi_store", # 2
    "simpy_store_populate_func", # 3
    "vidigi_store_populate_func", # 4
    "context_manager_comparison", # 5
    "context_manager_comparison_resources", # 6
    "context_manager_populate_store", # 7
    "priority_resource_vs_VidigiPriorityStoreLegacy", # 8
    "VidigiPriorityStoreLegacy_use_not_use_populate_store_func", # 9
    "priority_resource_vs_VidigiPriorityStore", # 10
    "VidigiPriorityStoreLegacy_vs_VidigiPriorityStore", # 11
    "VidigiPriorityStore_use_not_use_populate_store_func", # 12
]

def get_trial_id(trial_cls):
    return f"{trial_cls.__module__.split('.')[-1]}_{trial_cls.__name__}"


@pytest.mark.parametrize("trial_1_config, trial_2_config, trial_id",
                         [(t1, t2, id_) for (t1, t2), id_ in zip(trial_cases, trial_ids)],
                         ids=trial_ids)
def test_trial_equivalence(trial_1_config, trial_2_config, trial_id):
    df1 = run_trial(
        trial_cls=trial_1_config["trial_cls"],
        run_kwargs=trial_1_config.get("run_kwargs", {}),
        drop_resource_id=trial_1_config.get("drop_resource_id", False),
        filename=f"TEST_{trial_id}_df_1"
                )
    df2 = run_trial(
        trial_cls=trial_2_config["trial_cls"],
        run_kwargs=trial_2_config.get("run_kwargs", {}),
        drop_resource_id=trial_2_config.get("drop_resource_id", False),
        filename=f"TEST_{trial_id}_df_2"
    )

    try:
        assert_frame_equal(df1, df2, check_dtype=False)
    except AssertionError as e:
        msg = (
            f"\n❌ Mismatch between trials:\n"
            f" - Trial 1: {trial_1_config['trial_cls'].__name__} with {trial_1_config.get('run_kwargs', {})}\n"
            f" - Trial 2: {trial_2_config['trial_cls'].__name__} with {trial_2_config.get('run_kwargs', {})}"
        )
        raise AssertionError(msg + "\n\n" + str(e)) from None
