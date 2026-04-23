"""
StateManager — single source of truth for swarm state held in memory.

Thread-safe via asyncio.Lock.  No persistence layer is wired up yet;
all state is lost on server restart (intentional for this scaffold).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Callable, Awaitable, List, Optional

from core.models import DroneState, SwarmState, TelemetryMessage
from logging_system.events import log_telemetry_received, log_position_update

logger = logging.getLogger(__name__)

# Subscriber callbacks receive the full SwarmState after every mutation
StateSubscriber = Callable[[SwarmState], Awaitable[None]]


class StateManager:
    """
    Manages the in-memory swarm state.

    Consumers can subscribe to state-change notifications so that
    the WebSocket broadcaster receives updates without polling.
    """

    def __init__(self) -> None:
        self._state = SwarmState()
        self._lock = asyncio.Lock()
        self._subscribers: List[StateSubscriber] = []

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_swarm_state(self) -> SwarmState:
        """Return a snapshot of the current swarm state (no lock needed for reads)."""
        return self._state.model_copy(deep=True)

    def get_drone_state(self, drone_id: str) -> Optional[DroneState]:
        return self._state.drones.get(drone_id)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def apply_telemetry(self, msg: TelemetryMessage) -> None:
        """
        Merge a full telemetry message into the swarm state.
        Creates a DroneState entry for previously-unknown drones.
        """
        async with self._lock:
            self._state.drones[msg.drone_id] = DroneState(
                drone_id=msg.drone_id,
                status=msg.status,
                position=msg.position,
                velocity=msg.velocity,
                battery_pct=msg.battery_pct,
                last_seen=msg.timestamp,
            )
            self._state.updated_at = datetime.utcnow()

        log_telemetry_received(msg)
        log_position_update(msg.drone_id, msg.position)
        await self._notify_subscribers()

    async def mark_drone_offline(self, drone_id: str) -> None:
        """Flag a drone as offline (e.g. when its MQTT heartbeat times out)."""
        from core.models import DroneStatus  # local import to avoid circularity

        async with self._lock:
            if drone_id in self._state.drones:
                self._state.drones[drone_id].status = DroneStatus.OFFLINE
                self._state.updated_at = datetime.utcnow()

        await self._notify_subscribers()

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def subscribe(self, callback: StateSubscriber) -> None:
        """Register an async callback invoked on every state change."""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: StateSubscriber) -> None:
        self._subscribers = [s for s in self._subscribers if s is not callback]

    async def _notify_subscribers(self) -> None:
        snapshot = self.get_swarm_state()
        for cb in self._subscribers:
            try:
                await cb(snapshot)
            except Exception:
                logger.exception("Subscriber %s raised an exception", cb)
