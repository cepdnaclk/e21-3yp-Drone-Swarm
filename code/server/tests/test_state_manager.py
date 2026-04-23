"""
Tests for core.state_manager.StateManager.

All tests are async (pytest-asyncio).  The StateManager holds no external
dependencies so no mocking is required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import pytest
import pytest_asyncio

from core.models import DroneStatus, SwarmState
from core.state_manager import StateManager
from tests.conftest import make_telemetry


@pytest.fixture()
def manager() -> StateManager:
    return StateManager()


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------

class TestInitialState:
    def test_empty_swarm_on_init(self, manager: StateManager) -> None:
        state = manager.get_swarm_state()
        assert state.drones == {}

    def test_get_drone_state_missing_returns_none(self, manager: StateManager) -> None:
        assert manager.get_drone_state("ghost") is None


# ---------------------------------------------------------------------------
# apply_telemetry
# ---------------------------------------------------------------------------

class TestApplyTelemetry:
    @pytest.mark.asyncio
    async def test_adds_new_drone(self, manager: StateManager) -> None:
        msg = make_telemetry(drone_id="d1", battery_pct=90.0)
        await manager.apply_telemetry(msg)

        state = manager.get_swarm_state()
        assert "d1" in state.drones
        assert state.drones["d1"].battery_pct == pytest.approx(90.0)

    @pytest.mark.asyncio
    async def test_updates_existing_drone(self, manager: StateManager) -> None:
        await manager.apply_telemetry(make_telemetry("d1", battery_pct=90.0))
        await manager.apply_telemetry(make_telemetry("d1", battery_pct=55.0))

        assert manager.get_swarm_state().drones["d1"].battery_pct == pytest.approx(55.0)

    @pytest.mark.asyncio
    async def test_position_stored_correctly(self, manager: StateManager) -> None:
        msg = make_telemetry("d2", x=3.0, y=-1.5, z=7.0)
        await manager.apply_telemetry(msg)

        pos = manager.get_swarm_state().drones["d2"].position
        assert pos.x == pytest.approx(3.0)
        assert pos.y == pytest.approx(-1.5)
        assert pos.z == pytest.approx(7.0)

    @pytest.mark.asyncio
    async def test_updated_at_advances(self, manager: StateManager) -> None:
        before = manager.get_swarm_state().updated_at
        await manager.apply_telemetry(make_telemetry())
        after = manager.get_swarm_state().updated_at
        assert after >= before

    @pytest.mark.asyncio
    async def test_multiple_drones_tracked_independently(self, manager: StateManager) -> None:
        await manager.apply_telemetry(make_telemetry("d1", battery_pct=80.0))
        await manager.apply_telemetry(make_telemetry("d2", battery_pct=40.0))

        state = manager.get_swarm_state()
        assert len(state.drones) == 2
        assert state.drones["d1"].battery_pct == pytest.approx(80.0)
        assert state.drones["d2"].battery_pct == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# mark_drone_offline
# ---------------------------------------------------------------------------

class TestMarkDroneOffline:
    @pytest.mark.asyncio
    async def test_marks_known_drone_offline(self, manager: StateManager) -> None:
        await manager.apply_telemetry(make_telemetry("d1"))
        await manager.mark_drone_offline("d1")

        assert manager.get_swarm_state().drones["d1"].status == DroneStatus.OFFLINE

    @pytest.mark.asyncio
    async def test_silently_ignores_unknown_drone(self, manager: StateManager) -> None:
        # Should not raise
        await manager.mark_drone_offline("nonexistent")


# ---------------------------------------------------------------------------
# Snapshot isolation
# ---------------------------------------------------------------------------

class TestSnapshotIsolation:
    @pytest.mark.asyncio
    async def test_get_swarm_state_returns_copy(self, manager: StateManager) -> None:
        await manager.apply_telemetry(make_telemetry("d1", battery_pct=80.0))

        snapshot = manager.get_swarm_state()
        # Mutating the snapshot must not affect internal state
        snapshot.drones["d1"].battery_pct = 1.0

        assert manager.get_swarm_state().drones["d1"].battery_pct == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# Subscriber notifications
# ---------------------------------------------------------------------------

class TestSubscribers:
    @pytest.mark.asyncio
    async def test_subscriber_called_on_telemetry(self, manager: StateManager) -> None:
        received: List[SwarmState] = []

        async def capture(state: SwarmState) -> None:
            received.append(state)

        manager.subscribe(capture)
        await manager.apply_telemetry(make_telemetry("d1"))

        assert len(received) == 1
        assert "d1" in received[0].drones

    @pytest.mark.asyncio
    async def test_subscriber_called_on_mark_offline(self, manager: StateManager) -> None:
        await manager.apply_telemetry(make_telemetry("d1"))

        received: List[SwarmState] = []

        async def capture(state: SwarmState) -> None:
            received.append(state)

        manager.subscribe(capture)
        await manager.mark_drone_offline("d1")

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_notifications(self, manager: StateManager) -> None:
        calls: List[int] = []

        async def counter(state: SwarmState) -> None:
            calls.append(1)

        manager.subscribe(counter)
        await manager.apply_telemetry(make_telemetry("d1"))
        manager.unsubscribe(counter)
        await manager.apply_telemetry(make_telemetry("d1", battery_pct=50.0))

        assert len(calls) == 1  # only the first call was received

    @pytest.mark.asyncio
    async def test_crashing_subscriber_does_not_break_others(
        self, manager: StateManager
    ) -> None:
        ok_calls: List[int] = []

        async def bad(_: SwarmState) -> None:
            raise RuntimeError("subscriber crash")

        async def good(_: SwarmState) -> None:
            ok_calls.append(1)

        manager.subscribe(bad)
        manager.subscribe(good)
        await manager.apply_telemetry(make_telemetry("d1"))

        assert len(ok_calls) == 1
