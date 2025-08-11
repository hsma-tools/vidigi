import simpy
import random
from typing import Tuple
from vidigi.logging import EventLogger


# ---------------------------
# Warehouse Layout (scaled)
# ---------------------------
# Coordinates in pixels for animation space
LAYOUT = {
    # Packing & maintenance
    "packing": (270, 270),
    "maintenance": (600, 300),

    # 8 pickup points
    "pickup_1": (25, 500),
    "pickup_2": (180, 500),
    "pickup_3": (70, 500),
    "pickup_4": (550, 500),
    "pickup_5": (25, 100),
    "pickup_6": (180, 100),
    "pickup_7": (370, 100),
    "pickup_8": (550, 100),
}

PICKUP_POINTS = list(name for name in LAYOUT if name.startswith("pickup"))

SPEED = 100.0  # pixels per minute
PACKING_TIME = 5
PACKAGES_PER_BATCH = (1, 5)
OTHER_TASK_TIME = (2, 4)
OTHER_TASK_PROB = 0.3
SIM_DURATION = 60*24


def travel_time(pos_a: Tuple[int, int], pos_b: Tuple[int, int]) -> float:
    """Calculate travel time between two coordinates."""
    dist = ((pos_a[0] - pos_b[0]) ** 2 + (pos_a[1] - pos_b[1]) ** 2) ** 0.5
    return dist / SPEED


class PackingRobot:
    def __init__(self, env, name, logger):
        self.env = env
        self.name = name
        self.logger = logger
        self.pos = LAYOUT["packing"]  # start at packing station
        self.env.process(self.poll_position())
        self.logger.log_arrival(entity_id=self.name,
                                x=self.pos[0], y=self.pos[1])
        self.logger.log_queue(entity_id=self.name, event="packing",
                               x=self.pos[0], y=self.pos[1])

    def poll_position(self):
        """Logs position every 1 sim time unit, even if idle."""
        while True:
            self.logger.log_custom_event(entity_id=self.name,
                                         event_type="position_poll",
                                         event="position",
                                         x=self.pos[0], y=self.pos[1])
            yield self.env.timeout(1)

    def move_to(self, location_name, pathway, outbound=True):
        """Move robot to a location using Manhattan path.
        outbound=True: horizontal then vertical
        outbound=False: retrace return path (vertical then horizontal)
        """
        destination = LAYOUT[location_name]
        start_x, start_y = self.pos
        dest_x, dest_y = destination

        if outbound:
            sequence = [("x", dest_x - start_x), ("y", dest_y - start_y)]
        else:
            sequence = [("y", dest_y - start_y), ("x", dest_x - start_x)]

        for axis, delta in sequence:
            if delta != 0:
                travel_time = abs(delta) / SPEED
                steps = int(travel_time)
                remaining = travel_time - steps
                move_per_unit = delta / travel_time

                for _ in range(steps):
                    yield self.env.timeout(1)
                    if axis == "x":
                        self.pos = (self.pos[0] + move_per_unit, self.pos[1])
                    else:
                        self.pos = (self.pos[0], self.pos[1] + move_per_unit)
                if remaining > 0:
                    yield self.env.timeout(remaining)
                    if axis == "x":
                        self.pos = (self.pos[0] + move_per_unit * remaining, self.pos[1])
                    else:
                        self.pos = (self.pos[0], self.pos[1] + move_per_unit * remaining)


    def pickup_packages(self, count, pickup_name):
        yield self.env.process(self.move_to(pickup_name, "to_pickup", outbound=True))
        # self.logger.log_custom_event(entity_id=self.name, event_type="action",
        #                              event=f"picked_up_{count}_packages",
        #                              x=self.pos[0], y=self.pos[1],
        #                              location=pickup_name)

        yield self.env.process(self.move_to("packing", "to_packing", outbound=False))


        self.logger.log_queue(entity_id=self.name,
                                    event=pickup_name,
                                    x=self.pos[0], y=self.pos[1],
                                    package_count=count)
        for i in range(count):
            yield self.env.timeout(PACKING_TIME)

        if random.random() < OTHER_TASK_PROB:
            yield self.env.process(self.other_task())

        # Go back to the packing station
        self.logger.log_queue(entity_id=self.name,
                                    event="packing",
                                    x=self.pos[0], y=self.pos[1])



    def other_task(self):
        yield self.env.process(self.move_to("maintenance", "to_maintenance"))
        task_time = random.randint(*OTHER_TASK_TIME)
        self.logger.log_queue(entity_id=self.name,
                                     event="maintenance",
                                     x=self.pos[0], y=self.pos[1],
                                     task_duration_mins=task_time
                                     )
        yield self.env.timeout(task_time)
        yield self.env.process(self.move_to("packing", "return_from_maintenance"))
        # Logging of return to packing location will be handled in pickup_packages process


def package_arrival(env, robot):
    while True:
        yield env.timeout(random.randint(4, 8))
        num_packages = random.randint(*PACKAGES_PER_BATCH)
        pickup_name = random.choice(PICKUP_POINTS)
        yield env.process(robot.pickup_packages(num_packages, pickup_name))




# ---------------------------
# Running the simulation
# ---------------------------
if __name__ == "__main__":
    env = simpy.Environment()
    logger = EventLogger(env=env)
    robot = PackingRobot(env, "RoboPack-1", logger)
    env.process(package_arrival(env, robot))
    env.run(until=SIM_DURATION)
    logger.log_departure(entity_id=robot.name,
                            x=robot.pos[0], y=robot.pos[1])

    logger.to_csv("robot_log.csv")
