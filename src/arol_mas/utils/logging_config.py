"""Centralized logging setup. Called once from the CLI entrypoint."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from arol_mas.config import Settings


def configure_logging(settings: Settings) -> None:
    log_dir = settings.resolve(settings.logging.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "arol_mas.log"

    level = getattr(logging, settings.logging.level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)
