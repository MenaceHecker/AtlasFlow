"""
Prometheus metrics for the AtlasFlow API.

Metrics exposed on GET /metrics (mounted as a separate ASGI app):

    atlasflow_events_ingested_total{event_type}
        Counter — incremented once per new event created at ingestion.
        Deduplicated (idempotent) requests do NOT increment this counter.

    atlasflow_api_request_duration_seconds{method, path, status_code}
        Histogram — records the wall-clock time of every HTTP request.

Usage:
    from app.core.metrics import EVENTS_INGESTED, API_REQUEST_DURATION
    EVENTS_INGESTED.labels(event_type="ping").inc()
"""
from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, make_asgi_app

# Use a custom registry so tests can instantiate a clean one without
# colliding with the global default registry.
REGISTRY = CollectorRegistry()

EVENTS_INGESTED: Counter = Counter(
    name="atlasflow_events_ingested_total",
    documentation="Total number of new events ingested (deduplicated requests excluded).",
    labelnames=["event_type"],
    registry=REGISTRY,
)

API_REQUEST_DURATION: Histogram = Histogram(
    name="atlasflow_api_request_duration_seconds",
    documentation="HTTP request duration in seconds, by method, path, and status code.",
    labelnames=["method", "path", "status_code"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
    registry=REGISTRY,
)

# ASGI app that serves the /metrics endpoint — mounted in main.py
metrics_app = make_asgi_app(registry=REGISTRY)
