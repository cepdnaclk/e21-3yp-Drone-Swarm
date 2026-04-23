"""
Shared pytest fixtures for the drone swarm server test suite.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.config import GeofenceBounds, Settings
from core.models import (
    Command,
    CommandType,
    DroneState,
    DroneStatus,
    Position,
    SwarmState,
    TelemetryMessage,
    Velocity,
)
from core.safety import SafetySupervisor


# ---------------------------------------------------------------------------
# Reusable settings with tighter bounds for predictable tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        stale_timeout_s=5.0,
        low_battery_pct=20.0,
        geofence=GeofenceBounds(
            x_min=-10.0, x_max=10.0,
            y_min=-10.0, y_max=10.0,
            z_min=0.0,   z_max=20.0,
        ),
    )


@pytest.fixture()
def supervisor(test_settings: Settings) -> SafetySupervisor:
    return SafetySupervisor(cfg=test_settings)


# ---------------------------------------------------------------------------
# Drone / swarm builders
# ---------------------------------------------------------------------------

def make_drone(
    drone_id: str = "d1",
    status: DroneStatus = DroneStatus.HOVERING,
    battery_pct: float = 80.0,
    x: float = 0.0,
    y: float = 0.0,
    z: float = 5.0,
    seconds_ago: float = 0.5,
) -> DroneState:
    """Create a healthy DroneState with sensible defaults."""
    from datetime import timedelta

    last_seen = datetime.now(tz=timezone.utc) - timedelta(seconds=seconds_ago)
    return DroneState(
        drone_id=drone_id,
        status=status,
        position=Position(x=x, y=y, z=z),
        velocity=Velocity(),
        battery_pct=battery_pct,
        last_seen=last_seen,
    )


def make_swarm(*drones: DroneState) -> SwarmState:
    return SwarmState(drones={d.drone_id: d for d in drones})


def make_telemetry(
    drone_id: str = "d1",
    battery_pct: float = 80.0,
    x: float = 0.0,
    y: float = 0.0,
    z: float = 5.0,
) -> TelemetryMessage:
    return TelemetryMessage(
        drone_id=drone_id,
        position=Position(x=x, y=y, z=z),
        velocity=Velocity(),
        battery_pct=battery_pct,
        status=DroneStatus.HOVERING,
        timestamp=datetime.now(tz=timezone.utc),
    )


def make_hover_cmd(drone_id: str = "d1") -> Command:
    return Command(command_type=CommandType.HOVER, target_drone_id=drone_id)
