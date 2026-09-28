"""Clean-install smoke test: run a small model against an *installed* vidigi.

This is deliberately a plain script, not a pytest test. It is run by
.github/workflows/install_smoke.yml with the interpreter of an empty virtualenv
that holds nothing but vidigi and whatever pip resolved for it, from a directory
outside the repository. That is the point: pytest is not a vidigi dependency, and
pytest.ini_options.pythonpath in pyproject.toml would otherwise put the checkout's
src/ on sys.path and test that instead of the package.

Only vidigi's declared dependencies may be imported here (simpy is one). Do not
import sim_tools, ciw, scipy etc. - a missing declaration is exactly what this is
meant to expose.

Set EXPECTED_VERSION to also assert which release was installed.
"""

import importlib
import importlib.metadata
import os
import random
import warnings
from pathlib import Path

import simpy

from vidigi.logging import EventLogger, TrialLogger
from vidigi.resources import VidigiStore
from vidigi.utils import EventPosition, create_event_position_df

N_CUBICLES = 3
SIM_DURATION = 200
N_RUNS = 2
MEAN_INTER_ARRIVAL = 4
MEAN_TREATMENT = 9

SCENARIO = {"n_cubicles": N_CUBICLES}


def check_installed_package():
    import vidigi

    installed_from = Path(vidigi.__file__).resolve()
    assert "site-packages" in installed_from.parts, (
        f"vidigi was imported from {installed_from}, not from an installed "
        "distribution - this run is not testing the package."
    )

    version = importlib.metadata.version("vidigi")
    expected = os.environ.get("EXPECTED_VERSION")
    if expected:
        assert version == expected, f"installed {version}, expected {expected}"
    print(f"vidigi {version} imported from {installed_from}")

    # Whatever the package advertises as public must import from a clean install.
    # process_mapping is the one that pulls in ipywidgets/ipycytoscape/graphviz.
    for name in (
        "analysis",
        "animation",
        "ciw",
        "logging",
        "plots",
        "prep",
        "process_mapping",
        "resources",
        "utils",
    ):
        importlib.import_module(f"vidigi.{name}")
        assert hasattr(vidigi, name), f"vidigi.{name} not exposed by vidigi/__init__"


def patient(env, entity_id, logger, cubicles, rng):
    logger.log_arrival(entity_id=entity_id)
    logger.log_queue(entity_id=entity_id, event="wait_for_treatment")

    # Auto-logs treatment_begins/treatment_ends because the store has a logger.
    with cubicles.request(
        entity_id=entity_id,
        start_event="treatment_begins",
        end_event="treatment_ends",
    ) as req:
        yield req
        yield env.timeout(rng.expovariate(1 / MEAN_TREATMENT))

    logger.log_departure(entity_id=entity_id)


def arrivals(env, logger, cubicles, rng):
    entity_id = 0
    while True:
        entity_id += 1
        env.process(patient(env, entity_id, logger, cubicles, rng))
        yield env.timeout(rng.expovariate(1 / MEAN_INTER_ARRIVAL))


def run_model(run_number):
    env = simpy.Environment()
    logger = EventLogger(env=env, run_number=run_number, scenario=SCENARIO)
    cubicles = VidigiStore(
        env, num_resources=N_CUBICLES, label="cubicles", logger=logger
    )
    env.process(arrivals(env, logger, cubicles, random.Random(run_number)))
    env.run(until=SIM_DURATION)
    return logger


def main():
    check_installed_package()

    # A vidigi-attributed FutureWarning/DeprecationWarning means an upstream
    # release has started to deprecate something vidigi relies on - better a red
    # run now than a breakage when it is removed. Other libraries' own warnings
    # (and warnings raised at import time) are left alone.
    with warnings.catch_warnings():
        warnings.filterwarnings("error", category=FutureWarning, module=r"vidigi(\.|$)")
        warnings.filterwarnings(
            "error", category=DeprecationWarning, module=r"vidigi(\.|$)"
        )

        loggers = [run_model(run_number) for run_number in range(1, N_RUNS + 1)]
        for logger in loggers:
            df = logger.to_dataframe()
            assert not df.empty
            assert {"arrival", "wait_for_treatment", "treatment_begins", "depart"} <= (
                set(df["event"])
            ), f"expected events missing from the log: {sorted(set(df['event']))}"

        trial = TrialLogger(loggers)
        assert trial.summary()

        event_position_df = create_event_position_df(
            [
                EventPosition(event="arrival", x=50, y=300, label="Arrival"),
                EventPosition(
                    event="wait_for_treatment", x=300, y=300, label="Waiting"
                ),
                EventPosition(
                    event="treatment_begins",
                    x=300,
                    y=150,
                    label="Being treated",
                    resource="n_cubicles",
                ),
                EventPosition(event="depart", x=500, y=50, label="Exit"),
            ]
        )

        fig = trial.animate_activity_log(
            event_position_df,
            run_number=1,
            scenario=SCENARIO,
            limit_duration=SIM_DURATION,
            every_x_time_units=5,
        )
        assert len(fig.frames) > 0, "animation produced no frames"
        assert len(fig.to_html()) > 10_000, "animation HTML is implausibly small"

        queue_fig = trial.plot_queue_size(
            event_list=["wait_for_treatment"],
            limit_duration=SIM_DURATION,
            every_x_time_units=5,
        )
        assert len(queue_fig.data) > 0, "queue-size plot has no traces"

        mean_wait = trial.get_event_duration_stat(
            "wait_for_treatment", "treatment_begins", what="mean"
        )
        assert mean_wait is not None

    print("smoke model OK")


if __name__ == "__main__":
    main()
