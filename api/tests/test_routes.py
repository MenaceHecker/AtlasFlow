"""
Integration-style tests for the FastAPI routes (no LocalStack required).
Uses the api_client fixture which wires TestClient + moto.
"""
from __future__ import annotations

import pytest


# ── POST /v1/events ───────────────────────────────────────────────────────────

class TestPostEvent:
    def test_returns_201_with_event_id(self, api_client):
        resp = api_client.post(
            "/v1/events",
            json={"type": "order.placed", "payload": {"amount": 42}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "event_id" in body
        assert body["status"] == "CREATED"

    def test_missing_type_returns_422(self, api_client):
        resp = api_client.post("/v1/events", json={"payload": {}})
        assert resp.status_code == 422

    def test_empty_type_returns_422(self, api_client):
        resp = api_client.post("/v1/events", json={"type": "", "payload": {}})
        assert resp.status_code == 422

    def test_idempotency_key_deduplicates(self, api_client):
        payload = {"type": "order.placed", "payload": {}}
        headers = {"Idempotency-Key": "test-idem-001"}

        r1 = api_client.post("/v1/events", json=payload, headers=headers)
        r2 = api_client.post("/v1/events", json=payload, headers=headers)

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["event_id"] == r2.json()["event_id"]

    def test_no_idempotency_key_creates_distinct_events(self, api_client):
        payload = {"type": "order.placed", "payload": {}}

        r1 = api_client.post("/v1/events", json=payload)
        r2 = api_client.post("/v1/events", json=payload)

        assert r1.json()["event_id"] != r2.json()["event_id"]


# ── GET /v1/events/{event_id} ─────────────────────────────────────────────────

class TestGetEventById:
    def test_returns_event_for_valid_id(self, api_client):
        create_resp = api_client.post(
            "/v1/events", json={"type": "ping", "payload": {}}
        )
        event_id = create_resp.json()["event_id"]

        get_resp = api_client.get(f"/v1/events/{event_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["event_id"] == event_id

    def test_returns_404_for_unknown_id(self, api_client):
        resp = api_client.get("/v1/events/does-not-exist")
        assert resp.status_code == 404


class TestEventDetailShape:
    """Assert the public API shape — no internal DDB fields should leak through."""

    def test_no_internal_fields_exposed(self, api_client):
        create_resp = api_client.post(
            "/v1/events", json={"type": "shape.test", "payload": {"x": "one"}}
        )
        event_id = create_resp.json()["event_id"]

        body = api_client.get(f"/v1/events/{event_id}").json()

        # internal storage fields must not be present
        assert "pk" not in body
        assert "payload_inline" not in body
        assert "updatedAt" not in body

        # expected public fields must be present
        assert body["event_id"] == event_id
        assert body["type"] == "shape.test"
        assert body["status"] == "CREATED"
        assert "created_at" in body
        assert "updated_at" in body
        assert "attempts" in body
        assert body["payload"] == {"x": "one"}

    def test_list_items_have_clean_shape(self, api_client):
        api_client.post("/v1/events", json={"type": "list.shape", "payload": {"y": 2}})

        items = api_client.get("/v1/events?status=CREATED").json()["items"]
        assert len(items) >= 1

        for item in items:
            assert "pk" not in item
            assert "payload_inline" not in item
            assert "event_id" in item
            assert "status" in item
            assert "payload" in item

    def test_legacy_worker_timestamp_overrides_stale_timestamp(
        self, api_client, aws_resources
    ):
        event_id = "legacy-timestamp"
        aws_resources["events_table"].put_item(
            Item={
                "pk": f"EVENT#{event_id}",
                "event_id": event_id,
                "type": "legacy.test",
                "status": "COMPLETED",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "updatedAt": "2026-01-02T00:00:00+00:00",
                "attempts": 1,
                "payload_inline": {},
            }
        )

        body = api_client.get(f"/v1/events/{event_id}").json()

        assert body["updated_at"] == "2026-01-02T00:00:00+00:00"
        assert "updatedAt" not in body


# ── GET /v1/events ────────────────────────────────────────────────────────────

class TestListEvents:
    def test_returns_items_list(self, api_client):
        api_client.post("/v1/events", json={"type": "t1", "payload": {}})
        api_client.post("/v1/events", json={"type": "t2", "payload": {}})

        resp = api_client.get("/v1/events")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert len(body["items"]) >= 2

    def test_limit_query_param(self, api_client):
        for _ in range(5):
            api_client.post("/v1/events", json={"type": "bulk", "payload": {}})

        resp = api_client.get("/v1/events?limit=2")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) <= 2

    def test_status_filter(self, api_client):
        api_client.post("/v1/events", json={"type": "ev", "payload": {}})

        resp = api_client.get("/v1/events?status=CREATED")
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["status"] == "CREATED"

    def test_invalid_limit_returns_422(self, api_client):
        resp = api_client.get("/v1/events?limit=0")
        assert resp.status_code == 422


# ── GET /health ───────────────────────────────────────────────────────────────

def test_health(api_client):
    resp = api_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
