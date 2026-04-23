"""
Pydantic data models shared across the entire server.

All models use strict types so validation errors surface early at
system boundaries (MQTT ingress, HTTP ingress, WebSocket egress).
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional
from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class DroneStatus(str, Enum):
    IDLE = "idle"
    HOVERING = "hovering"
    MOVING = "moving"
    LANDING = "landing"
    EMERGENCY = "emergency"
    OFFLINE = "offline"


class CommandType(str, Enum):
    HOVER = "hover"
    MOVE = "move"
    LAND = "land"
    TAKEOFF = "takeoff"
    EMERGENCY_STOP = "emergency_stop"


# ---------------------------------------------------------------------------
# Core domain models
# ---------------------------------------------------------------------------

class Position(BaseModel):
    """3-D position in metres (local NED or ENU frame — TBD by localization)."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class Velocity(BaseModel):
    """3-D velocity in m/s."""
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0


class DroneState(BaseModel):
    """Complete state snapshot for a single drone."""
    drone_id: str
    status: DroneStatus = DroneStatus.OFFLINE
    position: Position = Field(default_factory=Position)
    velocity: Velocity = Field(default_factory=Velocity)
    battery_pct: float = Field(default=100.0, ge=0.0, le=100.0)
    last_seen: datetime = Field(default_factory=datetime.utcnow)


class SwarmState(BaseModel):
    """Aggregated state of the entire swarm."""
    drones: Dict[str, DroneState] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def active_count(self) -> int:
        return sum(1 for d in self.drones.values() if d.status != DroneStatus.OFFLINE)


# ---------------------------------------------------------------------------
# Inbound MQTT message models
# ---------------------------------------------------------------------------

class PositionUpdate(BaseModel):
    """Parsed from telemetry/+/position MQTT topic."""
    drone_id: str
    position: Position
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TelemetryMessage(BaseModel):
    """Full telemetry payload from a single drone."""
    drone_id: str
    position: Position
    velocity: Velocity
    battery_pct: float = Field(ge=0.0, le=100.0)
    status: DroneStatus
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Outbound command model
# ---------------------------------------------------------------------------

class Command(BaseModel):
    """Command dispatched to one or all drones via MQTT."""
    command_type: CommandType
    target_drone_id: Optional[str] = None  # None → broadcast to all
    parameters: Dict[str, float] = Field(default_factory=dict)
    issued_at: datetime = Field(default_factory=datetime.utcnow)
