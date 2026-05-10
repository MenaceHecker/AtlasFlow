"""
Unit tests for worker/app/services/processor.py
"""
from __future__ import annotations

import json
import uuid
import pytest

from tests.conftest import _seed_event


# ── transition_to_processing ──────────────────────────────────────────────────

class TestTransitionToProcessing:
    def test_claims_created_event(self, aws_resources):
        from app.services.processor import transition_to_processing

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id, status="CREATED")

        claimed = transition_to_processing(event_id)
        assert claimed is True

        # verify DDB record was updated
        item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]
        assert item["status"] == "PROCESSING"

    def test_double_claim_returns_false(self, aws_resources):
        """At-least-once delivery guard: second claim on same event is rejected."""
        from app.services.processor import transition_to_processing

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id, status="CREATED")

        first = transition_to_processing(event_id)
        second = transition_to_processing(event_id)   # already PROCESSING

        assert first is True
        assert second is False

    def test_cannot_claim_completed_event(self, aws_resources):
        from app.services.processor import transition_to_processing

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id, status="COMPLETED")

        claimed = transition_to_processing(event_id)
        assert claimed is False

    def test_cannot_claim_failed_event(self, aws_resources):
        from app.services.processor import transition_to_processing

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id, status="FAILED")

        claimed = transition_to_processing(event_id)
        assert claimed is False


# ── mark_completed ────────────────────────────────────────────────────────────

class TestMarkCompleted:
    def test_sets_status_and_result(self, aws_resources):
        from app.services.processor import mark_completed

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id, status="PROCESSING")

        result = {"summary": "done", "event_id": event_id}
        mark_completed(event_id, result)

        item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]
        assert item["status"] == "COMPLETED"
        assert item["result"] == result


# ── mark_failed ───────────────────────────────────────────────────────────────

class TestMarkFailed:
    def test_sets_status_and_error(self, aws_resources):
        from app.services.processor import mark_failed

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id, status="PROCESSING")

        mark_failed(event_id, "something went wrong")

        item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]
        assert item["status"] == "FAILED"
        assert item["error"] == "something went wrong"


# ── process_message ───────────────────────────────────────────────────────────

class TestProcessMessage:
    def test_happy_path_marks_completed(self, aws_resources, monkeypatch):
        from app.services import processor

        # Disable random failure and sleep for deterministic test
        monkeypatch.setattr(processor.random, "random", lambda: 0.99)
        monkeypatch.setattr(processor.time, "sleep", lambda _: None)

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id, status="CREATED")

        processor.process_message(json.dumps({"event_id": event_id}))

        item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]
        assert item["status"] == "COMPLETED"

    def test_already_claimed_event_is_skipped(self, aws_resources, monkeypatch):
        """If another worker already claimed the event, process_message exits early."""
        from app.services import processor

        monkeypatch.setattr(processor.random, "random", lambda: 0.99)
        monkeypatch.setattr(processor.time, "sleep", lambda _: None)

        event_id = str(uuid.uuid4())
        # seed as PROCESSING (already claimed)
        _seed_event(aws_resources["events_table"], event_id, status="PROCESSING")

        # should not raise
        processor.process_message(json.dumps({"event_id": event_id}))

        item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]
        # status unchanged
        assert item["status"] == "PROCESSING"

    def test_simulated_error_propagates(self, aws_resources, monkeypatch):
        """RuntimeError from processing logic should propagate so SQS retries."""
        from app.services import processor

        monkeypatch.setattr(processor.random, "random", lambda: 0.0)   # always fail
        monkeypatch.setattr(processor.time, "sleep", lambda _: None)

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id, status="CREATED")

        with pytest.raises(RuntimeError, match="simulated processing error"):
            processor.process_message(json.dumps({"event_id": event_id}))
