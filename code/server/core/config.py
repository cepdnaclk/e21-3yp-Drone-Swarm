"""
Server configuration loaded from environment variables (or .env file).

All values have safe defaults so the server starts without any extra setup.
Import the singleton `settings` everywhere instead of reading os.getenv directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


def _env_float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


def _env_int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


@dataclass(frozen=True)
class GeofenceBounds:
    """Axis-aligned box in metres (local frame)."""
    x_min: float = -50.0
    x_max: float =  50.0
    y_min: float = -50.0
    y_max: float =  50.0
    z_min: float =   0.0   # floor (ground level)
    z_max: float =  30.0   # ceiling


@dataclass(frozen=True)
class Settings:
    # MQTT broker
    mqtt_host: str              = field(default_factory=lambda: os.getenv("MQTT_HOST", "localhost"))
    mqtt_port: int              = field(default_factory=lambda: _env_int("MQTT_PORT", 1883))
    mqtt_username: Optional[str]= field(default_factory=lambda: os.getenv("MQTT_USERNAME"))
    mqtt_password: Optional[str]= field(default_factory=lambda: os.getenv("MQTT_PASSWORD"))

    # Scheduler
    scheduler_hz: float         = field(default_factory=lambda: _env_float("SCHEDULER_HZ", 5.0))

    # Safety thresholds
    stale_timeout_s: float      = field(default_factory=lambda: _env_float("STALE_TIMEOUT_S", 5.0))
    low_battery_pct: float      = field(default_factory=lambda: _env_float("LOW_BATTERY_PCT", 20.0))
    geofence: GeofenceBounds    = field(default_factory=GeofenceBounds)

    # Logging
    log_level: str              = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())


# Module-level singleton — import this everywhere
settings = Settings()
