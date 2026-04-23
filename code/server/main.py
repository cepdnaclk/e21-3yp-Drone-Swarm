"""
Drone Swarm Server — entry point.

Starts the FastAPI application and initialises all subsystems:
  - MQTT client (comms)
  - State manager (core)
  - Swarm scheduler (core)
  - API routes and WebSocket endpoint (api)
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from algorithms.hover import hover
from comms.mqtt_client import MQTTClient
from core.scheduler import SwarmScheduler
from core.safety import SafetySupervisor
from core.state_manager import StateManager
from api.routes import build_router
from api.websocket import build_ws_router
from logging_system.logger import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

# Shared singletons — instantiated once and passed around via app.state
state_manager = StateManager()
mqtt_client = MQTTClient(state_manager=state_manager)
scheduler = SwarmScheduler(
    state_manager=state_manager,
    algorithm=hover,
    publish=mqtt_client.publish_command,
    supervisor=SafetySupervisor(),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle handler."""
    logger.info("Starting drone swarm server …")
    await mqtt_client.connect()
    scheduler.start()
    yield
    logger.info("Shutting down drone swarm server …")
    await scheduler.stop()
    await mqtt_client.disconnect()


app = FastAPI(
    title="Drone Swarm Server",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(build_router(state_manager))
app.include_router(build_ws_router(state_manager))
