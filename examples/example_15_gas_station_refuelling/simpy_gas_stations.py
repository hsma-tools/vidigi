"""
Gas Station Refueling example

Covers:

- Resources: Resource
- Resources: Container
- Waiting for other processes

Scenario:
  A gas station has a limited number of gas pumps that share a common
  fuel reservoir. Cars randomly arrive at the gas station, request one
  of the fuel pumps and start refueling from that reservoir.

  A gas station control process observes the gas station's fuel level
  and calls a tank truck for refueling if the station's level drops
  below a threshold.

"""

import itertools
import random

from vidigi.resources import VidigiStore
from vidigi.animation import animate_activity_log
from vidigi.logging import EventLogger
from vidigi.utils import EventPosition, create_event_position_df

import simpy

# fmt: off
RANDOM_SEED = 42
STATION_TANK_SIZE = 200    # Size of the gas station tank (liters)
THRESHOLD = 25             # Station tank minimum level (% of full)
CAR_TANK_SIZE = 50         # Size of car fuel tanks (liters)
CAR_TANK_LEVEL = [5, 25]   # Min/max levels of car fuel tanks (liters)
REFUELING_SPEED = 2        # Rate of refuelling car fuel tank (liters / second)
TANK_TRUCK_ARRIVAL_TIME = 300      # Time it takes tank truck to arrive (seconds)
TANK_TRUCK_REFUEL_TIME = 1000      # MODIFICATION: Time it takes tank truck to refuel (seconds)
T_INTER = [30, 300]        # Interval between car arrivals [min, max] (seconds)
SIM_TIME = 60*60*24            # Simulation time (seconds)
# fmt: on


def car(name, env, gas_station, station_tank, logger):
    """A car arrives at the gas station for refueling.

    It requests one of the gas station's fuel pumps and tries to get the
    desired amount of fuel from it. If the station's fuel tank is
    depleted, the car has to wait for the tank truck to arrive.

    """
    car_tank_level = random.randint(*CAR_TANK_LEVEL)
    logger.log_arrival(entity_id=name)
    print(f'{env.now:6.1f} s: {name} arrived at gas station')
    logger.log_queue(entity_id=name, event='pump_queue_wait_begins')
    with gas_station.request() as req:
        # Request one of the gas pumps
        gas_pump = yield req

        logger.log_resource_use_start(entity_id=name, event="pumping_begins",
                                  resource_id=gas_pump.id_attribute)

        # Get the required amount of fuel
        fuel_required = CAR_TANK_SIZE - car_tank_level
        yield station_tank.get(fuel_required)

        # The "actual" refueling process takes some time
        yield env.timeout(fuel_required / REFUELING_SPEED)

        logger.log_resource_use_end(entity_id=name, event="pumping_ends",
                                  resource_id=gas_pump.id_attribute)

        print(f'{env.now:6.1f} s: {name} refueled with {fuel_required:.1f}L')
        logger.log_departure(entity_id=name)


def gas_station_control(env, station_tank, logger):
    """Periodically check the level of the gas station tank and call the tank
    truck if the level falls below a threshold."""
    truck_call_id = 0

    while True:
        if station_tank.level / station_tank.capacity * 100 < THRESHOLD:
            # We need to call the tank truck now!
            logger.log_arrival(entity_id=f"Call {truck_call_id}")
            logger.log_queue(entity_id=f"Call {truck_call_id}", event="calling_truck")
            print(f'{env.now:6.1f} s: Calling tank truck')
            # Wait for the tank truck to arrive and refuel the station tank
            yield env.process(tank_truck(env, station_tank, logger, truck_call_id))

            truck_call_id += 1

        yield env.timeout(10)  # Check every 10 seconds


def tank_truck(env, station_tank, logger, truck_call_id):
    """Arrives at the gas station after a certain delay and refuels it."""
    yield env.timeout(TANK_TRUCK_ARRIVAL_TIME)
    logger.log_departure(entity_id=f"Call {truck_call_id}")
    logger.log_arrival(entity_id=f"Truck {truck_call_id}")
    amount = station_tank.capacity - station_tank.level
    logger.log_queue(entity_id=f"Truck {truck_call_id}", event="refueling")
    yield env.timeout(TANK_TRUCK_REFUEL_TIME)
    station_tank.put(amount)
    print(
        f'{env.now:6.1f} s: Tank truck arrived and refuelled station with {amount:.1f}L'
    )
    logger.log_departure(entity_id=f"Truck {truck_call_id}")


def car_generator(env, gas_station, station_tank, logger):
    """Generate new cars that arrive at the gas station."""
    for i in itertools.count():
        yield env.timeout(random.randint(*T_INTER))
        env.process(car(f'Car {i}', env, gas_station, station_tank, logger))


# Setup and start the simulation
print('Gas Station refuelling')
random.seed(RANDOM_SEED)

# Create environment and start processes
env = simpy.Environment()
gas_station = VidigiStore(env, num_resources=2)
station_tank = simpy.Container(env, STATION_TANK_SIZE, init=STATION_TANK_SIZE)
logger = EventLogger(env=env)
env.process(gas_station_control(env, station_tank, logger))
env.process(car_generator(env, gas_station, station_tank, logger))

# Execute!
env.run(until=SIM_TIME)

logger.to_csv("gas_station_log.csv")
