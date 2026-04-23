"""
Hover algorithm — built-in swarm behaviour.

Instructs every active drone to hold its current position.
Returns one Command per active drone with CommandType.HOVER and no
additional parameters (the drone firmware interprets HOVER as
"maintain current altitude and XY position").
"""

from __future__ import annotations

from typing import List

from core.models import Command, CommandType, DroneStatus, SwarmState


def hover(swarm_state: SwarmState) -> List[Command]:
    """
    Generate hold-position commands for all non-offline drones.

    Args:
        swarm_state: Current snapshot of the swarm.

    Returns:
        A list of HOVER commands, one per active drone.
    """
    commands: List[Command] = []

    for drone_id, drone in swarm_state.drones.items():
        if drone.status == DroneStatus.OFFLINE:
            continue  # can't command an offline drone

        commands.append(
            Command(
                command_type=CommandType.HOVER,
                target_drone_id=drone_id,
                parameters={},  # no extra params — hold current setpoint
            )
        )

    return commands
