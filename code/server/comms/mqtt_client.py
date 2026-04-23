"""
MQTT client scaffolding using aiomqtt (async wrapper over paho-mqtt).

Topic conventions (configurable via env / settings):
  Inbound telemetry  →  telemetry/{drone_id}/full
  Outbound commands  →  commands/{drone_id}   (or commands/broadcast)

The client:
  1. Connects to the broker on startup.
  2. Subscribes to wildcard telemetry topics.
  3. Dispatches each message to StateManager.apply_telemetry().
  4. Exposes publish_command() for algorithm/API layers to send commands.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from core.models import Command, TelemetryMessage
from core.state_manager import StateManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Broker settings — override via environment variables
# ---------------------------------------------------------------------------
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME: Optional[str] = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD: Optional[str] = os.getenv("MQTT_PASSWORD")

TOPIC_TELEMETRY_WILDCARD = "telemetry/+/full"
TOPIC_COMMAND_PREFIX = "commands"


class MQTTClient:
    """
    Async MQTT client.

    Uses aiomqtt when available; falls back to a no-op stub so the server
    can start in environments where the broker is not yet reachable.
    """

    def __init__(self, state_manager: StateManager) -> None:
        self._state_manager = state_manager
        self._client = None  # aiomqtt.Client instance, set on connect
        self._listen_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        try:
            import aiomqtt  # optional dependency
        except ImportError:
            logger.warning(
                "aiomqtt not installed — MQTT disabled.  "
                "Install with: pip install aiomqtt"
            )
            return

        logger.info("Connecting to MQTT broker at %s:%d …", MQTT_HOST, MQTT_PORT)
        try:
            self._client = aiomqtt.Client(
                hostname=MQTT_HOST,
                port=MQTT_PORT,
                username=MQTT_USERNAME,
                password=MQTT_PASSWORD,
            )
            await self._client.__aenter__()
            await self._client.subscribe(TOPIC_TELEMETRY_WILDCARD)
            logger.info("Subscribed to %s", TOPIC_TELEMETRY_WILDCARD)
            self._listen_task = asyncio.create_task(self._listen_loop())
        except Exception:
            logger.exception("MQTT connection failed — running without broker")
            self._client = None

    async def disconnect(self) -> None:
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        if self._client is not None:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:
                pass
            self._client = None
        logger.info("MQTT client disconnected")

    # ------------------------------------------------------------------
    # Inbound — telemetry listener
    # ------------------------------------------------------------------

    async def _listen_loop(self) -> None:
        """Continuously receive messages and forward to StateManager."""
        logger.info("MQTT listen loop started")
        try:
            async for message in self._client.messages:
                await self._dispatch(message)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("MQTT listen loop crashed")

    async def _dispatch(self, message) -> None:
        """Parse a raw MQTT message and apply it to the swarm state."""
        topic = str(message.topic)
        try:
            payload = json.loads(message.payload)
        except json.JSONDecodeError:
            logger.warning("Non-JSON payload on topic %s — ignored", topic)
            return

        # Route based on topic pattern
        if topic.startswith("telemetry/") and topic.endswith("/full"):
            await self._handle_telemetry(topic, payload)
        else:
            logger.debug("Unhandled topic %s", topic)

    async def _handle_telemetry(self, topic: str, payload: dict) -> None:
        try:
            msg = TelemetryMessage(**payload)
            await self._state_manager.apply_telemetry(msg)
        except Exception:
            logger.exception("Failed to parse telemetry on %s", topic)

    # ------------------------------------------------------------------
    # Outbound — command publisher
    # ------------------------------------------------------------------

    async def publish_command(self, command: Command) -> None:
        """
        Serialize and publish a Command to the appropriate MQTT topic.

        Topic:
          commands/{drone_id}   — targeted command
          commands/broadcast    — command for all drones
        """
        if self._client is None:
            logger.warning("MQTT not connected — command not sent: %s", command)
            return

        target = command.target_drone_id or "broadcast"
        topic = f"{TOPIC_COMMAND_PREFIX}/{target}"

        try:
            payload = command.model_dump_json()
            await self._client.publish(topic, payload)
            logger.info("Published command %s → %s", command.command_type, topic)
        except Exception:
            logger.exception("Failed to publish command to %s", topic)
