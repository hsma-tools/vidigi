import simpy
import random
from typing import Tuple
from vidigi.logging import EventLogger


# ---------------------------
# Warehouse Layout (scaled)
# ---------------------------
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
PICKUP_POINTS = [n for n in LAYOUT if n.startswith("pickup")]

SPEED = 100.0  # pixels per minute
PACKING_TIME = 5
PACKAGES_PER_BATCH = (1, 5)
OTHER_TASK_TIME = (2, 4)
OTHER_TASK_PROB = 0.3
SIM_DURATION = 60 * 24

# Shared dictionary of robot positions
robot_positions = {}


def travel_time(pos_a: Tuple[int, int], pos_b: Tuple[int, int]) -> float:
    dist = ((pos_a[0] - pos_b[0]) ** 2 + (pos_a[1] - pos_b[1]) ** 2) ** 0.5
    return dist / SPEED


class PackingRobot:
    def __init__(self, env, name, logger, packing_slot=0):
        self.env = env
        self.name = name
        self.logger = logger
        self.packing_offset = (
            (packing_slot % 4) * 15,          # x: 0,15,30,45 then back to 0
            (packing_slot // 4) * 30          # y: 0 for first 4, then 30, 60, etc.
        )
        self.pos = self._with_packing_offset(LAYOUT["packing"])
        robot_positions[self.name] = self.pos
        self.env.process(self.poll_position())
        self.logger.log_arrival(entity_id=self.name, x=self.pos[0], y=self.pos[1])
        self.logger.log_queue(entity_id=self.name, event="packing", x=self.pos[0], y=self.pos[1])

    def _with_packing_offset(self, base_pos):
        """Return position adjusted if in packing area."""
        if base_pos == LAYOUT["packing"]:
            return (base_pos[0] + self.packing_offset[0],
                    base_pos[1] + self.packing_offset[1])
        else:
            return base_pos

    def _logical_pos(self, pos):
        """Return the logical position without visual offset."""
        # If within 1e-6 of packing coords (ignoring offset), treat as packing
        px, py = LAYOUT["packing"]
        if abs(pos[0] - px - self.packing_offset[0]) < 1e-6 and \
        abs(pos[1] - py - self.packing_offset[1]) < 1e-6:
            return LAYOUT["packing"]
        return pos

    def poll_position(self):
        while True:
            self.logger.log_custom_event(
                entity_id=self.name,
                event_type="position_poll",
                event="position",
                x=self.pos[0],
                y=self.pos[1],
            )
            yield self.env.timeout(1)

    def move_to(self, location_name, pathway, outbound=True):
        """Move robot step-by-step."""
        destination = LAYOUT[location_name]
        start_x, start_y = self.pos
        dest_x, dest_y = destination

        yield from self._do_stepwise_move(destination, outbound)


    def _do_stepwise_move(self, destination, outbound):
        """Helper for stepwise movement with blocking except in packing.
        """
        start_x, start_y = self.pos
        dest_x, dest_y = destination

        if outbound:
            sequence = [("x", dest_x - start_x), ("y", dest_y - start_y)]
        else:
            sequence = [("y", dest_y - start_y), ("x", dest_x - start_x)]

        for axis, delta in sequence:
            if delta != 0:
                travel_time_units = abs(delta) / SPEED
                steps = int(travel_time_units)
                remaining = travel_time_units - steps
                move_per_unit = delta / travel_time_units

                # --- Whole steps ---
                for _ in range(steps):
                    next_pos = (
                        self.pos[0] + move_per_unit if axis == "x" else self.pos[0],
                        self.pos[1] + move_per_unit if axis == "y" else self.pos[1],
                    )

                    yield self.env.timeout(1)
                    self.pos = self._with_packing_offset(next_pos)
                    robot_positions[self.name] = self.pos

                # --- Remaining fractional step ---
                if remaining > 0:
                    next_pos = (
                        self.pos[0] + move_per_unit * remaining if axis == "x" else self.pos[0],
                        self.pos[1] + move_per_unit * remaining if axis == "y" else self.pos[1],
                    )

                    if (self._logical_pos(self.pos) != LAYOUT["packing"] and
                        self._logical_pos(next_pos) != LAYOUT["packing"]):
                        while any(
                            other != self.name and
                            abs(robot_positions[other][0] - next_pos[0]) < 1e-6 and
                            abs(robot_positions[other][1] - next_pos[1]) < 1e-6
                            for other in robot_positions
                        ):
                            yield self.env.timeout(0.1)

                    yield self.env.timeout(remaining)
                    self.pos = self._with_packing_offset(next_pos)
                    robot_positions[self.name] = self.pos


    def pickup_packages(self, count, pickup_name):
        yield self.env.process(self.move_to(pickup_name, "to_pickup", outbound=True))

        yield self.env.process(self.move_to("packing", "to_packing", outbound=False))

        self.logger.log_queue(entity_id=self.name, event=pickup_name, x=self.pos[0], y=self.pos[1], package_count=count)
        for _ in range(count):
            yield self.env.timeout(PACKING_TIME)

        if random.random() < OTHER_TASK_PROB:
            yield self.env.process(self.other_task())

        self.logger.log_queue(entity_id=self.name, event="packing", x=self.pos[0], y=self.pos[1])

    def other_task(self):
        yield self.env.process(self.move_to("maintenance", "to_maintenance"))
        task_time = random.randint(*OTHER_TASK_TIME)
        self.logger.log_queue(entity_id=self.name, event="maintenance", x=self.pos[0], y=self.pos[1], task_duration_mins=task_time)
        yield self.env.timeout(task_time)
        yield self.env.process(self.move_to("packing", "return_from_maintenance"))


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

    n_robots=7

    robots = [PackingRobot(env, f"RoboPack-{i+1}", logger, packing_slot=i) for i in range(8)]
    for robot in robots:
        env.process(package_arrival(env, robot))

    env.run(until=SIM_DURATION)
    for robot in robots:
        logger.log_departure(entity_id=robot.name, x=robot.pos[0], y=robot.pos[1])
    logger.to_csv("robot_log_multiple.csv")
