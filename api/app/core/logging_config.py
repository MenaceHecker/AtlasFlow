"""
Structured logging configuration for the AtlasFlow API.

Call ``configure_logging()`` once at application startup (e.g. in main.py).
Every subsequent ``logging.getLogger(__name__)`` call in the codebase will
then produce JSON-formatted lines that include:

    timestamp   – ISO-8601 UTC
    level       – INFO / WARNING / ERROR …
    logger      – dotted module name
    message     – the log message string
    **kwargs    – any extra fields passed via ``extra={"event_id": …}``

In local development, set LOG_FORMAT=text in your .env to get a
human-readable format instead of JSON.
"""
from __future__ import annotations

import logging
import os
import sys

from pythonjsonlogger.json import JsonFormatter


def configure_logging() -> None:
    """Configure the root logger for the API process."""
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
        # Human-readable fallback for local development (LOG_FORMAT=text)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(log_level)
    # Remove any handlers that uvicorn or another library may have added.
    root.handlers.clear()
    root.addHandler(handler)

    # Quiet noisy third-party loggers.
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
