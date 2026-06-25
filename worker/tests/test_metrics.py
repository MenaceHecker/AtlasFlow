"""
Tests for Prometheus metrics in the AtlasFlow worker processor.

These tests verify:
  - messages_processed_total increments with the correct labels on success.
  - messages_processed_total increments with outcome=failed on handler exception.
  - messages_processed_total increments with outcome=skipped for double-claim.
  - messages_processed_total increments with outcome=skipped for missing events.
  - processing_duration_seconds histogram is populated after dispatch.
"""
from __future__ import annotations

import json
import uuid

from tests.conftest import _seed_event


def _counter_value(metric, labels: dict) -> float:
    """Read the _total sample value for a given label set."""
    samples = metric.collect()[0].samples
    for s in samples:
        if s.name.endswith("_total") and s.labels == labels:
            return s.value
    return 0.0


def _histogram_count(metric, labels: dict) -> float:
    """Read the _count sample for a histogram label set."""
    samples = metric.collect()[0].samples
    for s in samples:
        if s.name.endswith("_count") and s.labels == labels:
            return s.value
    return 0.0


class TestProcessorMetrics:
    def test_completed_event_increments_counter(self, aws_resources):
        from app.core.metrics import MESSAGES_PROCESSED
        from app.services.processor import process_message

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id)

        before = _counter_value(
            MESSAGES_PROCESSED, {"event_type": "test.event", "outcome": "completed"}
        )

        process_message(json.dumps({"event_id": event_id}))

        after = _counter_value(
            MESSAGES_PROCESSED, {"event_type": "test.event", "outcome": "completed"}
        )
        assert after == before + 1

    def test_completed_event_records_duration(self, aws_resources):
        from app.core.metrics import PROCESSING_DURATION
        from app.services.processor import process_message

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id)

        before = _histogram_count(PROCESSING_DURATION, {"event_type": "test.event"})

        process_message(json.dumps({"event_id": event_id}))

        after = _histogram_count(PROCESSING_DURATION, {"event_type": "test.event"})
        assert after == before + 1

    def test_failed_event_increments_failed_counter(self, aws_resources, monkeypatch):
        import pytest

        from app.core.metrics import MESSAGES_PROCESSED
        from app.services import processor

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id)

        from app.services.handlers.builtin import PingHandler

        def boom(self, event_id, payload):
            raise ValueError("handler exploded")

        monkeypatch.setattr(PingHandler, "handle", boom)

        # _seed_event creates a 'test.event' type which uses FallbackHandler —
        # we need to use 'ping' and make PingHandler fail
        from datetime import UTC, datetime
        now = datetime.now(UTC).isoformat()
        aws_resources["events_table"].put_item(Item={
            "pk": f"EVENT#{event_id}",
            "event_id": event_id,
            "type": "ping",
            "status": "CREATED",
            "created_at": now,
            "updated_at": now,
            "attempts": 0,
            "payload_inline": {},
        })

        before = _counter_value(
            MESSAGES_PROCESSED, {"event_type": "ping", "outcome": "failed"}
        )

        with pytest.raises(ValueError, match="handler exploded"):
            processor.process_message(json.dumps({"event_id": event_id}))

        after = _counter_value(
            MESSAGES_PROCESSED, {"event_type": "ping", "outcome": "failed"}
        )
        assert after == before + 1

    def test_double_claimed_event_increments_skipped(self, aws_resources):
        from app.core.metrics import MESSAGES_PROCESSED
        from app.services.processor import process_message, transition_to_processing

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id)

        # Claim it manually first
        transition_to_processing(event_id)

        before = _counter_value(
            MESSAGES_PROCESSED, {"event_type": "test.event", "outcome": "skipped"}
        )

        process_message(json.dumps({"event_id": event_id}))

        after = _counter_value(
            MESSAGES_PROCESSED, {"event_type": "test.event", "outcome": "skipped"}
        )
        assert after == before + 1

    def test_missing_event_increments_skipped(self, aws_resources):
        from app.core.metrics import MESSAGES_PROCESSED
        from app.services.processor import process_message

        before = _counter_value(
            MESSAGES_PROCESSED, {"event_type": "unknown", "outcome": "skipped"}
        )

        process_message(json.dumps({"event_id": "does-not-exist"}))

        after = _counter_value(
            MESSAGES_PROCESSED, {"event_type": "unknown", "outcome": "skipped"}
        )
        assert after == before + 1
