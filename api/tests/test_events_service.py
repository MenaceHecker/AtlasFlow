"""
Unit tests for events_service.py
"""
from __future__ import annotations

import json
import pytest


# ── create_event ──────────────────────────────────────────────────────────────

class TestCreateEvent:
    def test_creates_new_event_no_idempotency_key(self, aws_resources):
        from app.services.events_service import create_event, get_event

        event_id, reused = create_event("order.placed", {"amount": 10}, None)

        assert reused is False
        assert event_id is not None

        item = get_event(event_id)
        assert item is not None
        assert item["event_id"] == event_id
        assert item["type"] == "order.placed"
        assert item["status"] == "CREATED"
        assert item["payload_inline"] == {"amount": 10}

    def test_enqueues_message_on_create(self, aws_resources):
        from app.services.events_service import create_event
        from app.services.aws_clients import sqs_client

        # clear cache so client uses mocked SQS
        from app.services import aws_clients
        aws_clients.sqs_client.cache_clear()

        event_id, _ = create_event("user.signup", {"email": "a@b.com"}, None)

        sqs = sqs_client()
        resp = sqs.receive_message(
            QueueUrl=aws_resources["queue_url"],
            MaxNumberOfMessages=1,
            WaitTimeSeconds=0,
        )
        msgs = resp.get("Messages", [])
        assert len(msgs) == 1
        body = json.loads(msgs[0]["Body"])
        assert body["event_id"] == event_id

    def test_idempotency_key_returns_same_event_id(self, aws_resources):
        from app.services.events_service import create_event

        key = "idem-key-001"
        id1, reused1 = create_event("order.placed", {}, key)
        id2, reused2 = create_event("order.placed", {}, key)

        assert id1 == id2
        assert reused1 is False
        assert reused2 is True

    def test_different_idempotency_keys_create_different_events(self, aws_resources):
        from app.services.events_service import create_event

        id1, _ = create_event("order.placed", {}, "key-A")
        id2, _ = create_event("order.placed", {}, "key-B")

        assert id1 != id2

    def test_no_key_always_creates_new_event(self, aws_resources):
        from app.services.events_service import create_event

        id1, _ = create_event("order.placed", {}, None)
        id2, _ = create_event("order.placed", {}, None)

        assert id1 != id2

    def test_enqueue_failure_removes_event(self, aws_resources, monkeypatch):
        from app.services import events_service

        monkeypatch.setattr(
            events_service, "_get_queue_url", lambda: aws_resources["queue_url"]
        )
        monkeypatch.setattr(
            events_service, "sqs_client", lambda: aws_resources["sqs"]
        )
        monkeypatch.setattr(
            aws_resources["sqs"],
            "send_message",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("SQS unavailable")),
        )

        with pytest.raises(RuntimeError, match="SQS unavailable"):
            events_service.create_event("order.placed", {}, None)

        items = aws_resources["events_table"].scan().get("Items", [])
        assert items == []

    def test_enqueue_failure_releases_idempotency_key(
        self, aws_resources, monkeypatch
    ):
        from app.services import events_service

        original_send_message = aws_resources["sqs"].send_message
        calls = 0

        def fail_once(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("SQS unavailable")
            return original_send_message(**kwargs)

        monkeypatch.setattr(
            events_service, "_get_queue_url", lambda: aws_resources["queue_url"]
        )
        monkeypatch.setattr(
            events_service, "sqs_client", lambda: aws_resources["sqs"]
        )
        monkeypatch.setattr(aws_resources["sqs"], "send_message", fail_once)

        key = "retryable-idempotency-key"
        with pytest.raises(RuntimeError, match="SQS unavailable"):
            events_service.create_event("order.placed", {}, key)

        assert aws_resources["events_table"].scan().get("Items", []) == []
        assert aws_resources["idem_table"].get_item(
            Key={"pk": f"IDEMP#{key}"}
        ).get("Item") is None

        event_id, reused = events_service.create_event("order.placed", {}, key)

        assert reused is False
        assert events_service.get_event(event_id) is not None


# ── get_event ─────────────────────────────────────────────────────────────────

class TestGetEvent:
    def test_returns_none_for_missing_event(self, aws_resources):
        from app.services.events_service import get_event

        assert get_event("does-not-exist") is None

    def test_returns_item_for_existing_event(self, aws_resources):
        from app.services.events_service import create_event, get_event

        event_id, _ = create_event("ping", {}, None)
        item = get_event(event_id)

        assert item is not None
        assert item["event_id"] == event_id


# ── list_events ───────────────────────────────────────────────────────────────

class TestListEvents:
    def test_scan_returns_all_events(self, aws_resources):
        from app.services.events_service import create_event, list_events

        for i in range(3):
            create_event(f"type.{i}", {}, None)

        result = list_events(status=None, limit=25, last_pk=None)
        assert len(result["items"]) == 3

    def test_limit_is_respected(self, aws_resources):
        from app.services.events_service import create_event, list_events

        for i in range(5):
            create_event("type.x", {}, None)

        result = list_events(status=None, limit=2, last_pk=None)
        assert len(result["items"]) <= 2

    def test_pagination_next_token(self, aws_resources):
        from app.services.events_service import create_event, list_events

        for i in range(4):
            create_event("type.p", {}, None)

        page1 = list_events(status=None, limit=2, last_pk=None)
        assert len(page1["items"]) == 2

        if page1["next_token"]:
            page2 = list_events(status=None, limit=2, last_pk=page1["next_token"])
            assert len(page2["items"]) > 0
            # no overlap
            ids1 = {i["event_id"] for i in page1["items"]}
            ids2 = {i["event_id"] for i in page2["items"]}
            assert ids1.isdisjoint(ids2)

    def test_filter_by_status(self, aws_resources):
        from app.services.events_service import create_event, list_events

        create_event("type.q", {}, None)

        result = list_events(status="CREATED", limit=25, last_pk=None)
        assert all(i["status"] == "CREATED" for i in result["items"])

    def test_next_token_is_opaque_base64(self, aws_resources):
        """The cursor must not expose raw DynamoDB key values like 'EVENT#<uuid>'."""
        import base64
        import json
        from app.services.events_service import create_event, list_events

        for i in range(3):
            create_event(f"type.cursor.{i}", {}, None)

        result = list_events(status=None, limit=2, last_pk=None)
        token = result["next_token"]

        assert token is not None
        # Must be valid base64 that decodes to JSON (not a raw pk string)
        decoded = json.loads(base64.urlsafe_b64decode(token.encode()))
        assert isinstance(decoded, dict)
        assert "pk" in decoded
        # The token itself must not look like a raw DynamoDB pk
        assert not token.startswith("EVENT#")

    def test_malformed_cursor_raises_value_error(self, aws_resources):
        import pytest
        from app.services.events_service import list_events

        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            list_events(status=None, limit=10, last_pk="not-valid-base64!!!")

