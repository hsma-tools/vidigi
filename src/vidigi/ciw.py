from collections.abc import Iterable
from typing import Any, Iterator, Mapping, Optional, Sequence

import pandas as pd

from vidigi.logging import EventLogger, TrialLogger


def _ciw_event_dicts(
    ciw_recs_obj: Iterable[Mapping[str, Any]],
    node_name_list: Sequence[str],
) -> Iterator[dict]:
    """
    Yield vidigi event dictionaries from a ``ciw.data_record`` object.

    This is the shared core behind :func:`event_log_from_ciw_recs`,
    :func:`event_logger_from_ciw_recs` and :func:`trial_logger_from_ciw_recs`.
    For every entity, in turn, it yields (in order): one ``arrival`` event,
    then for each node the entity visited a ``<node>_wait_begins``,
    ``<node>_begins`` and ``<node>_ends`` event, and finally one ``depart``
    event. See :func:`event_log_from_ciw_recs` for the meaning of the
    parameters and the interpretation of the ciw record fields.
    """
    entity_ids = list(set([log.id_number for log in ciw_recs_obj]))

    for entity_id in entity_ids:
        entity_tuples = [log for log in ciw_recs_obj if log.id_number == entity_id]

        # Sort the events for this entity by service start time
        entity_tuples.sort(key=lambda x: x.service_start_date)

        total_steps = len(entity_tuples)

        # If first entry, record the arrival time
        for i, event in enumerate(entity_tuples):
            if i == 0:
                yield {
                    "entity_id": entity_id,
                    "pathway": "Model",
                    "event_type": "arrival_departure",
                    "event": "arrival",
                    "time": event.arrival_date,
                }

            yield {
                "entity_id": entity_id,
                "pathway": "Model",
                "event_type": "queue",
                "event": f"{node_name_list[event.node-1]}_wait_begins",
                "time": event.arrival_date,
            }

            yield {
                "entity_id": entity_id,
                "pathway": "Model",
                "event_type": "resource_use",
                "event": f"{node_name_list[event.node-1]}_begins",
                "time": event.service_start_date,
                "resource_id": event.server_id,
            }

            yield {
                "entity_id": entity_id,
                "pathway": "Model",
                "event_type": "resource_use_end",
                "event": f"{node_name_list[event.node-1]}_ends",
                "time": event.service_end_date,
                "resource_id": event.server_id,
            }

            if i == total_steps - 1:
                yield {
                    "entity_id": entity_id,
                    "pathway": "Model",
                    "event_type": "arrival_departure",
                    "event": "depart",
                    "time": event.exit_date,
                }


def event_log_from_ciw_recs(
    ciw_recs_obj: Iterable[Mapping[str, Any]],
    node_name_list: Sequence[str],
) -> pd.DataFrame:
    """
    Build an event log from a `ciw.data_record` object.

    The returned dataframe is in the format expected by the vidigi functions
    `reshape_for_animation` and `animate_activity_log`.

    Parameters
    ----------
    ciw_recs_obj: Iterable[CiwRecord]
        An iterable `ciw.data_record` object. Output by
        `Simulation.get_all_records()`. See
        https://ciw.readthedocs.io/en/latest/Tutorial/GettingStarted/part_3.html
        and https://ciw.readthedocs.io/en/latest/Reference/results.html for
        more details.
    node_name_list: Sequence[str]
        User-defined list of strings where each string relates to the resource
        or activity that will take place at that ciw node

    Returns
    -------
    pd.DataFrame
        Event log with one row per event and the columns: `entity_id`,
        `pathway`, `event_type`, `event`, `time`, and optionally `resource_id`.

    See Also
    --------
    event_logger_from_ciw_recs : Same conversion, returning a vidigi
        `EventLogger` (query helpers, JSON/CSV export, timeline and
        process-map outputs) instead of a bare DataFrame.
    trial_logger_from_ciw_recs : Build a `TrialLogger` from several ciw runs
        for multi-run duration / resource-utilisation / replication analysis.

    Notes
    -----
    Given the ciw recs object, if we know the nodes and what they relate to,
    we can build up a picture  the arrival date for the first tuple
    for a given user ID is the arrival

    Then, for each node:
    - the arrival date for a given node is when they start queueing
    - the service start date is when they stop queueing
    - the service start date is when they begin using the resource
    - the service end date is when the resource use ends
    - the server ID is the equivalent of a simpy resource use ID

    A more complex multi-node example can be found in
    https://github.com/Bergam0t/ciw-example-animation in the files:
    - **ciw_model.py**
    - **vidigi_experiments.py**

    Examples
    --------
    # Example taken from:
    # https://ciw.readthedocs.io/en/latest/Tutorial/GettingStarted/part_3.html
    # Let us interpret the servers as workers at a bank, who can see one
    # customer at a time

    import ciw

    N = ciw.create_network(
        arrival_distributions=[ciw.dists.Exponential(rate=0.2)],
        service_distributions=[ciw.dists.Exponential(rate=0.1)],
        number_of_servers=[3]
    )

    ciw.seed(1)

    Q = ciw.Simulation(N)

    Q.simulate_until_max_time(1440)

    recs = Q.get_all_records()

    event_log_from_ciw_recs(ciw_recs_obj=recs, node_name_list=["bank_server"])

    """
    return pd.DataFrame(list(_ciw_event_dicts(ciw_recs_obj, node_name_list)))


def event_logger_from_ciw_recs(
    ciw_recs_obj: Iterable[Mapping[str, Any]],
    node_name_list: Sequence[str],
    *,
    run_number: Optional[int] = None,
) -> EventLogger:
    """
    Build a vidigi `EventLogger` from a single `ciw.data_record` object.

    Equivalent to :func:`event_log_from_ciw_recs`, but returns a populated
    :class:`vidigi.logging.EventLogger` rather than a bare DataFrame. Use this
    when you want the logger's extras on top of the animation: event querying
    (`get_events_by_entity`, `get_events_by_event_type`, ...), JSON / CSV
    export, `plot_entity_timeline`, and `generate_dfg` for a process map.

    Parameters
    ----------
    ciw_recs_obj : Iterable[CiwRecord]
        An iterable `ciw.data_record` object, as output by
        `Simulation.get_all_records()`. See :func:`event_log_from_ciw_recs`.
    node_name_list : Sequence[str]
        User-defined list of node names. See :func:`event_log_from_ciw_recs`.
    run_number : int, optional
        If given, stamped onto every logged event as `run_number`, so this
        logger's events can be told apart from other runs' - required if the
        logger is later added to a `TrialLogger`. Default `None` (no
        `run_number` column).

    Returns
    -------
    vidigi.logging.EventLogger
        A logger whose `_log` holds one record per event. `logger.to_dataframe()`
        carries the same data as :func:`event_log_from_ciw_recs`; the column
        *order* follows `BaseEvent`'s field order instead, which the
        animation and analysis functions (being column-name based) do not
        care about.

    See Also
    --------
    event_log_from_ciw_recs : The bare-DataFrame version.
    trial_logger_from_ciw_recs : The multi-run version.

    Examples
    --------
    import ciw
    from vidigi.ciw import event_logger_from_ciw_recs

    N = ciw.create_network(
        arrival_distributions=[ciw.dists.Exponential(rate=0.2)],
        service_distributions=[ciw.dists.Exponential(rate=0.1)],
        number_of_servers=[3]
    )
    ciw.seed(1)
    Q = ciw.Simulation(N)
    Q.simulate_until_max_time(1440)

    logger = event_logger_from_ciw_recs(
        Q.get_all_records(), node_name_list=["bank_server"]
    )
    logger.to_dataframe()
    """
    logger = EventLogger(run_number=run_number)

    for event_data in _ciw_event_dicts(ciw_recs_obj, node_name_list):
        logger.log_event(**event_data)

    return logger


def trial_logger_from_ciw_recs(
    ciw_recs_list: Sequence[Iterable[Mapping[str, Any]]],
    node_name_list: Sequence[str],
    *,
    run_numbers: Optional[Sequence[int]] = None,
) -> TrialLogger:
    """
    Build a vidigi `TrialLogger` from several ciw runs' records.

    Each entry in `ciw_recs_list` is one run's `Simulation.get_all_records()`
    output - the shape returned by a `multiple_replications`-style helper that
    collects a `get_all_records()` per replication. Every run becomes an
    :class:`vidigi.logging.EventLogger` (via :func:`event_logger_from_ciw_recs`,
    stamped with a `run_number`), and the collection is wrapped in a
    :class:`vidigi.logging.TrialLogger` for cross-run analysis:
    `get_event_duration_stat`, `get_resource_utilisation`, `plot_queue_size`,
    `plot_replication_analysis`, `plot_warm_up_diagnostic`, and so on.

    Parameters
    ----------
    ciw_recs_list : Sequence[Iterable[CiwRecord]]
        One `ciw.data_record` object per run.
    node_name_list : Sequence[str]
        User-defined list of node names, applied to every run. See
        :func:`event_log_from_ciw_recs`.
    run_numbers : Sequence[int], optional
        Run number to stamp onto each run's events, in the same order as
        `ciw_recs_list`. Default `None` uses `1, 2, ..., len(ciw_recs_list)`.
        If given, its length must match `ciw_recs_list`.

    Returns
    -------
    vidigi.logging.TrialLogger

    Raises
    ------
    ValueError
        If `ciw_recs_list` is empty, if `run_numbers` is given with a
        mismatched length, or if any run's records are empty (a ciw run that
        recorded nothing has no arrival time to build events from).

    See Also
    --------
    event_logger_from_ciw_recs : The single-run version.
    event_log_from_ciw_recs : The bare-DataFrame version.

    Examples
    --------
    from vidigi.ciw import trial_logger_from_ciw_recs

    # `logs` is a list where each entry is one run's Q.get_all_records()
    trial = trial_logger_from_ciw_recs(logs, node_name_list=["operator", "nurse"])
    trial.get_event_duration_stat("arrival", "depart", what="mean")
    """
    ciw_recs_list = list(ciw_recs_list)

    if not ciw_recs_list:
        raise ValueError(
            "trial_logger_from_ciw_recs was given no runs. Pass a list with "
            "one ciw get_all_records() object per replication."
        )

    if run_numbers is None:
        run_numbers = range(1, len(ciw_recs_list) + 1)
    else:
        run_numbers = list(run_numbers)
        if len(run_numbers) != len(ciw_recs_list):
            raise ValueError(
                f"run_numbers has {len(run_numbers)} entries but "
                f"{len(ciw_recs_list)} runs were supplied - they must match."
            )

    event_logs = []
    for run_number, ciw_recs_obj in zip(run_numbers, ciw_recs_list):
        logger = event_logger_from_ciw_recs(
            ciw_recs_obj, node_name_list, run_number=run_number
        )
        if not logger.get_log():
            raise ValueError(
                f"Run {run_number} has no ciw records, so no events could be "
                "built for it. Every run passed to trial_logger_from_ciw_recs "
                "must have recorded at least one entity."
            )
        event_logs.append(logger)

    return TrialLogger(event_logs=event_logs)
