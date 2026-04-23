"""
Structured event logging helpers.

Every public function emits a single log record whose `extra` dict contains
machine-readable fields.  The root logger's formatter can be swapped for a
JSON formatter (e.g. python-json-logger) without touching call sites.

Call sites stay clean:
    log_telemetry_received(msg)
    log_position_update(drone_id, position)
    log_command_sent(command)
    log_safety_rejection(command, reason)
"""

from __future__ import annotations

import logging
from datetime import datetime

from core.models import Command, Position, TelemetryMessage

logger = logging.getLogger("swarm.events")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extra(**kwargs) -> dict:
    """Merge caller-supplied fields with a common timestamp key."""
    return {"event_ts": datetime.utcnow().isoformat(), **kwargs}


# ---------------------------------------------------------------------------
# Inbound telemetry
# ---------------------------------------------------------------------------

def log_telemetry_received(msg: TelemetryMessage) -> None:
    """Emitted each time a full telemetry message is applied to SwarmState."""
    logger.info(
        "TELEMETRY  drone=%-10s  status=%-10s  bat=%.1f%%  "
        "pos=(%.2f, %.2f, %.2f)",
        msg.drone_id,
        msg.status.value,
        msg.battery_pct,
        msg.position.x,
        msg.position.y,
        msg.position.z,
        extra=_extra(
            event="telemetry_received",
            drone_id=msg.drone_id,
            status=msg.status.value,
            battery_pct=msg.battery_pct,
            pos_x=msg.position.x,
            pos_y=msg.position.y,
            pos_z=msg.position.z,
        ),
    )


# ---------------------------------------------------------------------------
# Position updates
# ---------------------------------------------------------------------------

def log_position_update(drone_id: str, position: Position) -> None:
    """Emitted for lightweight position-only updates (e.g. from UWB localization)."""
    logger.info(
        "POSITION   drone=%-10s  pos=(%.2f, %.2f, %.2f)",
        drone_id,
        position.x,
        position.y,
        position.z,
        extra=_extra(
            event="position_update",
            drone_id=drone_id,
            pos_x=position.x,
            pos_y=position.y,
            pos_z=position.z,
        ),
    )


# ---------------------------------------------------------------------------
# Commands dispatched
# ---------------------------------------------------------------------------

def log_command_sent(command: Command) -> None:
    """Emitted after SafetySupervisor approves and MQTT publishes a command."""
    target = command.target_drone_id or "broadcast"
    logger.info(
        "COMMAND    target=%-10s  type=%s  params=%s",
        target,
        command.command_type.value,
        command.parameters,
        extra=_extra(
            event="command_sent",
            target_drone_id=target,
            command_type=command.command_type.value,
            parameters=command.parameters,
        ),
    )


# ---------------------------------------------------------------------------
# Safety rejections
# ---------------------------------------------------------------------------

def log_safety_rejection(command: Command, reason: str) -> None:
    """Emitted when SafetySupervisor blocks a command."""
    target = command.target_drone_id or "broadcast"
    logger.warning(
        "SAFETY_REJECT  target=%-10s  type=%-15s  reason=%s",
        target,
        command.command_type.value,
        reason,
        extra=_extra(
            event="safety_rejection",
            target_drone_id=target,
            command_type=command.command_type.value,
            reason=reason,
        ),
    )
