"""
Carwash example.

Covers:

- Waiting for other processes
- Resources: Resource

Scenario:
  A carwash has a limited number of washing machines and defines
  a washing processes that takes some (random) time.

  Car processes arrive at the carwash at a random time. If one washing
  machine is available, they start the washing process and wait for it
  to finish. If not, they wait until they can use one.

"""

import itertools
import random
from vidigi.resources import VidigiStore
from vidigi.animation import animate_activity_log
from vidigi.logging import EventLogger
from vidigi.utils import EventPosition, create_event_position_df

import simpy

import pandas as pd

# fmt: off
RANDOM_SEED = 42
NUM_MACHINES = 2  # Number of machines in the carwash
WASHTIME = 5      # Minutes it takes to clean a car
T_INTER = 2       # Create a car every ~2 minutes
SIM_TIME = 60*8     # Simulation time in minutes
# fmt: on


class Carwash:
    """A carwash has a limited number of machines (``NUM_MACHINES``) to
    clean cars in parallel.

    Cars have to request one of the machines. When they got one, they
    can start the washing processes and wait for it to finish (which
    takes ``washtime`` minutes).

    """

    def __init__(self, env, num_machines, washtime):
        self.env = env
        self.machine = VidigiStore(env, num_resources=num_machines)
        self.washtime = washtime
        self.logger = EventLogger(env=self.env)

    def wash(self, car):
        """The washing processes. It takes a ``car`` processes and tries
        to clean it."""
        yield self.env.timeout(self.washtime)
        pct_dirt = random.randint(50, 99)
        print(f"Carwash removed {pct_dirt}% of {car}'s dirt.")


def car(env, name, cw):
    """The car process (each car has a ``name``) arrives at the carwash
    (``cw``) and requests a cleaning machine.

    It then starts the washing process, waits for it to finish and
    leaves to never come back ...

    """
    print(f'{name} arrives at the carwash at {env.now:.2f}.')
    cw.logger.log_arrival(entity_id=name)
    cw.logger.log_queue(entity_id=name, event='carwash_queue_wait_begins')
    with cw.machine.request() as request:
        carwash_spot = yield request

        print(f'{name} enters the carwash at {env.now:.2f}.')

        cw.logger.log_resource_use_start(entity_id=name, event="carwashing_begins",
                                  resource_id=carwash_spot.id_attribute)

        yield env.process(cw.wash(name))

        cw.logger.log_resource_use_end(entity_id=name, event="carwashing_ends",
                            resource_id=carwash_spot.id_attribute)

        print(f'{name} leaves the carwash at {env.now:.2f}.')
        cw.logger.log_departure(entity_id=name)


def setup(env, num_machines, washtime, t_inter, duration):
    """Create a carwash, a number of initial cars and keep creating cars
    approx. every ``t_inter`` minutes."""
    # Create the carwash
    carwash = Carwash(env, num_machines, washtime)

    car_count = itertools.count()

    # Create 4 initial cars
    for _ in range(4):
        env.process(car(env, f'Car {next(car_count)}', carwash))

    # Create more cars while the simulation is running
    while env.now < duration:
        yield env.timeout(random.randint(t_inter - 2, t_inter + 2))
        env.process(car(env, f'Car {next(car_count)}', carwash))

    # Allow remaining events to finish before returning
    yield env.timeout(0)
    carwash.logger.to_dataframe().to_csv(f"logs_{NUM_MACHINES}_machines_{T_INTER}_IAT.csv")


# Setup and start the simulation
print('Carwash')
print('Check out http://youtu.be/fXXmeP9TvBg while simulating ... ;-)')
random.seed(RANDOM_SEED)  # This helps to reproduce the results

def run_model():
    # Create an environment and start the setup process
    env = simpy.Environment()
    carwash_process = env.process(setup(env, NUM_MACHINES, WASHTIME, T_INTER, SIM_TIME))
    # Execute!
    env.run(until=carwash_process)

run_model()

T_INTER = 7

run_model()
