"""
SafetySupervisor — validates algorithm-generated commands before dispatch.

Three independent checks run in sequence; the first failure vetoes the command:

  1. Stale tracking  — drone's last telemetry is older than STALE_TIMEOUT_S.
  2. Geofence        — drone's current position is outside the configured box.
  3. Low battery     — battery below LOW_BATTERY_PCT and command is not LAND /
                       EMERGENCY_STOP.

A SafetyVerdict is returned for every command so callers can log rejections
without catching exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from core.config import Settings, settings as default_settings
from core.models import Command, CommandType, DroneState, SwarmState


@dataclass(frozen=True)
class SafetyVerdict:
    approved: bool
    drone_id: str
    command_type: CommandType
    reason: str = ""  # non-empty only when approved=False


# Commands that are always safe regardless of battery / geofence state
_ALWAYS_PERMITTED = {CommandType.EMERGENCY_STOP, CommandType.LAND}


class SafetySupervisor:
    """
    Stateless validator — all context comes from the SwarmState snapshot
    and the injected Settings, making it trivial to unit-test.
    """

    def __init__(self, cfg: Settings = default_settings) -> None:
        self._cfg = cfg

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def validate(self, command: Command, swarm: SwarmState) -> SafetyVerdict:
        """
        Run all safety checks for *command* against *swarm*.

        Returns a SafetyVerdict regardless of outcome.
        """
        drone_id = command.target_drone_id or "broadcast"

        # Targeted commands: run per-drone checks
        if command.target_drone_id is not None:
            drone = swarm.drones.get(command.target_drone_id)
            if drone is None:
                return SafetyVerdict(
                    approved=False,
                    drone_id=drone_id,
                    command_type=command.command_type,
                    reason=f"drone {drone_id!r} not found in swarm state",
                )
            return self._check_drone(command, drone)

        # Broadcast commands: approve only if every active drone passes
        for did, drone in swarm.drones.items():
            verdict = self._check_drone(command, drone)
            if not verdict.approved:
                return SafetyVerdict(
                    approved=False,
                    drone_id="broadcast",
                    command_type=command.command_type,
                    reason=f"drone {did!r} failed: {verdict.reason}",
                )
        return SafetyVerdict(
            approved=True,
            drone_id="broadcast",
            command_type=command.command_type,
        )

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_drone(self, command: Command, drone: DroneState) -> SafetyVerdict:
        base = dict(drone_id=drone.drone_id, command_type=command.command_type)

        verdict = self._check_stale(drone)
        if verdict is not None:
            return SafetyVerdict(approved=False, **base, reason=verdict)

        verdict = self._check_geofence(drone)
        if verdict is not None:
            return SafetyVerdict(approved=False, **base, reason=verdict)

        verdict = self._check_battery(command, drone)
        if verdict is not None:
            return SafetyVerdict(approved=False, **base, reason=verdict)

        return SafetyVerdict(approved=True, **base)

    def _check_stale(self, drone: DroneState) -> Optional[str]:
        """Return a rejection reason string if telemetry is stale, else None."""
        now = datetime.now(tz=timezone.utc)
        last = drone.last_seen

        # Make last_seen timezone-aware if it is naive (legacy data)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)

        age_s = (now - last).total_seconds()
        if age_s > self._cfg.stale_timeout_s:
            return (
                f"stale telemetry: last seen {age_s:.1f}s ago "
                f"(limit {self._cfg.stale_timeout_s}s)"
            )
        return None

    def _check_geofence(self, drone: DroneState) -> Optional[str]:
        """Return a rejection reason string if the drone is outside the geofence."""
        p = drone.position
        g = self._cfg.geofence

        violations: list[str] = []
        if not (g.x_min <= p.x <= g.x_max):
            violations.append(f"x={p.x:.1f} not in [{g.x_min}, {g.x_max}]")
        if not (g.y_min <= p.y <= g.y_max):
            violations.append(f"y={p.y:.1f} not in [{g.y_min}, {g.y_max}]")
        if not (g.z_min <= p.z <= g.z_max):
            violations.append(f"z={p.z:.1f} not in [{g.z_min}, {g.z_max}]")

        if violations:
            return "geofence violation: " + "; ".join(violations)
        return None

    def _check_battery(self, command: Command, drone: DroneState) -> Optional[str]:
        """Return a rejection reason string for low-battery non-safe commands."""
        if command.command_type in _ALWAYS_PERMITTED:
            return None  # landing/stop is always allowed

        if drone.battery_pct < self._cfg.low_battery_pct:
            return (
                f"low battery: {drone.battery_pct:.1f}% "
                f"(threshold {self._cfg.low_battery_pct}%)"
            )
        return None
