"""
Localization stub — placeholder for the real localization pipeline.

Replace this module with actual UWB / vision / IMU fusion logic.
The interface (estimate_position) must remain compatible so callers
do not need to change when the real implementation lands.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.models import Position

logger = logging.getLogger(__name__)


def estimate_position(drone_id: str, raw_sensor_data: dict) -> Optional[Position]:
    """
    Estimate a drone's position from raw sensor data.

    Args:
        drone_id:        ID of the drone whose position is being estimated.
        raw_sensor_data: Dict of sensor readings (UWB ranges, IMU, etc.).

    Returns:
        Estimated Position, or None if estimation is not possible.

    NOTE: Currently a stub — returns None and logs a warning.
    """
    logger.debug(
        "Localization stub called for drone %s — returning None (not implemented)",
        drone_id,
    )
    return None
