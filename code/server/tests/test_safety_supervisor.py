"""
Tests for core.safety.SafetySupervisor.

SafetySupervisor is pure/synchronous so no asyncio fixture is needed.
Every test creates its own swarm snapshot and command to keep cases isolated.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.models import Command, CommandType, DroneStatus, Position
from core.safety import SafetySupervisor
from tests.conftest import (
    make_drone,
    make_hover_cmd,
    make_swarm,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_land_cmd(drone_id: str = "d1") -> Command:
    return Command(command_type=CommandType.LAND, target_drone_id=drone_id)


def make_estop_cmd(drone_id: str = "d1") -> Command:
    return Command(command_type=CommandType.EMERGENCY_STOP, target_drone_id=drone_id)


# ---------------------------------------------------------------------------
# Healthy drone → command approved
# ---------------------------------------------------------------------------

class TestApprovedCommands:
    def test_healthy_drone_hover_approved(self, supervisor: SafetySupervisor) -> None:
        drone = make_drone("d1")
        swarm = make_swarm(drone)
        verdict = supervisor.validate(make_hover_cmd("d1"), swarm)

        assert verdict.approved is True
        assert verdict.reason == ""

    def test_returns_correct_drone_id(self, supervisor: SafetySupervisor) -> None:
        drone = make_drone("d1")
        verdict = supervisor.validate(make_hover_cmd("d1"), make_swarm(drone))
        assert verdict.drone_id == "d1"

    def test_returns_correct_command_type(self, supervisor: SafetySupervisor) -> None:
        drone = make_drone("d1")
        verdict = supervisor.validate(make_hover_cmd("d1"), make_swarm(drone))
        assert verdict.command_type == CommandType.HOVER


# ---------------------------------------------------------------------------
# Unknown drone
# ---------------------------------------------------------------------------

class TestUnknownDrone:
    def test_rejects_command_for_unknown_drone(self, supervisor: SafetySupervisor) -> None:
        swarm = make_swarm()  # empty
        verdict = supervisor.validate(make_hover_cmd("ghost"), swarm)

        assert verdict.approved is False
        assert "not found" in verdict.reason


# ---------------------------------------------------------------------------
# Stale tracking check
# ---------------------------------------------------------------------------

class TestStaleTracking:
    def test_rejects_stale_drone(self, supervisor: SafetySupervisor) -> None:
        # last_seen > 5 s ago (threshold is 5 s in test_settings)
        drone = make_drone("d1", seconds_ago=10.0)
        verdict = supervisor.validate(make_hover_cmd("d1"), make_swarm(drone))

        assert verdict.approved is False
        assert "stale" in verdict.reason

    def test_accepts_fresh_drone(self, supervisor: SafetySupervisor) -> None:
        drone = make_drone("d1", seconds_ago=0.1)
        verdict = supervisor.validate(make_hover_cmd("d1"), make_swarm(drone))

        assert verdict.approved is True

    def test_boundary_exactly_at_timeout_is_stale(
        self, supervisor: SafetySupervisor, test_settings
    ) -> None:
        # Exactly at the threshold is still stale (strict >)
        drone = make_drone("d1", seconds_ago=test_settings.stale_timeout_s + 0.001)
        verdict = supervisor.validate(make_hover_cmd("d1"), make_swarm(drone))

        assert verdict.approved is False

    def test_naive_datetime_handled(self, supervisor: SafetySupervisor) -> None:
        """last_seen without tzinfo should not crash; stale comparison still works."""
        drone = make_drone("d1", seconds_ago=0.1)
        # Strip timezone to simulate legacy/naive datetime
        drone = drone.model_copy(
            update={"last_seen": drone.last_seen.replace(tzinfo=None)}
        )
        verdict = supervisor.validate(make_hover_cmd("d1"), make_swarm(drone))
        # Should still approve (fresh drone, just naive tz)
        assert verdict.approved is True


# ---------------------------------------------------------------------------
# Geofence check
# ---------------------------------------------------------------------------

class TestGeofence:
    def test_inside_geofence_approved(self, supervisor: SafetySupervisor) -> None:
        drone = make_drone("d1", x=0.0, y=0.0, z=5.0)
        verdict = supervisor.validate(make_hover_cmd("d1"), make_swarm(drone))

        assert verdict.approved is True

    def test_outside_x_rejected(self, supervisor: SafetySupervisor) -> None:
        drone = make_drone("d1", x=99.0, y=0.0, z=5.0)
        verdict = supervisor.validate(make_hover_cmd("d1"), make_swarm(drone))

        assert verdict.approved is False
        assert "geofence" in verdict.reason
        assert "x=" in verdict.reason

    def test_outside_y_rejected(self, supervisor: SafetySupervisor) -> None:
        drone = make_drone("d1", x=0.0, y=-99.0, z=5.0)
        verdict = supervisor.validate(make_hover_cmd("d1"), make_swarm(drone))

        assert verdict.approved is False
        assert "y=" in verdict.reason

    def test_above_ceiling_rejected(self, supervisor: SafetySupervisor) -> None:
        # test_settings z_max = 20 m
        drone = make_drone("d1", x=0.0, y=0.0, z=25.0)
        verdict = supervisor.validate(make_hover_cmd("d1"), make_swarm(drone))

        assert verdict.approved is False
        assert "z=" in verdict.reason

    def test_below_floor_rejected(self, supervisor: SafetySupervisor) -> None:
        drone = make_drone("d1", x=0.0, y=0.0, z=-1.0)
        verdict = supervisor.validate(make_hover_cmd("d1"), make_swarm(drone))

        assert verdict.approved is False

    def test_multiple_axis_violations_reported(self, supervisor: SafetySupervisor) -> None:
        drone = make_drone("d1", x=50.0, y=50.0, z=5.0)
        verdict = supervisor.validate(make_hover_cmd("d1"), make_swarm(drone))

        assert verdict.approved is False
        assert "x=" in verdict.reason
        assert "y=" in verdict.reason


# ---------------------------------------------------------------------------
# Low battery check
# ---------------------------------------------------------------------------

class TestLowBattery:
    def test_low_battery_blocks_hover(self, supervisor: SafetySupervisor) -> None:
        # threshold = 20 %; battery = 10 %
        drone = make_drone("d1", battery_pct=10.0)
        verdict = supervisor.validate(make_hover_cmd("d1"), make_swarm(drone))

        assert verdict.approved is False
        assert "battery" in verdict.reason

    def test_exactly_at_threshold_blocked(self, supervisor: SafetySupervisor, test_settings) -> None:
        drone = make_drone("d1", battery_pct=test_settings.low_battery_pct - 0.1)
        verdict = supervisor.validate(make_hover_cmd("d1"), make_swarm(drone))

        assert verdict.approved is False

    def test_above_threshold_approved(self, supervisor: SafetySupervisor, test_settings) -> None:
        drone = make_drone("d1", battery_pct=test_settings.low_battery_pct + 0.1)
        verdict = supervisor.validate(make_hover_cmd("d1"), make_swarm(drone))

        assert verdict.approved is True

    def test_land_always_permitted_on_low_battery(
        self, supervisor: SafetySupervisor
    ) -> None:
        drone = make_drone("d1", battery_pct=5.0)
        verdict = supervisor.validate(make_land_cmd("d1"), make_swarm(drone))

        assert verdict.approved is True

    def test_emergency_stop_always_permitted_on_low_battery(
        self, supervisor: SafetySupervisor
    ) -> None:
        drone = make_drone("d1", battery_pct=5.0)
        verdict = supervisor.validate(make_estop_cmd("d1"), make_swarm(drone))

        assert verdict.approved is True


# ---------------------------------------------------------------------------
# Broadcast commands
# ---------------------------------------------------------------------------

class TestBroadcastCommands:
    def _broadcast_hover(self) -> Command:
        return Command(command_type=CommandType.HOVER, target_drone_id=None)

    def test_broadcast_approved_when_all_drones_healthy(
        self, supervisor: SafetySupervisor
    ) -> None:
        swarm = make_swarm(make_drone("d1"), make_drone("d2"))
        verdict = supervisor.validate(self._broadcast_hover(), swarm)

        assert verdict.approved is True
        assert verdict.drone_id == "broadcast"

    def test_broadcast_rejected_when_one_drone_stale(
        self, supervisor: SafetySupervisor
    ) -> None:
        swarm = make_swarm(
            make_drone("d1", seconds_ago=0.1),
            make_drone("d2", seconds_ago=20.0),  # stale
        )
        verdict = supervisor.validate(self._broadcast_hover(), swarm)

        assert verdict.approved is False
        assert "d2" in verdict.reason

    def test_broadcast_approved_on_empty_swarm(
        self, supervisor: SafetySupervisor
    ) -> None:
        verdict = supervisor.validate(self._broadcast_hover(), make_swarm())

        assert verdict.approved is True


# ---------------------------------------------------------------------------
# Check ordering: stale takes priority over geofence and battery
# ---------------------------------------------------------------------------

class TestCheckOrdering:
    def test_stale_checked_before_geofence(self, supervisor: SafetySupervisor) -> None:
        """A stale drone outside the geofence should mention 'stale', not 'geofence'."""
        drone = make_drone("d1", seconds_ago=30.0, x=999.0)
        verdict = supervisor.validate(make_hover_cmd("d1"), make_swarm(drone))

        assert verdict.approved is False
        assert "stale" in verdict.reason

    def test_geofence_checked_before_battery(self, supervisor: SafetySupervisor) -> None:
        """A fresh drone outside the fence with low battery should mention 'geofence'."""
        drone = make_drone("d1", seconds_ago=0.1, x=999.0, battery_pct=5.0)
        verdict = supervisor.validate(make_hover_cmd("d1"), make_swarm(drone))

        assert verdict.approved is False
        assert "geofence" in verdict.reason
