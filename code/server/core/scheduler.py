"""
SwarmScheduler — the main control loop.

Runs at a configurable frequency (SCHEDULER_HZ env var, default 5 Hz).
Each tick:
  1. Reads the current SwarmState snapshot from StateManager.
  2. Passes it to the active algorithm to generate candidate Commands.
  3. Validates each command through SafetySupervisor.
  4. Publishes approved commands via MQTTClient.
  5. Emits structured log events for each outcome.

The scheduler is intentionally decoupled from all subsystems via
constructor injection so it can be unit-tested without a live broker.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, List, Optional

from core.config import settings
from core.models import Command, SwarmState
from core.safety import SafetySupervisor
from core.state_manager import StateManager
from logging_system.events import log_command_sent, log_safety_rejection

logger = logging.getLogger(__name__)

# Type alias for algorithm callables: takes SwarmState, returns List[Command]
AlgorithmFn = Callable[[SwarmState], List[Command]]

# Type alias for the publish function injected from MQTTClient
PublishFn = Callable[[Command], Awaitable[None]]


class SwarmScheduler:
    """
    Periodic control loop that ties algorithm output to MQTT dispatch.

    Args:
        state_manager:  Source of truth for swarm state.
        algorithm:      Callable that maps SwarmState → List[Command].
        publish:        Async callable that sends a Command over MQTT.
        supervisor:     SafetySupervisor instance (uses defaults if omitted).
        hz:             Loop frequency in Hz (overrides settings.scheduler_hz if given).
    """

    def __init__(
        self,
        state_manager: StateManager,
        algorithm: AlgorithmFn,
        publish: PublishFn,
        supervisor: Optional[SafetySupervisor] = None,
        hz: Optional[float] = None,
    ) -> None:
        self._state_manager = state_manager
        self._algorithm = algorithm
        self._publish = publish
        self._supervisor = supervisor or SafetySupervisor()
        self._hz = hz if hz is not None else settings.scheduler_hz
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Schedule the control loop as a background asyncio Task."""
        if self._task and not self._task.done():
            logger.warning("Scheduler already running — ignoring start()")
            return
        self._task = asyncio.create_task(self._loop(), name="swarm-scheduler")
        logger.info("Scheduler started at %.1f Hz", self._hz)

    async def stop(self) -> None:
        """Cancel the loop and wait for clean shutdown."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler stopped")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        interval = 1.0 / self._hz
        logger.debug("Scheduler loop interval: %.3f s", interval)

        while True:
            tick_start = asyncio.get_event_loop().time()
            try:
                await self._tick()
            except Exception:
                # Never let a single bad tick kill the loop
                logger.exception("Unhandled error in scheduler tick")

            elapsed = asyncio.get_event_loop().time() - tick_start
            sleep_for = max(0.0, interval - elapsed)
            await asyncio.sleep(sleep_for)

    async def _tick(self) -> None:
        """Single scheduler iteration."""
        swarm = self._state_manager.get_swarm_state()

        if not swarm.drones:
            return  # nothing to do if no drones have been seen yet

        commands: List[Command] = self._algorithm(swarm)

        for cmd in commands:
            verdict = self._supervisor.validate(cmd, swarm)

            if verdict.approved:
                await self._publish(cmd)
                log_command_sent(cmd)
            else:
                log_safety_rejection(cmd, verdict.reason)
