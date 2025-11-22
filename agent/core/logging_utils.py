"""
Logging setup for the agent.
Creates console and file handlers with structured format.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .config import Settings


def setup_logging(settings: Settings):
    log_dir = settings.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "agent.log"

    fmt = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format=fmt,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    logging.getLogger(__name__).info("Logging initialized at %s", log_file)
