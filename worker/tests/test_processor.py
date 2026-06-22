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
        assert item["updated_at"] != item["created_at"]
        assert "updatedAt" not in item

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

    def test_claims_failed_event_for_retry(self, aws_resources):
        from app.services.processor import transition_to_processing

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id, status="FAILED")

        claimed = transition_to_processing(event_id)
        assert claimed is True

        item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]
        assert item["status"] == "PROCESSING"
        assert item["attempts"] == 1


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
        assert item["updated_at"] != item["created_at"]
        assert "updatedAt" not in item


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
        assert item["updated_at"] != item["created_at"]
        assert "updatedAt" not in item


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
        def _raise(*a: object, **kw: object) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(registry, "dispatch", _raise)

        with pytest.raises(RuntimeError, match="boom"):
            processor.process_message(json.dumps({"event_id": event_id}))

        item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]
        assert item["status"] == "FAILED"
        assert "boom" in item["error"]

    def test_failed_event_is_retried_and_completed(self, aws_resources, monkeypatch):
        """A redelivered message can reclaim a FAILED event and complete it."""
        from app.services import processor
        from app.services.handlers.registry import registry

        event_id = str(uuid.uuid4())
        _seed_event(aws_resources["events_table"], event_id, status="CREATED")
        aws_resources["events_table"].update_item(
            Key={"pk": f"EVENT#{event_id}"},
            UpdateExpression="SET #t = :t",
            ExpressionAttributeNames={"#t": "type"},
            ExpressionAttributeValues={":t": "retry.test"},
        )

        calls = 0

        def fail_once_then_succeed(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("transient failure")
            return {"retried": True}

        monkeypatch.setattr(registry, "dispatch", fail_once_then_succeed)

        with pytest.raises(RuntimeError, match="transient failure"):
            processor.process_message(json.dumps({"event_id": event_id}))

        failed_item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]
        assert failed_item["status"] == "FAILED"
        assert failed_item["attempts"] == 1

        processor.process_message(json.dumps({"event_id": event_id}))

        completed_item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]
        assert completed_item["status"] == "COMPLETED"
        assert completed_item["attempts"] == 2
        assert completed_item["result"] == {"retried": True}
        assert "error" not in completed_item
