"""
Centralised logging configuration.

Call configure_logging() once at server startup.  All modules then use
the standard logging.getLogger(__name__) pattern and inherit this config.
"""

from __future__ import annotations

import logging
import os
import sys

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

_FMT = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
_DATE_FMT = "%Y-%m-%dT%H:%M:%S"


def configure_logging() -> None:
    """Apply a structured, human-readable log format to the root logger."""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format=_FMT,
        datefmt=_DATE_FMT,
        stream=sys.stdout,
        force=True,  # override any library that called basicConfig first
    )
    # Quieten noisy third-party loggers
    logging.getLogger("aiomqtt").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
