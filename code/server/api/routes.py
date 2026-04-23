"""
HTTP REST routes.

  GET  /health       — liveness probe
  GET  /swarm/state  — full swarm state snapshot
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter

from core.state_manager import StateManager
from core.models import SwarmState


def build_router(state_manager: StateManager) -> APIRouter:
    router = APIRouter()

    @router.get("/health", response_model=Dict[str, Any], tags=["meta"])
    async def health() -> Dict[str, Any]:
        """Liveness probe. Returns 200 while the server is running."""
        return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

    @router.get("/swarm/state", response_model=SwarmState, tags=["swarm"])
    async def get_swarm_state() -> SwarmState:
        """Return the latest in-memory snapshot of the entire swarm."""
        return state_manager.get_swarm_state()

    return router
