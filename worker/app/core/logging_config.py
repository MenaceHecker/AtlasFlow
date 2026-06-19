"""
Structured logging configuration for the AtlasFlow worker.

Call ``configure_logging()`` once at process startup (e.g. at the top of
main.py before any other imports that trigger logging).

JSON output fields:
    timestamp   – ISO-8601 UTC
    level       – INFO / WARNING / ERROR …
    logger      – dotted module name
    message     – the log message string
    **kwargs    – any extra fields passed via ``extra={"event_id": …}``

Set LOG_FORMAT=text for human-readable output during local development.
"""
from __future__ import annotations

import logging
import os
import sys

from pythonjsonlogger.json import JsonFormatter


def configure_logging() -> None:
    """Configure the root logger for the worker process."""
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    log_format = os.getenv("LOG_FORMAT", "json").lower()

    handler = logging.StreamHandler(sys.stdout)

    formatter: logging.Formatter
    if log_format == "json":
        formatter = JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
            rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
        )
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()
    root.addHandler(handler)

    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
