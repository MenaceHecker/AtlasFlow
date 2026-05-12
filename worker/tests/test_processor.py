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

        item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]
        assert item["status"] == "PROCESSING"

    def test_double_claim_returns_false(self, aws_resources):
        """At-least-once delivery guard: second claim on the same event is rejected."""
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


# ── process_message (dispatch integration) ────────────────────────────────────

class TestProcessMessage:
    """
    These tests verify that process_message correctly orchestrates:
    fetch -> claim -> dispatch -> mark_completed/mark_failed.
    Handler logic is not tested here (see test_handlers.py).
    """

    def test_ping_event_marks_completed(self, aws_resources):
        """A 'ping' event should be dispatched to PingHandler and mark COMPLETED."""
        from app.services import processor

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id, status="CREATED")
        # Override event type to ping
        aws_resources["events_table"].update_item(
            Key={"pk": f"EVENT#{event_id}"},
            UpdateExpression="SET #t = :t",
            ExpressionAttributeNames={"#t": "type"},
            ExpressionAttributeValues={":t": "ping"},
        )

        processor.process_message(json.dumps({"event_id": event_id}))

        item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]
        assert item["status"] == "COMPLETED"
        assert item["result"]["pong"] is True

    def test_already_claimed_event_is_skipped(self, aws_resources):
        """If another worker already claimed the event, process_message exits early."""
        from app.services import processor

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id, status="PROCESSING")

        # Should not raise
        processor.process_message(json.dumps({"event_id": event_id}))

        item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]
        assert item["status"] == "PROCESSING"   # unchanged

    def test_missing_event_id_is_skipped(self, aws_resources):
        """If the event_id doesn't exist in DDB, the message is skipped cleanly."""
        from app.services import processor

        non_existent = str(uuid.uuid4())
        # Should not raise
        processor.process_message(json.dumps({"event_id": non_existent}))

    def test_unknown_event_type_uses_fallback(self, aws_resources):
        """An unregistered event type is handled by FallbackHandler, not a crash."""
        from app.services import processor

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id, status="CREATED")
        aws_resources["events_table"].update_item(
            Key={"pk": f"EVENT#{event_id}"},
            UpdateExpression="SET #t = :t",
            ExpressionAttributeNames={"#t": "type"},
            ExpressionAttributeValues={":t": "completely.unknown.type"},
        )

        processor.process_message(json.dumps({"event_id": event_id}))

        item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]
        assert item["status"] == "COMPLETED"
        assert item["result"]["handler"] == "FallbackHandler"

    def test_handler_exception_marks_failed_and_reraises(self, aws_resources, monkeypatch):
        """If dispatch raises, the event is marked FAILED and the exception propagates."""
        from app.services import processor
        from app.services.handlers.registry import registry

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id, status="CREATED")
        aws_resources["events_table"].update_item(
            Key={"pk": f"EVENT#{event_id}"},
            UpdateExpression="SET #t = :t",
            ExpressionAttributeNames={"#t": "type"},
            ExpressionAttributeValues={":t": "ping"},
        )

        # Monkeypatch the registry's dispatch to raise
        monkeypatch.setattr(registry, "dispatch", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))

        with pytest.raises(RuntimeError, match="boom"):
            processor.process_message(json.dumps({"event_id": event_id}))

        item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]
        assert item["status"] == "FAILED"
        assert "boom" in item["error"]
