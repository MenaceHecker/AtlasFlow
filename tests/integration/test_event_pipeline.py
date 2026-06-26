"""
Integration tests: full event pipeline via real LocalStack.

Tests the complete flow:
  POST /v1/events → SQS message → process_message() → DynamoDB COMPLETED

No mocks. Real DynamoDB, SQS, S3 backed by LocalStack.
"""
from __future__ import annotations

from integration.helpers import process_one, wait_for_status


class TestPingPipeline:
    def test_ping_event_completes_end_to_end(self, env):
        """POST a ping event; process it; verify COMPLETED status and echo result."""
        client = env["client"]
        infra = env["infra"]

        resp = client.post("/v1/events", json={"type": "ping", "payload": {"hello": "world"}})
        assert resp.status_code == 200
        event_id = resp.json()["event_id"]

        process_one(infra, event_id)

        item = wait_for_status(infra, event_id, "COMPLETED")
        assert item["result"]["status"] == "pong"
        assert item["result"]["echo"] == {"hello": "world"}

    def test_ping_event_visible_via_get(self, env):
        """After processing, GET /v1/events/{id} returns status COMPLETED."""
        client = env["client"]
        infra = env["infra"]

        resp = client.post("/v1/events", json={"type": "ping", "payload": {}})
        event_id = resp.json()["event_id"]

        process_one(infra, event_id)
        wait_for_status(infra, event_id, "COMPLETED")

        detail = client.get(f"/v1/events/{event_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["status"] == "COMPLETED"
        assert body["event_id"] == event_id
        # Internal fields must not be exposed
        assert "pk" not in body
        assert "s3_key" not in body
        assert "payload_inline" not in body


class TestDataTransformPipeline:
    def test_data_transform_uppercase(self, env):
        client = env["client"]
        infra = env["infra"]

        payload = {"fields": {"name": "alice", "city": "nyc"}, "operation": "uppercase"}
        resp = client.post("/v1/events", json={"type": "data.transform", "payload": payload})
        assert resp.status_code == 200
        event_id = resp.json()["event_id"]

        process_one(infra, event_id)

        item = wait_for_status(infra, event_id, "COMPLETED")
        assert item["result"]["transformed"]["name"] == "ALICE"
        assert item["result"]["transformed"]["city"] == "NYC"


class TestNotifyPipeline:
    def test_notify_email_completes(self, env):
        client = env["client"]
        infra = env["infra"]

        payload = {
            "channel": "email",
            "recipient": "test@example.com",
            "message": "Your order is ready!",
        }
        resp = client.post("/v1/events", json={"type": "notify", "payload": payload})
        assert resp.status_code == 200
        event_id = resp.json()["event_id"]

        process_one(infra, event_id)

        item = wait_for_status(infra, event_id, "COMPLETED")
        assert item["result"]["channel"] == "email"
        assert item["result"]["recipient"] == "test@example.com"
        assert item["result"]["delivered"] is True


class TestSchemaValidation:
    def test_unknown_event_type_rejected(self, env):
        """The API must reject unknown event types before they reach the queue."""
        client = env["client"]
        resp = client.post(
            "/v1/events",
            json={"type": "does.not.exist", "payload": {}},
        )
        assert resp.status_code == 422

    def test_invalid_notify_payload_rejected(self, env):
        """Missing required fields for notify must return 422."""
        client = env["client"]
        resp = client.post(
            "/v1/events",
            json={"type": "notify", "payload": {"channel": "email"}},
        )
        assert resp.status_code == 422

    def test_list_events_returns_processed_events(self, env):
        """GET /v1/events lists events after processing."""
        client = env["client"]
        infra = env["infra"]

        resp = client.post("/v1/events", json={"type": "ping", "payload": {}})
        event_id = resp.json()["event_id"]
        process_one(infra, event_id)
        wait_for_status(infra, event_id, "COMPLETED")

        list_resp = client.get("/v1/events?status=COMPLETED")
        assert list_resp.status_code == 200
        ids = [i["event_id"] for i in list_resp.json()["items"]]
        assert event_id in ids
