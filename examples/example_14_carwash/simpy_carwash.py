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
    carwash.logger.to_dataframe().to_csv("logs.csv")


# Setup and start the simulation
print('Carwash')
print('Check out http://youtu.be/fXXmeP9TvBg while simulating ... ;-)')
random.seed(RANDOM_SEED)  # This helps to reproduce the results

# Create an environment and start the setup process
env = simpy.Environment()
carwash_process = env.process(setup(env, NUM_MACHINES, WASHTIME, T_INTER, SIM_TIME))
# Execute!
env.run(until=carwash_process)

# Display log
event_log_df = pd.read_csv("logs.csv")

# Define positions for animation
event_positions = create_event_position_df([
    EventPosition(event='arrival', x=0, y=350, label="Entrance"),
    EventPosition(event='carwash_queue_wait_begins', x=350, y=200, label="Queue"),
    EventPosition(event='carwashing_begins', x=340, y=100, resource='num_carwashes',
                  label="Being Washed"),
    EventPosition(event='depart', x=250, y=50, label="Exit")
])


class Params:
    def __init__(self):
        self.num_carwashes = NUM_MACHINES

icon_list = [ "🚗", "🚙", "🚓",
            "🚗", "🚙", "🏎️",
            "🚗", "🚙", "🚚",
            "🚗", "🚙", "🛻",
            "🚗", "🚙", "🚛",
            "🚗", "🚙", "🚕",
            "🚗", "🚙", "🚒",
            "🚗", "🚙", "🚑"]

random.shuffle(icon_list)

# Create animation
animate_activity_log(
    event_log=event_log_df,
    event_position_df=event_positions,
    scenario=Params(),
    every_x_time_units=1,
    plotly_height=800,
    plotly_width=800,
    override_x_max=400,
    override_y_max=400,
    limit_duration=SIM_TIME,
    entity_icon_size=50,
    gap_between_entities=50,
    gap_between_resources=180,
    display_stage_labels=False,
    wrap_queues_at=7,
    step_snapshot_max=14,
    gap_between_queue_rows=60,
    custom_entity_icon_list=icon_list,
    resource_opacity=0,
    setup_mode=False,
    add_background_image="https://raw.githubusercontent.com/hsma-tools/vidigi/refs/heads/main/examples/example_14_carwash/carwash_bg.png"
)
