"""
Integration tests: DLQ replay via /v1/admin/dlq/replay against real LocalStack.

Tests the full flow:
  Seed FAILED event → POST /v1/admin/dlq/replay → event re-queued → process → COMPLETED.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from tests.integration.conftest import DLQ_NAME, process_one, wait_for_status

ADMIN_KEY = "inttest-admin-key"


class TestDlqReplay:
    def _seed_failed_event(self, infra, event_id: str) -> None:
        """Insert a FAILED event into DDB and a message onto the DLQ."""
        now = datetime.now(UTC).isoformat()
        infra["events_table"].put_item(
            Item={
                "pk": f"EVENT#{event_id}",
                "event_id": event_id,
                "type": "ping",
                "status": "FAILED",
                "created_at": now,
                "updated_at": now,
                "attempts": 3,
                "payload_inline": {"from": "dlq"},
                "error": "simulated failure",
            }
        )
        dlq_url = infra["sqs"].get_queue_url(QueueName=DLQ_NAME)["QueueUrl"]
        infra["sqs"].send_message(
            QueueUrl=dlq_url,
            MessageBody=json.dumps({"event_id": event_id}),
        )

    def test_replay_moves_failed_event_to_main_queue(self, env):
        """Replaying a FAILED DLQ event re-queues it and resets status to CREATED."""
        import uuid
        client = env["client"]
        infra = env["infra"]
        event_id = str(uuid.uuid4())

        self._seed_failed_event(infra, event_id)

        resp = client.post(
            "/v1/admin/dlq/replay",
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["replayed"] >= 1

        # Status must now be CREATED (reset by the replay)
        item = infra["events_table"].get_item(Key={"pk": f"EVENT#{event_id}"})["Item"]
        assert item["status"] == "CREATED"

    def test_replay_then_process_completes_event(self, env):
        """Full cycle: FAILED → replay → process_message() → COMPLETED."""
        import uuid
        client = env["client"]
        infra = env["infra"]
        event_id = str(uuid.uuid4())

        self._seed_failed_event(infra, event_id)

        # Replay
        client.post(
            "/v1/admin/dlq/replay",
            headers={"X-Admin-Key": ADMIN_KEY},
        )

        # Now process it
        process_one(infra, event_id)

        item = wait_for_status(infra, event_id, "COMPLETED", timeout=10.0)
        assert item["result"]["status"] == "pong"

    def test_replay_skips_non_failed_event(self, env):
        """Events that are already COMPLETED are skipped during replay."""
        import uuid
        client = env["client"]
        infra = env["infra"]
        event_id = str(uuid.uuid4())

        # Seed a COMPLETED event on the DLQ (shouldn't happen in prod, but let's be safe)
        now = datetime.now(UTC).isoformat()
        infra["events_table"].put_item(
            Item={
                "pk": f"EVENT#{event_id}",
                "event_id": event_id,
                "type": "ping",
                "status": "COMPLETED",
                "created_at": now,
                "updated_at": now,
                "attempts": 1,
                "payload_inline": {},
            }
        )
        dlq_url = infra["sqs"].get_queue_url(QueueName=DLQ_NAME)["QueueUrl"]
        infra["sqs"].send_message(
            QueueUrl=dlq_url,
            MessageBody=json.dumps({"event_id": event_id}),
        )

        resp = client.post(
            "/v1/admin/dlq/replay",
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["skipped"] >= 1

        # Status must remain COMPLETED
        item = infra["events_table"].get_item(Key={"pk": f"EVENT#{event_id}"})["Item"]
        assert item["status"] == "COMPLETED"

    def test_replay_requires_admin_key(self, env):
        """Admin endpoint must be protected."""
        client = env["client"]
        resp = client.post("/v1/admin/dlq/replay")
        assert resp.status_code == 401
