"""
WebSocket endpoint — live swarm state stream.

  WS  /ws/swarm

Clients connect and receive a JSON-serialised SwarmState message every
time the StateManager publishes a state change.  On connect the client
immediately receives the current state so it can render without waiting.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.state_manager import StateManager, StateSubscriber
from core.models import SwarmState

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Keeps track of active WebSocket connections and fans out state updates."""

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        logger.info("WS client connected  (total: %d)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        logger.info("WS client disconnected (total: %d)", len(self._connections))

    async def broadcast(self, state: SwarmState) -> None:
        """Send state JSON to all connected clients; drop stale connections."""
        payload = state.model_dump_json()
        dead: Set[WebSocket] = set()

        for ws in list(self._connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)

        for ws in dead:
            self._connections.discard(ws)


def build_ws_router(state_manager: StateManager) -> APIRouter:
    router = APIRouter()
    manager = ConnectionManager()

    # Wire the manager's broadcast into the state-change pipeline
    state_manager.subscribe(manager.broadcast)

    @router.websocket("/ws/swarm")
    async def swarm_ws(websocket: WebSocket) -> None:
        await manager.connect(websocket)

        # Push current state immediately so the client isn't left blank
        current = state_manager.get_swarm_state()
        await websocket.send_text(current.model_dump_json())

        try:
            # Keep the socket alive; we push updates via the subscriber callback
            while True:
                await websocket.receive_text()  # ignore client→server messages for now
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    return router
