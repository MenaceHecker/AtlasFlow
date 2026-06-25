"""
Prometheus metrics for the AtlasFlow worker.

Metrics exposed on a background HTTP server at :9090/metrics:

    atlasflow_worker_messages_processed_total{event_type, outcome}
        Counter — incremented once per SQS message processed.
        outcome is one of: "completed", "failed", "skipped"

    atlasflow_worker_processing_duration_seconds{event_type}
        Histogram — wall-clock time from PROCESSING -> COMPLETED/FAILED.

Usage:
    from app.core.metrics import MESSAGES_PROCESSED, PROCESSING_DURATION
    MESSAGES_PROCESSED.labels(event_type="ping", outcome="completed").inc()
    PROCESSING_DURATION.labels(event_type="ping").observe(elapsed)
"""
from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram

# Custom registry avoids collision with the default global registry in tests.
REGISTRY = CollectorRegistry()

MESSAGES_PROCESSED: Counter = Counter(
    name="atlasflow_worker_messages_processed_total",
    documentation=(
        "Total SQS messages processed by the worker. "
        "'outcome' is one of: completed, failed, skipped."
    ),
    labelnames=["event_type", "outcome"],
    registry=REGISTRY,
)

PROCESSING_DURATION: Histogram = Histogram(
    name="atlasflow_worker_processing_duration_seconds",
    documentation="Wall-clock time (seconds) to process a single event.",
    labelnames=["event_type"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)
