from tests.sample_models.simplest_fifo_with_logging_resources import Trial as simplest_fifo_with_logging_resources_TRIAL
from tests.sample_models.simplest_fifo_with_logging_stores import Trial as simplest_fifo_with_logging_store_TRIAL
from tests.sample_models.simplest_with_logging_priority_resources import Trial as simplest_with_logging_priority_resources
from tests.sample_models.simplest_with_logging_priority_storesLEGACY import Trial as simplest_with_logging_priority_storesLEGACY
from tests.sample_models.simplest_fifo_with_logging_stores_context_manager import Trial as simplest_fifo_with_logging_stores_context_manager

##################################################
# FIFO resources/stores
##################################################

def test_same_output_simpy_store_simpy_resource():
    trial_1 = simplest_fifo_with_logging_resources_TRIAL(master_seed=42)
    trial_1.run_trial()
    trial_1_event_logs = trial_1.all_event_logs
    trial_1_event_logs.to_csv("tests/test_same_output_simpy_store_simpy_resource_trial_1_event_log.csv")

    trial_2 = simplest_fifo_with_logging_store_TRIAL(master_seed=42)
    trial_2.run_trial(use_vidigi_store=False, use_populate_store_func=False)
    trial_2_event_logs = trial_2.all_event_logs
    trial_2_event_logs.drop(columns="resource_id", inplace=True)
    trial_2_event_logs.to_csv("tests/test_same_output_simpy_store_simpy_resource_trial_2_event_log.csv")

    assert trial_1_event_logs.equals(trial_2_event_logs), "Different results observed when using resources and stores"

def test_same_output_simpy_store_vidigi_store():
    trial_1 = simplest_fifo_with_logging_store_TRIAL(master_seed=42)
    trial_1.run_trial(use_vidigi_store=False, use_populate_store_func=False)
    trial_1_event_logs = trial_1.all_event_logs
    trial_1_event_logs.to_csv("tests/test_same_output_simpy_store_vidigi_store_trial_1_event_log.csv")

    trial_2 = simplest_fifo_with_logging_store_TRIAL(master_seed=42)
    trial_2.run_trial(use_vidigi_store=True, use_populate_store_func=False)
    trial_2_event_logs = trial_2.all_event_logs
    trial_2_event_logs.to_csv("tests/test_same_output_simpy_store_vidigi_store_trial_2_event_log.csv")

    assert trial_1_event_logs.equals(trial_2_event_logs), "Different results observed when using simpy store and vidigi store"

def test_same_output_simpy_store_with_without_populate_store_func():
    trial_1 = simplest_fifo_with_logging_store_TRIAL(master_seed=42)
    trial_1.run_trial(use_vidigi_store=False, use_populate_store_func=False)
    trial_1_event_logs = trial_1.all_event_logs
    trial_1_event_logs.to_csv("tests/test_same_output_simpy_store_not_use_populate_store_trial_1_event_log.csv")

    trial_2 = simplest_fifo_with_logging_store_TRIAL(master_seed=42)
    trial_2.run_trial(use_vidigi_store=False, use_populate_store_func=True)
    trial_2_event_logs = trial_2.all_event_logs
    trial_2_event_logs.to_csv("tests/test_same_output_simpy_store_use_populate_store_trial_2_event_log.csv")

    assert trial_1_event_logs.equals(trial_2_event_logs), "Different results observed when populating a simpy store with the populate_store function"

def test_same_output_vidigi_store_with_without_populate_store_func():
    trial_1 = simplest_fifo_with_logging_store_TRIAL(master_seed=42)
    trial_1.run_trial(use_vidigi_store=True, use_populate_store_func=False)
    trial_1_event_logs = trial_1.all_event_logs
    trial_1_event_logs.to_csv("tests/test_same_output_vidigi_store_not_use_populate_store_trial_1_event_log.csv")

    trial_2 = simplest_fifo_with_logging_store_TRIAL(master_seed=42)
    trial_2.run_trial(use_vidigi_store=True, use_populate_store_func=True)
    trial_2_event_logs = trial_2.all_event_logs
    trial_2_event_logs.to_csv("tests/test_same_output_vidigi_store_use_populate_store_trial_2_event_log.csv")

    assert trial_1_event_logs.equals(trial_2_event_logs), "Different results observed when populating a vidigi store with the populate_store function"

def test_same_output_using_context_manager():
    trial_1 = simplest_fifo_with_logging_store_TRIAL(master_seed=42)
    trial_1.run_trial(use_vidigi_store=True, use_populate_store_func=False)
    trial_1_event_logs = trial_1.all_event_logs
    trial_1_event_logs.to_csv("tests/test_same_output_using_context_manager_trial_1_event_log.csv")

    trial_2 = simplest_fifo_with_logging_stores_context_manager(master_seed=42)
    trial_2.run_trial(use_populate_store_func=False)
    trial_2_event_logs = trial_2.all_event_logs
    trial_2_event_logs.drop(columns="resource_id", inplace=True)
    trial_2_event_logs.to_csv("tests/test_same_output_using_context_manager_trial_2_event_log.csv")

def test_same_output_using_context_manager_populate_stores():
    trial_1 = simplest_fifo_with_logging_store_TRIAL(master_seed=42)
    trial_1.run_trial(use_vidigi_store=True, use_populate_store_func=False)
    trial_1_event_logs = trial_1.all_event_logs
    trial_1_event_logs.to_csv("tests/test_same_output_using_context_manager_trial_1_event_log.csv")

    trial_2 = simplest_fifo_with_logging_stores_context_manager(master_seed=42)
    trial_2.run_trial(use_populate_store_func=False)
    trial_2_event_logs = trial_2.all_event_logs
    trial_2_event_logs.drop(columns="resource_id", inplace=True)
    trial_2_event_logs.to_csv("tests/test_same_output_using_context_manager_trial_2_event_log.csv")


################################################
# Priority resources/stores
################################################

def test_same_output_priority_resource_VidigiPriorityStorelegacy():
    trial_1 = simplest_with_logging_priority_resources(master_seed=42)
    trial_1.run_trial()
    trial_1_event_logs = trial_1.all_event_logs
    trial_1_event_logs.to_csv("tests/test_same_output_priority_resource_VidigiPriorityStore_trial_1_event_log.csv")

    trial_2 = simplest_with_logging_priority_storesLEGACY(master_seed=42)
    trial_2.run_trial()
    trial_2_event_logs = trial_2.all_event_logs
    trial_2_event_logs.to_csv("tests/test_same_output_priority_resource_VidigiPriorityStore_trial_2_event_log.csv")
