"""
Tests for event schema validation at the API ingestion layer.

These tests verify that:
  - Unknown event types are rejected with 422.
  - Payloads that violate the per-type Pydantic schema are rejected with 422.
  - Valid payloads for each registered type are accepted.
"""
from __future__ import annotations

# ── unknown event type ────────────────────────────────────────────────────────

class TestUnknownEventType:
    def test_unknown_type_returns_422(self, api_client):
        resp = api_client.post(
            "/v1/events",
            json={"type": "order.placed", "payload": {}},
        )
        assert resp.status_code == 422

    def test_unknown_type_error_mentions_type(self, api_client):
        resp = api_client.post(
            "/v1/events",
            json={"type": "totally.unknown.thing", "payload": {}},
        )
        assert resp.status_code == 422
        body = resp.json()
        # FastAPI validation errors are structured; the message should name the bad type
        errors = body.get("detail", [])
        combined = " ".join(str(e) for e in errors)
        assert "totally.unknown.thing" in combined

    def test_known_types_are_all_accepted(self, api_client):
        """Smoke-test that every registered type passes the type validator."""
        valid_payloads = {
            "ping": {},
            "data.transform": {"fields": {"x": "hello"}, "operation": "uppercase"},
            "notify": {"channel": "email", "recipient": "test@example.com", "message": "hi"},
        }
        for event_type, payload in valid_payloads.items():
            resp = api_client.post(
                "/v1/events",
                json={"type": event_type, "payload": payload},
            )
            assert resp.status_code == 200, (
                f"Expected 200 for registered type {event_type!r}, "
                f"got {resp.status_code}: {resp.text}"
            )


# ── per-type payload validation ───────────────────────────────────────────────

class TestNotifyPayloadValidation:
    """notify requires channel, recipient, and message."""

    def test_missing_channel_returns_422(self, api_client):
        resp = api_client.post(
            "/v1/events",
            json={
                "type": "notify",
                "payload": {"recipient": "a@b.com", "message": "hello"},
            },
        )
        assert resp.status_code == 422

    def test_missing_recipient_returns_422(self, api_client):
        resp = api_client.post(
            "/v1/events",
            json={
                "type": "notify",
                "payload": {"channel": "email", "message": "hello"},
            },
        )
        assert resp.status_code == 422

    def test_missing_message_returns_422(self, api_client):
        resp = api_client.post(
            "/v1/events",
            json={
                "type": "notify",
                "payload": {"channel": "email", "recipient": "a@b.com"},
            },
        )
        assert resp.status_code == 422

    def test_valid_notify_payload_accepted(self, api_client):
        resp = api_client.post(
            "/v1/events",
            json={
                "type": "notify",
                "payload": {
                    "channel": "sms",
                    "recipient": "+15551234567",
                    "message": "Your order is ready.",
                },
            },
        )
        assert resp.status_code == 200


class TestDataTransformPayloadValidation:
    """data.transform: fields defaults to {} and operation defaults to 'uppercase'."""

    def test_empty_payload_uses_defaults(self, api_client):
        """Empty payload is valid — all fields have defaults."""
        resp = api_client.post(
            "/v1/events",
            json={"type": "data.transform", "payload": {}},
        )
        assert resp.status_code == 200

    def test_explicit_operation_accepted(self, api_client):
        resp = api_client.post(
            "/v1/events",
            json={
                "type": "data.transform",
                "payload": {
                    "fields": {"name": "Alice"},
                    "operation": "reverse",
                },
            },
        )
        assert resp.status_code == 200


class TestPingPayloadValidation:
    """ping accepts any payload (extra fields allowed)."""

    def test_empty_payload_accepted(self, api_client):
        resp = api_client.post(
            "/v1/events",
            json={"type": "ping", "payload": {}},
        )
        assert resp.status_code == 200

    def test_arbitrary_payload_accepted(self, api_client):
        resp = api_client.post(
            "/v1/events",
            json={"type": "ping", "payload": {"foo": "bar", "nested": {"x": 1}}},
        )
        assert resp.status_code == 200
